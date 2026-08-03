"""Image upload and delivery.

Bytes are served from an application route rather than from a static directory
so that the login applies to them too. A guide can contain a photograph of an
access badge, a licence key taped to an instrument or an unpublished result;
none of that should be reachable by anyone who guesses a URL.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm.attributes import InstrumentedAttribute

from .. import audit, errors, images, videos
from ..auth import AuthorUser, DbDep, MaybeUser, client_address
from ..models import (
    EVERYONE,
    PUBLISHED,
    Annotation,
    Category,
    Guide,
    Media,
    Page,
    Step,
    StepMedia,
    User,
    new_id,
)
from ..schemas import MediaOut, media_out
from ..settings import Settings, get_settings
from ..storage import build_storage
from ..visibility import sees_unpublished

router = APIRouter(prefix="/api/media", tags=["media"])

MULTIPART_HEADROOM_BYTES = 1024 * 1024


@router.post("", response_model=MediaOut, status_code=status.HTTP_201_CREATED)
def upload_media(
    request: Request,
    db: DbDep,
    user: AuthorUser,
    file: UploadFile = File(...),
    alt: str = Form(default=""),
) -> MediaOut:
    settings = get_settings()

    # Which ceiling applies depends on whether this is a clip or a photograph,
    # and that is decided by the first twelve bytes rather than by anything the
    # caller declares. Sniffing before reading is what makes ``max_video_bytes``
    # reachable at all: measuring the whole body against the image cap first
    # refuses a 21 MB clip as an oversized *image*, which is exactly the file
    # the video path exists to accept.
    header = file.file.read(videos.HEADER_BYTES)
    file.file.seek(0)
    is_video = videos.looks_like_video(header)
    cap = settings.max_video_bytes if is_video else settings.max_upload_bytes
    noun = "Videos" if is_video else "Images"

    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit():
        if int(declared) > cap + MULTIPART_HEADROOM_BYTES:
            raise errors.payload_too_large(f"{noun} must be at most {cap // (1024 * 1024)} MB.")

    payload = images.read_within_limit(file.file, cap, noun)

    if is_video:
        return _store_video(payload, request, db, user, alt, settings)

    normalised = images.normalise(payload, settings.max_image_dimension, settings.max_image_pixels)

    media_id = new_id()
    storage_path = images.relative_storage_path(media_id, normalised.extension)
    build_storage(settings).write(storage_path, normalised.payload)

    media = Media(
        id=media_id,
        storage_path=storage_path,
        content_type=normalised.content_type,
        kind="image",
        byte_size=len(normalised.payload),
        width=normalised.width,
        height=normalised.height,
        alt=alt,
        original_filename=(file.filename or "")[:300],
        uploaded_by_id=user.id,
    )
    db.add(media)
    audit.record(
        db,
        action="media.upload",
        entity_type="media",
        entity_id=media.id,
        actor=user,
        ip_address=client_address(request),
        detail={
            "contentType": normalised.content_type,
            "byteSize": media.byte_size,
            "width": normalised.width,
            "height": normalised.height,
        },
    )
    db.commit()
    return media_out(media)


def _store_video(
    payload: bytes,
    request: Request,
    db: DbSession,
    user: User,
    alt: str,
    settings: Settings,
) -> MediaOut:
    """Persist a step video.

    The size cap is its own setting rather than the image one — a fifteen-second
    clip of a stage moving is an order of magnitude larger than any photograph —
    and it has already been applied by the time the bytes arrive here: the
    caller sniffs the container first so that it can stream the body against
    ``max_video_bytes`` instead of ``max_upload_bytes``.
    """
    identified = videos.identify(payload)
    media_id = new_id()
    storage_path = images.relative_storage_path(media_id, identified.extension)
    build_storage(settings).write(storage_path, payload)

    media = Media(
        id=media_id,
        storage_path=storage_path,
        content_type=identified.content_type,
        kind="video",
        byte_size=len(payload),
        width=None,
        height=None,
        alt=alt,
        original_filename="",
        uploaded_by_id=user.id,
    )
    db.add(media)
    audit.record(
        db,
        action="media.upload",
        entity_type="media",
        entity_id=media.id,
        actor=user,
        ip_address=client_address(request),
        detail={
            "contentType": identified.content_type,
            "byteSize": media.byte_size,
            "kind": "video",
        },
    )
    db.commit()
    return media_out(media)


GUIDE_IS_READABLE = (Guide.status == PUBLISHED, Guide.visibility == EVERYONE)
"""Both halves of it.

