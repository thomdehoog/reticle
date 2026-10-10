"""What readers are served: the published snapshot, and the index over it.

A guide or a page exists twice. The rows the editor autosaves into are the
**working copy**; the document written at the last publish is the **snapshot**,
and the snapshot is what a reader gets — by identifier, by slug, in a listing,
in a search result, in the PDF and in which images they may fetch — until the
next publish replaces it. "Editing a published guide never breaks the version
people are reading" is a promise about this module.

The snapshot is a JSON document, which is the right shape for serving one guide
and the wrong shape for asking "which published guides carry this tag". So each
publish also writes a small relational projection of the snapshot — its listing
columns, its tags, its search text, the uploads it shows — in the same
transaction, and every reader-facing query is a ``WHERE`` clause over that. A
landing page that embeds eighty guides opens no snapshot at all.

Nothing here decides *who* is a reader. ``content`` does that, and asks this
module for the published side when the answer is "a viewer", or an author who
wants to see what a viewer sees.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session as DbSession

from . import documents
from . import pages as page_documents
from .models import (
    PUBLISHED,
    Guide,
    GuideRevision,
    Media,
    Page,
    PageRevision,
    PublishedGuide,
    PublishedGuideMedia,
    PublishedGuideTag,
    PublishedPage,
    PublishedPageMedia,
    Tag,
)
from .schemas import (
    GuideDocumentIn,
    GuideOut,
    GuideSummaryOut,
    PageDocumentIn,
    PageOut,
    PageSummaryOut,
    media_display_url,
    user_ref_out,
)

# ------------------------------------------------------------- reading a snapshot


def _media_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """A media entry as the current contract spells it.

    Snapshots are kept as they were written, and the ones written before the
    display copy existed have no ``displayUrl``. It is derived, so it is filled
    in on the way out rather than by rewriting history.
    """
    if "displayUrl" in entry:
        return entry
    return {**entry, "displayUrl": media_display_url(str(entry.get("id", "")), str(entry.get("kind", "image")))}


def _overlay(data: dict[str, Any], entity: Any | None, reveal_changes: bool) -> None:
    """Lay the few facts that are not part of a snapshot over one.

    The slug, the status and the view count belong to the item, not to a
    version of it: a snapshot taken when the guide had been read ten times
    should not report ten for ever. Whether newer, unpublished work exists is
    said only to those who could open it; to a viewer it would be a disclosure.
    """
    data["hasUnpublishedChanges"] = False
    if entity is None:
        return
    data["slug"] = entity.slug
    data["status"] = entity.status
    data["viewCount"] = entity.view_count
    data["hasUnpublishedChanges"] = bool(reveal_changes and entity.has_unpublished_changes)


def guide_from_snapshot(document: dict[str, Any], guide: Guide | None = None, reveal_changes: bool = False) -> GuideOut:
    data = dict(document)
    data["steps"] = [
        {**step, "media": [_media_entry(entry) for entry in step.get("media") or []]}
        for step in document.get("steps") or []
    ]
    _overlay(data, guide, reveal_changes)
    return GuideOut.model_validate(data)


def page_from_snapshot(document: dict[str, Any], page: Page | None = None, reveal_changes: bool = False) -> PageOut:
    data = dict(document)
    # Snapshots written before the hero had a description do not carry one.
    data.setdefault("heroAlt", "")
    _overlay(data, page, reveal_changes)
    return PageOut.model_validate(data)


def guide_summary(guide: Guide, projection: PublishedGuide) -> GuideSummaryOut:
    """A guide as a reader's listing shows it: every content field from the snapshot."""
    return GuideSummaryOut(
        id=guide.id,
        slug=guide.slug,
        title=projection.title,
        summary=projection.summary,
        category_id=projection.category_id,
        tags=projection.tag_slugs,
        difficulty=projection.difficulty,
        time_required_min_minutes=projection.time_required_min_minutes,
        time_required_max_minutes=projection.time_required_max_minutes,
        status=guide.status,
        step_count=projection.step_count,
        author=user_ref_out(guide.author),
        view_count=guide.view_count,
        updated_at=guide.snapshot_updated_at or guide.updated_at,
        published_at=guide.published_at,
        has_unpublished_changes=False,
    )


def page_summary(page: Page, projection: PublishedPage) -> PageSummaryOut:
    return PageSummaryOut(
        id=page.id,
        slug=page.slug,
        title=projection.title,
        summary=projection.summary,
        category_id=projection.category_id,
        is_landing=projection.is_landing,
        status=page.status,
        updated_at=page.snapshot_updated_at or page.updated_at,
        published_at=page.published_at,
        has_unpublished_changes=False,
    )


# -------------------------------------------------------- comparing with a snapshot

