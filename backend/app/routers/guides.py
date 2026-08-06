"""Guides: listing, the whole-document save, publishing and archiving.

Reader visibility is a ``WHERE`` clause, never a filter applied while
serialising. A draft that reaches the serialiser has already been loaded, and
one forgotten branch there is the difference between a half-written safety
procedure staying internal and it being served to the whole institute.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request, Response, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session as DbSession

from .. import audit, errors
from ..auth import AdminUser, AuthorUser, DbDep, MaybeUser, client_address
from ..db import escape_like, utcnow
from ..documents import apply_document, apply_tags, next_updated_at, record_contribution
from ..models import (
    PUBLISHED,
    Bullet,
    Category,
    Guide,
    GuideRevision,
    GuideTag,
    Media,
    Step,
    StepMedia,
    Tag,
    User,
)
from ..schemas import (
    ContentStatus,
    GuideCreateIn,
    GuideDocumentIn,
    GuideOut,
    GuideSummaryOut,
    RevisionSummaryOut,
    TagsIn,
    guide_document,
    guide_out,
    guide_summary_out,
    user_ref_out,
)
from ..slugs import unique_slug
from ..visibility import readable_guides, sees_unpublished

router = APIRouter(prefix="/api/guides", tags=["guides"])

MAX_TAG_FILTER_TERMS = 20


def parse_tag_filter(raw: str | None) -> list[str]:
    """Split the comma-separated ``?tags=`` filter into slugs.

    Bounded because the filter becomes one correlated subquery per term: a
    caller passing a thousand tags would otherwise hand themselves a
    thousand-way join, on a query anybody can make without signing in.
    """
    if not raw:
        return []
    terms: list[str] = []
    for part in raw.split(","):
        slug = part.strip().lower()
        if slug and slug not in terms:
            terms.append(slug)
    if len(terms) > MAX_TAG_FILTER_TERMS:
        raise errors.validation_failed(f"Filter by at most {MAX_TAG_FILTER_TERMS} tags at once.")
    return terms


def apply_tag_filter(statement, tags: list[str]):
    """Require *all* of the tags, not any of them.

    A wiki page that asks for ``stellaris, confocal`` means the guides that are
    both, which is how one heading on a category page stays specific. ``any``
    would turn every embed on ZMB's busiest page into an undifferentiated dump.
    """
    for slug in tags:
        member = (
            select(GuideTag.id)
            .join(Tag, Tag.id == GuideTag.tag_id)
            .where(GuideTag.guide_id == Guide.id, Tag.slug == slug)
            .correlate(Guide)
            .exists()
        )
        statement = statement.where(member)
    return statement


def thumbnail_subquery():
    """The first image of the first step that has one.

    Browsing is meant to be visual — somebody heading for the confocal
    recognises the instrument before they finish reading its name — so a guide
    card needs a picture, and the honest one is the picture the guide opens
    with. Computed as a correlated subquery rather than by loading each guide's
    steps, because a listing of the whole corpus would otherwise pull every step
    and every media row in the institute to show forty cards.
    """
    return (
        select(StepMedia.media_id)
        .join(Step, Step.id == StepMedia.step_id)
        .join(Media, Media.id == StepMedia.media_id)
        .where(Step.guide_id == Guide.id, Media.kind == "image")
        .order_by(Step.order_index, StepMedia.order_index)
        .limit(1)
        .correlate(Guide)
        .scalar_subquery()
    )


def _slug_taken(db: DbSession, slug: str) -> bool:
    return db.scalar(select(func.count()).select_from(Guide).where(Guide.slug == slug)) > 0


def _load_for(db: DbSession, user: User, key: str) -> Guide:
    """Resolve by identifier or slug, hiding anything the reader may not see.

    Both rules are in the ``WHERE`` clause rather than checked on the loaded
    row, so the only outcome a viewer can distinguish is "no such guide".

    That 404 is deliberate, for a draft and for a staff guide alike: telling
    somebody the guide exists but is off-limits leaks the editorial pipeline for
    no benefit, and a guide's address is its title, so confirming one discloses
    that the facility has a procedure for whatever was guessed at.
    """
    statement = select(Guide).where(or_(Guide.id == key, Guide.slug == key))
    if not sees_unpublished(user):
        statement = statement.where(Guide.status == PUBLISHED)
    guide = db.scalars(readable_guides(statement, user)).one_or_none()
    if guide is None:
        raise errors.not_found("That guide does not exist.")
    return guide


def _load_editable(db: DbSession, guide_id: str) -> Guide:
    """Load a guide for writing, holding its row until the transaction ends.

    The lock is what makes the staleness check mean anything. Without it two
    authors saving the same guide at the same moment both read the row, both
    compare their timestamp against the same value, both pass, and both commit —
    PostgreSQL's default isolation permits exactly that, and the later write
    simply erases the earlier one. Both authors are told the save succeeded.

    Taking the row lock makes the second transaction wait for the first, and the
    row it then reads is the one the first committed, so its ``updated_at`` is
    newer than what that author last saw and the conflict is raised. This is a
    real race that a sequential test cannot see: every concurrency test in the
    suite had the colleague's save complete before the author's began, which
    passes against no locking at all.
    """
    guide = db.get(Guide, guide_id, with_for_update=True)
    if guide is None:
        raise errors.not_found("That guide does not exist.")
    return guide


@router.get("", response_model=list[GuideSummaryOut])
def list_guides(
    db: DbDep,
    user: MaybeUser,
    category_id: str | None = Query(default=None, alias="categoryId"),
    # Typed, not a bare string. `?status=` and `?status=publshed` used to filter
    # on a value nothing could equal and return an empty array — a caller with a
    # typo was told the library is empty rather than that the word is wrong,
    # which is how a migration script decided nothing had been imported yet and
    # imported everything a second time.
    status_filter: ContentStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
    author_id: str | None = Query(default=None, alias="authorId"),
    tags: str | None = Query(default=None, max_length=800),
    quick_link: bool | None = Query(default=None, alias="quickLink"),
) -> list[GuideSummaryOut]:
    step_count = (
        select(func.count(Step.id))
        .where(Step.guide_id == Guide.id)
        .correlate(Guide)
        .scalar_subquery()
    )
    statement = select(Guide, step_count.label("step_count"), thumbnail_subquery().label("thumb"))
    # Before the category, tag, author and text filters, all of which narrow
    # this listing further: whichever of them a caller combines, they are
    # choosing among the guides this clause already allowed.
    statement = readable_guides(statement, user)

    if not sees_unpublished(user):
        statement = statement.where(Guide.status == PUBLISHED)

    if status_filter is not None:
        statement = statement.where(Guide.status == status_filter)
    elif sees_unpublished(user):
        statement = statement.where(Guide.status != "archived")

    if category_id is not None:
        statement = statement.where(Guide.category_id == category_id)
    if author_id is not None:
        statement = statement.where(Guide.author_id == author_id)
    if quick_link is not None:
        statement = statement.where(Guide.is_quick_link.is_(quick_link))
    statement = apply_tag_filter(statement, parse_tag_filter(tags))
    if q:
        pattern = f"%{escape_like(q.strip())}%"
        statement = statement.where(
            or_(Guide.title.ilike(pattern, escape="\\"), Guide.summary.ilike(pattern, escape="\\"))
        )

    statement = statement.order_by(Guide.updated_at.desc(), Guide.id.desc())
    return [
        guide_summary_out(guide, count, thumbnail)
        for guide, count, thumbnail in db.execute(statement)
    ]


@router.post("", response_model=GuideOut, status_code=status.HTTP_201_CREATED)
def create_guide(payload: GuideCreateIn, request: Request, db: DbDep, user: AuthorUser) -> GuideOut:
    title = payload.title.strip()
    if not title:
        raise errors.validation_failed("A guide needs a title.")
    if db.get(Category, payload.category_id) is None:
        raise errors.validation_failed("That category does not exist.")

    guide = Guide(
        slug=unique_slug(title, lambda candidate: _slug_taken(db, candidate), fallback="guide"),
        title=title,
        category_id=payload.category_id,
        author_id=user.id,
        last_edited_by_id=user.id,
    )
    db.add(guide)
    db.flush()

    # A new guide starts with one empty step holding one empty bullet — the same
    # shape the editor's own "add step" produces. The button that lands the
    # author here says "create and start writing", and an editor whose only
    # controls are "add step" and then "add bullet" makes them perform two
    # pieces of ceremony before the first word of every guide they ever write.
    first_step = Step(guide_id=guide.id, order_index=0, title="")
    db.add(first_step)
    db.flush()
    db.add(Bullet(step_id=first_step.id, order_index=0, text="", color="black", level=0))

    record_contribution(db, guide, user)
    audit.record(
        db,
        action="guide.create",
        entity_type="guide",
        entity_id=guide.id,
        actor=user,
        ip_address=client_address(request),
        detail={"title": guide.title, "slug": guide.slug},
    )
    db.commit()
    return guide_out(guide)


@router.get("/{key}", response_model=GuideOut)
def read_guide(key: str, db: DbDep, user: MaybeUser) -> GuideOut:
    guide = _load_for(db, user, key)
    count_reading(db, guide)
    return guide_out(guide)


def count_reading(db: DbSession, guide: Guide) -> None:
    """Count somebody opening a published guide.

    Only published guides count: an author refreshing their own draft forty
    times while writing it would otherwise make the busiest guide at ZMB the one
    nobody has read. The counter is written with a bare ``UPDATE`` rather than by
    mutating the loaded row, so two people opening the same guide at once add two
    rather than one, and so it never touches ``updated_at`` — a read is not an
    edit, and moving the concurrency token would eject every editor who had the
    guide open.
    """
    if guide.status != PUBLISHED:
        return
    db.execute(update(Guide).where(Guide.id == guide.id).values(view_count=Guide.view_count + 1))
    db.commit()
    db.refresh(guide)


@router.put("/{guide_id}", response_model=GuideOut)
def save_guide(
    guide_id: str,
    payload: GuideDocumentIn,
    request: Request,
    db: DbDep,
    user: AuthorUser,
) -> GuideOut:
    guide = _load_editable(db, guide_id)
    apply_document(db, guide, payload, user)
    audit.record(
        db,
        action="guide.update",
        entity_type="guide",
        entity_id=guide.id,
        actor=user,
        ip_address=client_address(request),
        detail={"stepCount": len(payload.steps)},
    )
    db.commit()
    return guide_out(guide)


@router.put("/{guide_id}/tags", response_model=GuideOut)
def set_guide_tags(
    guide_id: str,
    payload: TagsIn,
    request: Request,
    db: DbDep,
    user: AuthorUser,
) -> GuideOut:
    """Move a guide between the groups on a section's page.

    Its own route rather than a whole-document save, because the editor holds a
    guide's steps and pictures and a section's page holds neither: making the
    drag round-trip the document would mean fetching it in full to change one
    list, and any bug in that round trip is a bug that eats somebody's work.
    """
    guide = _load_editable(db, guide_id)
    apply_tags(db, guide, payload.tags, payload.updated_at)
    audit.record(
        db,
        action="guide.retag",
        entity_type="guide",
        entity_id=guide.id,
        actor=user,
        ip_address=client_address(request),
        detail={"tags": payload.tags},
    )
    db.commit()
    return guide_out(guide)


@router.post("/{guide_id}/publish", response_model=GuideOut)
def publish_guide(guide_id: str, request: Request, db: DbDep, user: AuthorUser) -> GuideOut:
    guide = _load_editable(db, guide_id)
    if guide.status == "archived":
        raise errors.conflict("Restore this guide before publishing it.")

    now = utcnow()
    guide.status = PUBLISHED
    guide.version += 1
    guide.published_at = now
    guide.updated_at = next_updated_at(guide.updated_at)
    guide.last_edited_by_id = user.id
    db.flush()

    db.add(
        GuideRevision(
            guide_id=guide.id,
            version=guide.version,
            published_at=now,
            published_by_id=user.id,
            document=guide_document(guide),
        )
    )
    audit.record(
        db,
        action="guide.publish",
        entity_type="guide",
        entity_id=guide.id,
        actor=user,
        ip_address=client_address(request),
        detail={"version": guide.version},
    )
    db.commit()
    return guide_out(guide)


@router.post("/{guide_id}/unpublish", response_model=GuideOut)
def unpublish_guide(guide_id: str, request: Request, db: DbDep, user: AuthorUser) -> GuideOut:
    guide = _load_editable(db, guide_id)
    if guide.status != PUBLISHED:
        raise errors.conflict("Only a published guide can be unpublished.")

    guide.status = "draft"
    guide.updated_at = next_updated_at(guide.updated_at)
    guide.last_edited_by_id = user.id
    audit.record(
        db,
        action="guide.unpublish",
        entity_type="guide",
        entity_id=guide.id,
        actor=user,
        ip_address=client_address(request),
        detail={"version": guide.version},
    )
    db.commit()
    return guide_out(guide)


@router.delete("/{guide_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def archive_guide(guide_id: str, request: Request, db: DbDep, user: AdminUser) -> Response:
    guide = _load_editable(db, guide_id)
    if guide.status != "archived":
        guide.status = "archived"
        guide.updated_at = next_updated_at(guide.updated_at)
        guide.last_edited_by_id = user.id
    audit.record(
        db,
        action="guide.archive",
        entity_type="guide",
        entity_id=guide.id,
        actor=user,
        ip_address=client_address(request),
        detail={"title": guide.title},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{guide_id}/revisions", response_model=list[RevisionSummaryOut])
def list_revisions(guide_id: str, db: DbDep, user: AuthorUser) -> list[RevisionSummaryOut]:
    guide = _load_editable(db, guide_id)
    return [
        RevisionSummaryOut(
            version=revision.version,
            published_at=revision.published_at,
            published_by=user_ref_out(revision.published_by),
        )
        for revision in guide.revisions
    ]


@router.get("/{guide_id}/revisions/{version}", response_model=None)
def read_revision(guide_id: str, version: int, db: DbDep, user: AuthorUser) -> dict[str, Any]:
    _load_editable(db, guide_id)
    revision = db.scalars(
        select(GuideRevision).where(
            GuideRevision.guide_id == guide_id, GuideRevision.version == version
        )
    ).one_or_none()
    if revision is None:
        raise errors.not_found("That revision does not exist.")
    return revision.document
