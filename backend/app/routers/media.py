"""Image and video upload, and delivery of the bytes.

Bytes are served from an application route rather than from a static directory
so that the login applies to them too. A guide can contain a photograph of an
access badge, a licence key taped to an instrument or an unpublished result;
none of that should be reachable by anyone who guesses a URL.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import os
from typing import BinaryIO, Literal

from fastapi import APIRouter, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy import ColumnElement, exists, or_, select
from sqlalchemy.orm import Session as DbSession
from starlette.datastructures import UploadFile

from .. import audit, errors, images, uploads, videos
from ..auth import AnyUser, AuthorUser, DbDep, client_address
from ..models import (
    PUBLISHED,
    Guide,
    Media,
    Page,
    PublishedGuideMedia,
    PublishedPageMedia,
    is_valid_id,
    new_id,
)
from ..schemas import MediaOut, media_out
from ..settings import Settings, get_settings

router = APIRouter(prefix="/api/media", tags=["media"])

MAX_ALT_CHARS = 1000

MEDIA_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'; sandbox"
)
"""What a browser may do with an upload it has been sent to directly.

Images are re-encoded, but a video is stored as it arrived, and a container
signature says nothing about the megabytes after it. If a browser were ever
persuaded to treat one as a document, this is what stops it running script with
the reader's session: nothing loads, nothing executes, and the origin is not
the application's.
"""


MEDIA_CACHE_CONTROL = "private, no-cache"
"""Keep a copy, but ask before using it.