_ANNOTATION_FIELDS = ("shape", "color", "x", "y", "width", "height")
_BULLET_FIELDS = ("text", "color", "icon", "level")
_GUIDE_FIELDS = (
    "title",
    "summary",
    "categoryId",
    "difficulty",
    "timeRequiredMinMinutes",
    "timeRequiredMaxMinutes",
    "introduction",
    "conclusion",
)
_PAGE_FIELDS = ("title", "summary", "categoryId", "isLanding", "body", "heroMediaId")


def guide_fingerprint(document: dict[str, Any]) -> dict[str, Any]:
    """What a reader could tell apart, and nothing else.

    Two documents with the same fingerprint read identically, so a working copy
    whose fingerprint equals its snapshot's has no unpublished changes — which
    is how typing a word and deleting it again does not leave a guide flagged
    for ever. Identifiers are left out for that reason (a step deleted and
    retyped is the same step to a reader), and so is everything the server
    owns: timestamps, counters, who edited last.
    """
    return {
        **{field: document.get(field) for field in _GUIDE_FIELDS},
        "tags": sorted(document.get("tags") or []),
        "steps": [
            {
                "title": step.get("title", ""),
                "bullets": [
                    {field: bullet.get(field) for field in _BULLET_FIELDS} for bullet in step.get("bullets") or []
                ],
                "media": [
                    {
                        "id": entry.get("id"),
                        "alt": entry.get("alt", ""),
                        "annotations": [
                            {field: annotation.get(field) for field in _ANNOTATION_FIELDS}
                            for annotation in entry.get("annotations") or []
                        ],
                    }
                    for entry in step.get("media") or []
                ],
            }
            for step in document.get("steps") or []
        ],
    }


def page_fingerprint(document: dict[str, Any]) -> dict[str, Any]:
    return {**{field: document.get(field) for field in _PAGE_FIELDS}, "heroAlt": document.get("heroAlt") or ""}


# ------------------------------------------------------------ what a snapshot shows


def guide_media_ids(document: dict[str, Any]) -> set[str]:
    return {
        str(entry["id"])
        for step in document.get("steps") or []
        for entry in step.get("media") or []
        if entry.get("id")
    }


def page_media_ids(document: dict[str, Any]) -> set[str]:
    """The hero, and everything the body points at."""
    found = page_documents.referenced_media_ids(str(document.get("body") or ""))
    if document.get("heroMediaId"):
        found.add(str(document["heroMediaId"]))
    return found


def guide_search_text(document: dict[str, Any]) -> str:
    """Step titles and bullet text, one to a line.

    A line each, so that a search term cannot match across the end of one
    bullet and the start of the next and report a phrase nobody wrote.
    """
    lines: list[str] = []
    for step in document.get("steps") or []:
        lines.append(str(step.get("title") or ""))
        lines.extend(str(bullet.get("text") or "") for bullet in step.get("bullets") or [])
    return "\n".join(line for line in lines if line.strip())


def _existing_media(db: DbSession, media_ids: set[str]) -> list[str]:
    """Only uploads that still exist can be linked; a link is a foreign key."""
    if not media_ids:
        return []
    return sorted(db.scalars(select(Media.id).where(Media.id.in_(media_ids))))


# ------------------------------------------------------------ writing the projection


def _replace_links(db: DbSession, model: type, owner_id: str, column: str, values: list[str]) -> None:
    db.execute(delete(model).where(model.owner_id == owner_id))
    if values:
        db.execute(insert(model), [{"owner_id": owner_id, column: value} for value in values])


def project_guide(db: DbSession, guide: Guide, revision: GuideRevision) -> None:
    """Index a guide's snapshot for readers. Runs inside the publishing transaction.

    Everything is read from the snapshot document, not from the working rows,
    even though at this moment the two agree: the same function backs
    ``python -m app.maintenance`` and the tests that check a rebuilt projection
    against a stored one, and there the working copy has long since moved on.
    """
    document = revision.document
    row = db.get(PublishedGuide, guide.id)
    if row is None:
        row = PublishedGuide(owner_id=guide.id)
        db.add(row)
    row.revision_id = revision.id
    row.title = str(document.get("title") or "")
    row.summary = str(document.get("summary") or "")
    row.category_id = document.get("categoryId") or guide.category_id
    row.difficulty = document.get("difficulty") or "moderate"
    row.time_required_min_minutes = document.get("timeRequiredMinMinutes")
    row.time_required_max_minutes = document.get("timeRequiredMaxMinutes")
    row.step_count = len(document.get("steps") or [])
    row.search_text = guide_search_text(document)
    db.flush()

    slugs = sorted(set(document.get("tags") or []))
    tag_ids = sorted(db.scalars(select(Tag.id).where(Tag.slug.in_(slugs)))) if slugs else []
    _replace_links(db, PublishedGuideTag, guide.id, "tag_id", tag_ids)
    _replace_links(db, PublishedGuideMedia, guide.id, "media_id", _existing_media(db, guide_media_ids(document)))
    db.expire(row, ["tags"])


