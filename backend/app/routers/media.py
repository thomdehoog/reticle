"""Image upload and delivery.

Bytes are served from an application route rather than from a static directory
so that the login applies to them too. A guide can contain a photograph of an
access badge, a licence key taped to an instrument or an unpublished result;
none of that should be reachable by anyone who guesses a URL.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .. import audit, errors, images, videos
from ..auth import AnyUser, AuthorUser, DbDep, client_address
from ..models import Guide, Media, Page, Step, StepMedia, new_id
from ..schemas import MediaOut, media_out
from ..settings import get_settings
from ..storage import get_storage
from .guides import READER_STATUS

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

    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit():
        if int(declared) > settings.max_upload_bytes + MULTIPART_HEADROOM_BYTES:
            raise errors.payload_too_large(
                f"Images must be at most {settings.max_upload_bytes // (1024 * 1024)} MB."
            )

    payload = images.read_within_limit(file.file, settings.max_upload_bytes)

    if videos.looks_like_video(payload):
        return _store_video(payload, request, db, user, alt, settings)

    normalised = images.normalise(payload, settings.max_image_dimension, settings.max_image_pixels)

    media_id = new_id()
    storage_path = images.relative_storage_path(media_id, normalised.extension)
    get_storage().write(storage_path, normalised.payload)

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
    user: Any,
    alt: str,
    settings: Any,
) -> MediaOut:
    """Persist a step video.

    The size cap is its own setting rather than the image one: a fifteen-second
    clip of a stage moving is an order of magnitude larger than any photograph,
    and holding video to the image limit would reject exactly the files this
    exists to accept.
    """
    if len(payload) > settings.max_video_bytes:
        raise errors.payload_too_large(
            f"Videos must be at most {settings.max_video_bytes // (1024 * 1024)} MB."
        )

    identified = videos.identify(payload)
    media_id = new_id()
    storage_path = images.relative_storage_path(media_id, identified.extension)
    get_storage().write(storage_path, payload)

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


def _shown_by_a_published_guide(db: DbSession, media_id: str) -> bool:
    """Whether any published guide actually displays this image.

    Authentication was the only gate on the bytes, and authentication is not
    visibility: a viewer who was correctly given 404 for a draft guide was given
    200 for the photographs inside it, so the whole unpublished pipeline was
    readable one image at a time by anybody with an account. This is the same
    rule ``guides._load_for`` applies to the surrounding text, asked of the
    ``StepMedia -> Step -> Guide`` path that put the image on a page.
    """
    in_a_step = db.scalar(
        select(func.count())
        .select_from(StepMedia)
        .join(Step, Step.id == StepMedia.step_id)
        .join(Guide, Guide.id == Step.guide_id)
        .where(StepMedia.media_id == media_id, Guide.status == READER_STATUS)
    )
    if in_a_step:
        return True

    # The video slot and a wiki page's hero image are two more ways a file
    # reaches a reader, and each was a second copy of the same hole.
    as_a_video = db.scalar(
        select(func.count())
        .select_from(Step)
        .join(Guide, Guide.id == Step.guide_id)
        .where(Step.video_media_id == media_id, Guide.status == READER_STATUS)
    )
    if as_a_video:
        return True

    as_a_hero = db.scalar(
        select(func.count())
        .select_from(Page)
        .where(Page.hero_media_id == media_id, Page.status == READER_STATUS)
    )
    return bool(as_a_hero)


@router.get("/{media_id}")
def read_media(media_id: str, db: DbDep, user: AnyUser) -> Response:
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
    if user.role == "viewer" and not _shown_by_a_published_guide(db, media_id):
        raise errors.not_found("That file does not exist.")

    store = get_storage()
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