A plain ``max-age`` let a browser show a picture from its disk cache for an
hour without asking anybody — including after the person who loaded it had
signed out, on an instrument PC the next person was now sitting at.
``no-cache`` makes every use a conditional request, which goes through the
login and the visibility rule like any other and costs a 304 when the answer is
still yes. ``private`` keeps it out of any shared cache in between.
"""


def _store_image(payload: bytes, settings: Settings) -> Media:
    processed = images.process(payload, settings.max_image_dimension, settings.max_image_pixels)
    normalised = processed.image
    media_id = new_id()
    storage_path = images.relative_storage_path(media_id, normalised.extension)
    images.write_file(settings.media_root, storage_path, normalised.payload)
    if processed.display is not None:
        images.write_file(settings.media_root, images.display_storage_path(storage_path), processed.display)
    return Media(
        id=media_id,
        kind="image",
        storage_path=storage_path,
        content_type=normalised.content_type,
        byte_size=len(normalised.payload),
        width=normalised.width,
        height=normalised.height,
    )


def _store_video(stream: BinaryIO, video_format: videos.VideoFormat, settings: Settings) -> Media:
    media_id = new_id()
    storage_path = images.relative_storage_path(media_id, video_format.extension)
    byte_size = videos.store(stream, settings.media_root, storage_path, settings.max_video_bytes)
    return Media(
        id=media_id,
        kind="video",
        storage_path=storage_path,
        content_type=video_format.content_type,
        byte_size=byte_size,
        width=None,
        height=None,
    )


def _accept_upload(
    db: DbSession,
    stream: BinaryIO,
    filename: str,
    alt: str,
    actor_id: str,
    address: str | None,
) -> MediaOut:
    """Decide what the file is from its own bytes, store it, and record it.

    The opening bytes choose the path. A recognised video container is copied
    to disk in chunks against the video cap; anything else is treated as an
    image, read against the much smaller image cap and decoded, which is what
    rejects everything that is neither.
    """
    settings = get_settings()
    # The spooled upload knows its own length, so the store's ceiling can be
    # applied before a byte is processed. The transaction that question opened
    # is ended again at once: what follows can take seconds, and on SQLite an
    # open write transaction is the only writer there is.
    stream.seek(0, os.SEEK_END)
    incoming = stream.tell()
    stream.seek(0)
    uploads.assert_room_for(db, settings, incoming)
    db.rollback()

    head = stream.read(videos.SNIFF_BYTES)
    stream.seek(0)
    video_format = videos.sniff(head)

    if video_format is not None:
        media = _store_video(stream, video_format, settings)
    elif videos.resembles_other_media(head):
        raise errors.validation_failed(videos.UNSUPPORTED_MESSAGE)
    else:
        media = _store_image(images.read_within_limit(stream, settings.max_upload_bytes), settings)

    media.alt = alt
    media.original_filename = filename[:300]
    media.uploaded_by_id = actor_id
    try:
        db.add(media)
        audit.record(
            db,
            action="media.upload",
            entity_type="media",
            entity_id=media.id,
            actor_id=actor_id,
            ip_address=address,
            detail={
                "kind": media.kind,
                "contentType": media.content_type,
                "byteSize": media.byte_size,
                "width": media.width,
                "height": media.height,
            },
        )
        db.commit()
    except BaseException:
        uploads.remove_files(settings.media_root, media.storage_path)
        raise
    return media_out(media)


@router.post("", response_model=MediaOut, status_code=status.HTTP_201_CREATED)
async def upload_media(request: Request, db: DbDep, user: AuthorUser) -> MediaOut:
    """Accept one file in the multipart field ``file``.

    The body is read here, by hand, rather than declared as a parameter. A
    declared upload is parsed before any dependency runs, which would let a
    caller with no session make the server spool two hundred megabytes to disk
    before being told to sign in. Reading it after ``AuthorUser`` has resolved
    means the answer to an unauthenticated or under-privileged upload is sent
    without accepting a byte of it.

    The session's transaction is ended before the body is awaited for the same
    kind of reason: authenticating opened it, a slow upload can take minutes,
    and on SQLite an open write transaction is the only writer there is.
    """
    actor_id = user.id
    address = client_address(request)
    await run_in_threadpool(db.rollback)

    form = await request.form(max_files=1, max_fields=4)
    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise errors.validation_failed("Upload one file in the form field named 'file'.")
        alt = form.get("alt")
        alt_text = alt if isinstance(alt, str) else ""
        if len(alt_text) > MAX_ALT_CHARS:
            raise errors.validation_failed(f"Alt text must be at most {MAX_ALT_CHARS} characters.")
        return await run_in_threadpool(
            _accept_upload, db, upload.file, upload.filename or "", alt_text, actor_id, address
        )
    finally:
        await form.close()


def shown_to_viewers() -> ColumnElement[bool]:
    """Whether something published actually displays this file.

    Authentication was once the only gate on the bytes, and authentication is
    not visibility: a viewer who was correctly given 404 for a draft guide was
    given 200 for the photographs inside it, so the whole unpublished pipeline
    was readable one image at a time by anybody with an account.

    "Published" means the published *snapshot*. The working copy's own links —
    ``step_media``, a page's hero, the references in its body — say what an
    author has put in, which includes the screenshot dropped into an edit five
    minutes ago that nobody has published. What a viewer may fetch is what the
    snapshot they are being served shows: the links written when it was
    published, for a guide or page that is still published now.
    """
    in_published_guide = exists(
        select(PublishedGuideMedia.owner_id)
        .join(Guide, Guide.id == PublishedGuideMedia.owner_id)
        .where(PublishedGuideMedia.media_id == Media.id, Guide.status == PUBLISHED)
    )
    in_published_page = exists(
        select(PublishedPageMedia.owner_id)
        .join(Page, Page.id == PublishedPageMedia.owner_id)
        .where(PublishedPageMedia.media_id == Media.id, Page.status == PUBLISHED)
    )
    return or_(in_published_guide, in_published_page)


def _entity_tag(media_id: str, variant: str, path: os.PathLike[str]) -> str:
    """A strong validator for exactly these bytes.

    The identifier names the upload, the variant says whether this is the
    original or the display copy, and the size and modification time change if
    the file on disk is ever replaced — a display copy made later, a restore.
    """
    stat = os.stat(path)
    return f'"{media_id}-{variant}-{stat.st_size:x}-{stat.st_mtime_ns:x}"'


def _matches(header: str | None, entity_tag: str) -> bool:
    """Whether an ``If-None-Match`` header names this entity tag.

    The comparison is the weak one the header calls for: a ``W/`` prefix on
    what the client sends is ignored.
    """
    if not header:
        return False
    candidates = [candidate.strip() for candidate in header.split(",")]
    return "*" in candidates or any(candidate.removeprefix("W/") == entity_tag for candidate in candidates)


@router.api_route("/{media_id}", methods=["GET", "HEAD"])
def read_media(
    media_id: str,
    request: Request,
    db: DbDep,
    user: AnyUser,
    size: Literal["display"] | None = None,
) -> Response:
    """The bytes, with ``Range`` honoured so that a video can seek.

    ``?size=display`` asks for the copy meant to be looked at: an image held to
    ``images.DISPLAY_MAX_SIDE`` on its longer edge. It is the same file as the
    original when the original is already that small, and for a video.

    Every response can be revalidated. A matching ``If-None-Match`` is answered
    304 — after the same login and visibility checks as a full response, which
    is the point of making the browser ask.

    ``HEAD`` is answered like ``GET`` without the bytes: it is how a player or
    a script asks whether a file is there, and how large, before fetching it.
    """
    statement = select(Media.id, Media.storage_path, Media.content_type, Media.kind, Media.width, Media.height).where(
        Media.id == media_id
    )
    if user.role == "viewer":
        statement = statement.where(shown_to_viewers())
    found = db.execute(statement).one_or_none()
    # Making a display copy can take a second or two; the connection is not
    # needed for it.
    db.close()
    if found is None:
        raise errors.not_found("That file does not exist.")

    media_root = get_settings().media_root
    variant = "original"
    if size == "display" and found.kind == "image":
        path = images.display_file(media_root, found.storage_path, found.width, found.height, found.content_type)
        variant = "display" if path.name != os.path.basename(found.storage_path) else "original"
    else:
        path = images.resolve_file(media_root, found.storage_path)

    entity_tag = _entity_tag(found.id, variant, path)
    headers = {
        "Content-Disposition": f'inline; filename="{found.id}.{path.suffix.lstrip(".")}"',
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": MEDIA_CONTENT_SECURITY_POLICY,
        "Cache-Control": MEDIA_CACHE_CONTROL,
        "ETag": entity_tag,
    }
    if _matches(request.headers.get("if-none-match"), entity_tag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return FileResponse(path, media_type=found.content_type, headers=headers)


@router.delete("/{media_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_media(media_id: str, request: Request, db: DbDep, user: AuthorUser, force: bool = False) -> Response:
    """Remove an upload for good: its row, its file and its display copy.

    An upload could once only ever be unlinked. A badge photographed by
    accident stayed on disk, in every backup, and fetchable by any author who
    had the address, with no way to make it not so.

    Who may: an administrator, or the person who uploaded the file. What may be
    deleted: a file nothing uses — no working copy and no published snapshot,
    past or present. One that is still used is refused with 409 and a list of
    where, because the usual cause is a mistake about which file this is.

    ``?force=true`` is the administrator's "this must be gone": the file is
    taken out of every working copy and every stored snapshot first, and their
    cached PDF exports are dropped. Backups made before this moment still
    contain it; that is a matter for whoever keeps the backups.
    """
    if force and user.role != "admin":
        raise errors.forbidden("Only an administrator can delete a file that is still in use.")
    media = db.get(Media, media_id) if is_valid_id(media_id) else None
    if media is None:
        raise errors.not_found("That file does not exist.")
    if user.role != "admin" and media.uploaded_by_id != user.id:
        raise errors.forbidden("Only the person who uploaded a file, or an administrator, can delete it.")

    settings = get_settings()
    uses = uploads.uses_of(db, media.id)
    if uses and not force:
        raise errors.conflict(uploads.still_used_message(uses))
    if uses:
        uploads.strip_everywhere(db, media.id, uses, user, settings)

    storage_path = media.storage_path
    audit.record(
        db,
        action="media.delete",
        entity_type="media",
        entity_id=media.id,
        actor=user,
        ip_address=client_address(request),
        detail={
            "kind": media.kind,
            "byteSize": media.byte_size,
            "uploadedBy": media.uploaded_by_id,
            "forced": bool(uses),
            "removedFrom": uses.counts(),
        },
    )
    db.delete(media)
    db.commit()
    uploads.remove_files(settings.media_root, storage_path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