def project_page(db: DbSession, page: Page, revision: PageRevision) -> None:
    document = revision.document
    row = db.get(PublishedPage, page.id)
    if row is None:
        row = PublishedPage(owner_id=page.id)
        db.add(row)
    row.revision_id = revision.id
    row.title = str(document.get("title") or "")
    row.summary = str(document.get("summary") or "")
    row.category_id = document.get("categoryId")
    row.is_landing = bool(document.get("isLanding"))
    row.body = str(document.get("body") or "")
    db.flush()
    _replace_links(db, PublishedPageMedia, page.id, "media_id", _existing_media(db, page_media_ids(document)))


def _clear(db: DbSession, model: type, link_models: tuple[type, ...], owner_id: str) -> None:
    for link_model in link_models:
        db.execute(delete(link_model).where(link_model.owner_id == owner_id))
    row = db.get(model, owner_id)
    if row is not None:
        db.delete(row)
        db.flush()


def clear_guide(db: DbSession, guide_id: str) -> None:
    """Withdraw a guide from readers' listings, searches and image access."""
    _clear(db, PublishedGuide, (PublishedGuideTag, PublishedGuideMedia), guide_id)


def clear_page(db: DbSession, page_id: str) -> None:
    _clear(db, PublishedPage, (PublishedPageMedia,), page_id)


def withdraw_stale(db: DbSession) -> int:
    """Remove projections of anything that is no longer published; return how many.

    Unpublishing and archiving withdraw their own. This is for a writer that
    changes a status without going through ``content`` — the importer does,
    when a re-import turns a published guide back into a draft. Readers are
    already unaffected, because every reader-facing query tests the status as
    well; what a leftover row would still do is hold a foreign key on a
    category or an upload that somebody is trying to delete.
    """
    removed = 0
    for model, owner, clear in ((PublishedGuide, Guide, clear_guide), (PublishedPage, Page, clear_page)):
        stale = db.scalars(
            select(model.owner_id).join(owner, owner.id == model.owner_id).where(owner.status != PUBLISHED)
        ).all()
        for owner_id in stale:
            clear(db, owner_id)
        removed += len(stale)
    return removed


# ------------------------------------------------- putting a snapshot back to work


def restore_guide(db: DbSession, guide: Guide, document: dict[str, Any]) -> None:
    """Make the working copy read as the snapshot does: "discard changes".

    The snapshot goes back in through ``documents.apply_document``, the same
    door every save uses, so a restored guide is held to the same rules as a
    typed one. The existing steps are removed first rather than reconciled: the
    snapshot's steps keep their identifiers, and a bullet that the abandoned
    edit had moved to another step would otherwise be refused as belonging to
    something else.
    """
    payload = GuideDocumentIn.model_validate({**document, "expectedUpdatedAt": guide.updated_at})
    guide.steps.clear()
    db.flush()
    documents.apply_document(db, guide, payload)


def restore_page(db: DbSession, page: Page, document: dict[str, Any]) -> None:
    payload = PageDocumentIn.model_validate({**document, "expectedUpdatedAt": page.updated_at})
    page_documents.apply_document(db, page, payload)


# --------------------------------------------------- removing an upload for good


def strip_media_from_guide(document: dict[str, Any], media_id: str) -> dict[str, Any]:
    """The snapshot without one upload."""
    return {
        **document,
        "steps": [
            {**step, "media": [entry for entry in step.get("media") or [] if entry.get("id") != media_id]}
            for step in document.get("steps") or []
        ],
    }


def strip_media_from_body(body: str, media_id: str) -> str:
    """Take an image out of a Markdown body.

    ``![alt](/api/media/<id>)`` is removed whole, with any title or size query
    it carried. Any other mention of the address — an ordinary link, a
    reference definition — has only the address blanked, so the sentence around
    it survives and nothing in the text still names the file.
    """
    address = rf"/api/media/{re.escape(media_id)}(?![0-9A-Za-z])"
    without_images = re.sub(rf"!\[[^\]\n]*\]\(\s*{address}[^)\n]*\)", "", body)
    return re.sub(rf"{address}(\?[^\s)\"'<>]*)?", "", without_images)


def strip_media_from_page(document: dict[str, Any], media_id: str) -> dict[str, Any]:
    stripped = {**document, "body": strip_media_from_body(str(document.get("body") or ""), media_id)}
    if document.get("heroMediaId") == media_id:
        stripped["heroMediaId"] = None
        stripped["heroAlt"] = ""
    return stripped