Authentication was once the only gate on the bytes, and authentication is not
visibility: a viewer correctly given 404 for a draft guide was given 200 for the
photographs inside it, so the unpublished pipeline was readable one image at a
time by anybody with an account. A staff guide reopens the same hole through the
other half — it *is* published, so a check on status alone waves its pictures
through, and a screenshot of an access-control panel is the kind of thing one
carries.
"""


def _shown_in_a_readable_guide(db: DbSession, media_id: str) -> bool:
    return bool(
        db.scalar(
            select(func.count())
            .select_from(StepMedia)
            .join(Step, Step.id == StepMedia.step_id)
            .join(Guide, Guide.id == Step.guide_id)
            .where(StepMedia.media_id == media_id, *GUIDE_IS_READABLE)
        )
    )


def _played_by_a_readable_guide(db: DbSession, media_id: str) -> bool:
    return bool(
        db.scalar(
            select(func.count())
            .select_from(Step)
            .join(Guide, Guide.id == Step.guide_id)
            .where(Step.video_media_id == media_id, *GUIDE_IS_READABLE)
        )
    )


def _heading_a_published_page(db: DbSession, media_id: str) -> bool:
    return bool(
        db.scalar(
            select(func.count())
            .select_from(Page)
            .where(Page.hero_media_id == media_id, Page.status == PUBLISHED)
        )
    )


def _heading_a_section(db: DbSession, media_id: str) -> bool:
    """Unconditional, because ``categories.list_categories`` is.

    Every category is listed to every role, the hidden holding categories
    included — they are hidden from *browsing*, not from the API, which is how
    one LAS X guide reaches ten instrument headings. Narrowing this to visible
    categories would therefore refuse a picture the same request already handed
    the reader a URL for, which is a broken image rather than a kept secret.
    """
    return bool(
        db.scalar(
            select(func.count()).select_from(Category).where(Category.hero_media_id == media_id)
        )
    )


_DIRECT_REFERENCES: tuple[
    tuple[InstrumentedAttribute[Any], Callable[[DbSession, str], bool]], ...
] = (
    (StepMedia.media_id, _shown_in_a_readable_guide),
    (Step.video_media_id, _played_by_a_readable_guide),
    (Page.hero_media_id, _heading_a_published_page),
    (Category.hero_media_id, _heading_a_section),
)
"""Every column pointing at ``media.id`` whose owner carries its own rule."""

_POSTER_REFERENCE = Media.poster_media_id
"""The one column whose owner is another file.

A poster frame is displayed wherever the file it belongs to is displayed, so it
inherits that answer rather than holding a rule of its own. Nothing writes this
column over HTTP — the importer is its only author, and it sets one for every
vendor step video.
"""

_NOT_A_DISPLAY = (Annotation.media_id,)
"""Columns that point at a file without putting it on a screen.

An annotation is a shape drawn *over* an image — a child of it, not a container
that shows it — so its existence says nothing about who may see the image, and
it carries no rule. It is named here only so the completeness check below has an
answer for every foreign key rather than for the ones somebody remembered.
"""

MEDIA_REFERENCE_COLUMNS = (
    *(column for column, _ in _DIRECT_REFERENCES),
    _POSTER_REFERENCE,
    *_NOT_A_DISPLAY,
)
"""Every column in the schema that points at ``media.id``, each one classified.

This is the list that kept going stale. The rule was appended to three times,
once per newly-discovered reference, and was still two behind: a section picture
and a video's poster frame both answered 404 to viewers who had just been handed
their URLs. ``test_every_column_pointing_at_media_declares_who_may_read_it``
compares this tuple against the foreign keys SQLAlchemy actually holds, so the
next column fails the suite instead of becoming the fourth instance.

Reading the schema rather than the source is the point: ``Annotation.media_id``
was missed by an eye and by a grep for ``ForeignKey("media.id")``, because it is
written with an ``ondelete`` argument.
"""


def _displayed_by_something_a_viewer_can_open(db: DbSession, media_id: str) -> bool:
    """Whether any content a viewer may read actually puts this file on a screen.

    Walked rather than assumed one level deep: ``poster_media_id`` is a
    self-reference, so the schema permits a chain, and the ``seen`` set means a
    cycle in it is a false answer rather than a hung worker.
    """
    pending = {media_id}
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        if any(displays(db, current) for _, displays in _DIRECT_REFERENCES):
            return True
        pending.update(db.scalars(select(Media.id).where(Media.poster_media_id == current)).all())
    return False


@router.get("/{media_id}")
def read_media(media_id: str, db: DbDep, user: MaybeUser) -> Response:
    """Serve a file, once the caller has been shown to be allowed to see it.

    The visibility check above the storage call is the important line in this
    function, and it stays above it for every backend. A remote store is handed
    out as a short-lived signed URL **after** that check, never as a public
    object — otherwise the redirect becomes a way to read any file by id
    without a session, which is the hole this check exists to close.
    """
    media = db.get(Media, media_id)
    if media is None:
        raise errors.not_found("That file does not exist.")
    if not sees_unpublished(user) and not _displayed_by_something_a_viewer_can_open(db, media_id):
        raise errors.not_found("That file does not exist.")

    store = build_storage(get_settings())
    path = store.local_path(media.storage_path)
    if path is None:
        signed = store.signed_url(media.storage_path)
        if signed is None:
            raise errors.not_found("That file is no longer available.")
        # 302 rather than 301: the URL expires, and a permanent redirect would
        # be cached by the browser long past the point where it still works.
        return RedirectResponse(signed, status_code=302)

    return FileResponse(
        path,
        media_type=media.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{media.id}.{path.suffix.lstrip(".")}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )
