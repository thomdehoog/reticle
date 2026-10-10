"""Image and video upload, and delivery of the bytes.

Bytes are served from an application route rather than from a static directory
so that the login applies to them too. A guide can contain a photograph of an
access badge, a licence key taped to an instrument or an unpublished result;
none of that should be reachable by anyone who guesses a URL.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from typing import BinaryIO

from fastapi import APIRouter, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy import ColumnElement, exists, or_, select
from sqlalchemy.orm import Session as DbSession
from starlette.datastructures import UploadFile

from .. import audit, errors, images, videos
from ..auth import AnyUser, AuthorUser, DbDep, client_address
from ..models import PUBLISHED, Guide, Media, Page, PageMedia, Step, StepMedia, new_id
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


def _store_image(payload: bytes, settings: Settings) -> Media:
    normalised = images.normalise(payload, settings.max_image_dimension, settings.max_image_pixels)
    media_id = new_id()
    storage_path = images.relative_storage_path(media_id, normalised.extension)
    images.write_file(settings.media_root, storage_path, normalised.payload)
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
        (settings.media_root / media.storage_path).unlink(missing_ok=True)
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
    was readable one image at a time by anybody with an account. This is the
    visibility rule asked of every path that can put an upload in front of a
    reader — a step of a guide, the hero of a page, the body of a page.
    """
    in_published_guide = exists(
        select(StepMedia.id)
        .join(Step, Step.id == StepMedia.step_id)
        .join(Guide, Guide.id == Step.guide_id)
        .where(StepMedia.media_id == Media.id, Guide.status == PUBLISHED)
    )
    hero_of_published_page = exists(
        select(Page.id).where(Page.hero_media_id == Media.id, Page.status == PUBLISHED)
    )
    in_published_page_body = exists(
        select(PageMedia.page_id)
        .join(Page, Page.id == PageMedia.page_id)
        .where(PageMedia.media_id == Media.id, Page.status == PUBLISHED)
    )
    return or_(in_published_guide, hero_of_published_page, in_published_page_body)


@router.get("/{media_id}")
def read_media(media_id: str, db: DbDep, user: AnyUser) -> FileResponse:
    """The bytes, with ``Range`` honoured so that a video can seek."""
    statement = select(Media).where(Media.id == media_id)
    if user.role == "viewer":
        statement = statement.where(shown_to_viewers())
    media = db.scalars(statement).one_or_none()
    if media is None:
        raise errors.not_found("That file does not exist.")

    path = images.resolve_file(get_settings().media_root, media.storage_path)
    return FileResponse(
        path,
        media_type=media.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{media.id}.{path.suffix.lstrip(".")}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": MEDIA_CONTENT_SECURITY_POLICY,
            "Cache-Control": "private, max-age=3600",
        },
    )
