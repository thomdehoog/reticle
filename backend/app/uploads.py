"""The stored uploads as a collection: what uses each one, and removing one.

``routers.media`` takes a file in and hands its bytes out. This module answers
the questions that are about the store rather than about a request — is this
upload shown anywhere, how much is stored in all, what has to change for a file
to be truly gone — and it is shared by the delete endpoint and by
``python -m app.maintenance``, so the two cannot come to disagree about what
"unused" means.

"Used" is deliberately wide. An upload is in use if any working copy shows it,
*or any published snapshot ever did*: old versions stay readable, and a version
whose pictures have been collected from under it is not the version that was
published.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Text, delete, func, select, type_coerce
from sqlalchemy.orm import Session as DbSession

from . import errors, images, pdf, published
from .content import next_updated_at
from .models import (
    Guide,
    GuideRevision,
    Media,
    Page,
    PageMedia,
    PageRevision,
    PublishedGuide,
    PublishedGuideMedia,
    PublishedPage,
    PublishedPageMedia,
    Step,
    StepMedia,
    User,
)
from .settings import Settings

logger = logging.getLogger(__name__)

IDENTIFIER = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}")
"""Anything shaped like one of Reticle's identifiers.

Used to read which uploads a stored snapshot mentions without parsing it. It
over-matches on purpose — a guide's own identifier is found too — because the
result is only ever intersected with a set of upload identifiers, and the safe
mistake when deciding what may be deleted is to think something is in use.
"""

MAX_USES_NAMED = 5


@dataclass
class MediaUses:
    """Everywhere one upload appears."""

    guides: list[Guide] = field(default_factory=list)
    pages: list[Page] = field(default_factory=list)
    guide_revisions: list[GuideRevision] = field(default_factory=list)
    page_revisions: list[PageRevision] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.guides or self.pages or self.guide_revisions or self.page_revisions)

    def described(self) -> list[str]:
        """One phrase per place, working copies first, for the refusal message."""
        places = [f"the guide “{guide.title}”" for guide in self.guides]
        places += [f"the page “{page.title}”" for page in self.pages]
        places += [
            f"published version {revision.version} of the guide “{revision.document.get('title', '')}”"
            for revision in self.guide_revisions
        ]
        places += [
            f"published version {revision.version} of the page “{revision.document.get('title', '')}”"
            for revision in self.page_revisions
        ]
        return places

    def counts(self) -> dict[str, int]:
        return {
            "guides": len(self.guides),
            "pages": len(self.pages),
            "guideRevisions": len(self.guide_revisions),
            "pageRevisions": len(self.page_revisions),
        }


def _mentions(column: Any, media_id: str) -> Any:
    """A snapshot whose stored text contains the identifier.

    A scan of the snapshot table, which is fine here and nowhere else: this
    runs when an administrator deletes one file, not when a reader opens a page.
    """
    return type_coerce(column, Text).like(f"%{media_id}%")


def uses_of(db: DbSession, media_id: str) -> MediaUses:
    guides = db.scalars(
        select(Guide)
        .where(
            Guide.id.in_(
                select(Step.guide_id).join(StepMedia, StepMedia.step_id == Step.id).where(StepMedia.media_id == media_id)
            )
        )
        .order_by(Guide.title)
    ).all()
    pages = db.scalars(
        select(Page)
        .where(
            (Page.hero_media_id == media_id)
            | Page.id.in_(select(PageMedia.page_id).where(PageMedia.media_id == media_id))
        )
        .order_by(Page.title)
    ).all()
    guide_revisions = [
        revision
        for revision in db.scalars(
            select(GuideRevision)
            .where(_mentions(GuideRevision.document, media_id))
            .order_by(GuideRevision.owner_id, GuideRevision.version)
        )
        if media_id in published.guide_media_ids(revision.document)
    ]
    page_revisions = [
        revision
        for revision in db.scalars(
            select(PageRevision)
            .where(_mentions(PageRevision.document, media_id))
            .order_by(PageRevision.owner_id, PageRevision.version)
        )
        if media_id in published.page_media_ids(revision.document)
    ]
    return MediaUses(list(guides), list(pages), guide_revisions, page_revisions)


def still_used_message(uses: MediaUses) -> str:
    places = uses.described()
    named = "; ".join(places[:MAX_USES_NAMED])
    more = f"; and {len(places) - MAX_USES_NAMED} more" if len(places) > MAX_USES_NAMED else ""
    return f"That file is still used, so it was not deleted. It appears in: {named}{more}."


# ---------------------------------------------------------------- removing one


def _touch_keeping_state(entity: Any, actor: User) -> None:
    """Move the concurrency token without inventing unpublished changes.

    Taking a picture out of a working copy has to move ``updated_at``: an
    editor that has the guide open still holds the picture, and its next
    autosave must be refused as stale rather than fail on a file that no longer
    exists. The same picture is being taken out of the snapshot, so a guide
    that matched its snapshot before still does.
    """
    was_settled = entity.snapshot_updated_at == entity.updated_at
    entity.updated_at = next_updated_at(entity.updated_at)
    entity.last_edited_by_id = actor.id
    if was_settled:
        entity.snapshot_updated_at = entity.updated_at


def strip_everywhere(db: DbSession, media_id: str, uses: MediaUses, actor: User, settings: Settings) -> None:
    """Take an upload out of every working copy and every stored snapshot.

    This rewrites published history, which nothing else in Reticle does, and it
    is why forcing a delete is an administrator's action and is recorded: the
    tool exists for the photograph that must not exist — a badge, a patient
    name on a screen — and for that case a version that silently lost one
    picture is the right outcome.
    """
    db.execute(delete(StepMedia).where(StepMedia.media_id == media_id))
    for guide in uses.guides:
        _touch_keeping_state(guide, actor)

    for page in uses.pages:
        if page.hero_media_id == media_id:
            page.hero_media_id = None
            page.hero_alt = ""
        page.body = published.strip_media_from_body(page.body, media_id)
        _touch_keeping_state(page, actor)
    db.execute(delete(PageMedia).where(PageMedia.media_id == media_id))

    for revision in uses.guide_revisions:
        revision.document = published.strip_media_from_guide(revision.document, media_id)
        pdf.forget(settings.pdf_cache_root, revision.owner_id)
    for revision in uses.page_revisions:
        revision.document = published.strip_media_from_page(revision.document, media_id)
    db.flush()

    # What readers are served is one of those snapshots; re-index the ones that are.
    served_guides = {row.revision_id: row.owner_id for row in db.scalars(select(PublishedGuide))}
    for revision in uses.guide_revisions:
        if revision.id in served_guides:
            published.project_guide(db, db.get(Guide, revision.owner_id), revision)
    served_pages = {row.revision_id: row.owner_id for row in db.scalars(select(PublishedPage))}
    for revision in uses.page_revisions:
        if revision.id in served_pages:
            published.project_page(db, db.get(Page, revision.owner_id), revision)
    db.execute(delete(PublishedGuideMedia).where(PublishedGuideMedia.media_id == media_id))
    db.execute(delete(PublishedPageMedia).where(PublishedPageMedia.media_id == media_id))
    db.flush()


def remove_files(media_root: Path, storage_path: str) -> None:
    """Delete an upload's files: the original and its display copy.

    Called after the row is gone and committed. A file that outlives its row is
    an orphan the maintenance command sweeps up; a row that outlives its file
    is a broken picture in somebody's guide.
    """
    for path in images.stored_files(media_root, storage_path):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not delete %s; the maintenance command will retry.", path, exc_info=True)


# -------------------------------------------------------------------- the store


def store_size(db: DbSession) -> int:
    """Bytes of stored originals, from the database rather than from the disk.

    Summing a column is one indexed read however many files there are; walking
    the directory on every upload would make each upload slower than the last.
    """
    return int(db.scalar(select(func.coalesce(func.sum(Media.byte_size), 0))) or 0)


def assert_room_for(db: DbSession, settings: Settings, incoming_bytes: int) -> None:
    """Refuse an upload that would take the store past its configured ceiling."""
    limit = settings.max_media_store_bytes
    if not limit:
        return
    if store_size(db) + incoming_bytes > limit:
        raise errors.payload_too_large(
            "The media store is full, so this file was not uploaded. Ask an administrator to free "
            "space (unused uploads can be purged) or to raise the limit."
        )


def unused_media(db: DbSession, older_than: datetime) -> list[Media]:
    """Uploads that nothing shows and no snapshot ever showed, from before a date.

    The age matters as much as the emptiness. An upload is unreferenced for the
    seconds between arriving and the autosave that places it in a step, and for
    as long as an author leaves a tab open before saving; "older than a week"
    is what tells an abandoned file from one in the middle of being used.
    """
    candidates = {
        media.id: media
        for media in db.scalars(
            select(Media).where(
                Media.created_at < older_than,
                Media.id.not_in(select(StepMedia.media_id)),
                Media.id.not_in(select(PageMedia.media_id)),
                Media.id.not_in(select(Page.hero_media_id).where(Page.hero_media_id.is_not(None))),
            )
        )
    }
    if not candidates:
        return []
    for model in (GuideRevision, PageRevision):
        for text in db.scalars(select(type_coerce(model.document, Text))).yield_per(50):
            for mentioned in IDENTIFIER.findall(text or ""):
                candidates.pop(mentioned, None)
    # A page body is free text and its references are recorded on save; read
    # the bodies themselves as well, so that a body written by anything that
    # skipped that step still protects the files it points at.
    for body in db.scalars(select(Page.body)).yield_per(50):
        for mentioned in IDENTIFIER.findall(body or ""):
            candidates.pop(mentioned, None)
    return sorted(candidates.values(), key=lambda media: media.id)
