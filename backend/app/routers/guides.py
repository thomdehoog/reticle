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
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession

from .. import audit, errors
from ..auth import AdminUser, AnyUser, AuthorUser, DbDep, client_address
from ..db import utcnow
from ..documents import apply_document, next_updated_at
from ..models import Category, Guide, GuideRevision, Step, User
from ..schemas import (
    GuideCreateIn,
    GuideDocumentIn,
    GuideOut,
    GuideSummaryOut,
    RevisionSummaryOut,
    guide_document,
    guide_out,
    guide_summary_out,
    user_ref_out,
)
from ..slugs import unique_slug

router = APIRouter(prefix="/api/guides", tags=["guides"])

READER_STATUS = "published"


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _slug_taken(db: DbSession, slug: str) -> bool:
    return db.scalar(select(func.count()).select_from(Guide).where(Guide.slug == slug)) > 0


def _load_for(db: DbSession, user: User, key: str) -> Guide:
    """Resolve by identifier or slug, hiding anything the reader may not see.

    A viewer gets 404 rather than 403 for an unpublished guide: telling them the
    guide exists but is off-limits leaks the editorial pipeline for no benefit.
    """
    guide = db.scalars(select(Guide).where(or_(Guide.id == key, Guide.slug == key))).one_or_none()
    if guide is None:
        raise errors.not_found("That guide does not exist.")
    if user.role == "viewer" and guide.status != READER_STATUS:
        raise errors.not_found("That guide does not exist.")
    return guide


def _load_editable(db: DbSession, guide_id: str) -> Guide:
    guide = db.get(Guide, guide_id)
    if guide is None:
        raise errors.not_found("That guide does not exist.")
    return guide


@router.get("", response_model=list[GuideSummaryOut])
def list_guides(
    db: DbDep,
    user: AnyUser,
    category_id: str | None = Query(default=None, alias="categoryId"),
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
    author_id: str | None = Query(default=None, alias="authorId"),
) -> list[GuideSummaryOut]:
    step_count = (
        select(func.count(Step.id)).where(Step.guide_id == Guide.id).correlate(Guide).scalar_subquery()
    )
    statement = select(Guide, step_count.label("step_count"))

    if user.role == "viewer":
        statement = statement.where(Guide.status == READER_STATUS)

    if status_filter is not None:
        statement = statement.where(Guide.status == status_filter)
    elif user.role != "viewer":
        statement = statement.where(Guide.status != "archived")

    if category_id is not None:
        statement = statement.where(Guide.category_id == category_id)
    if author_id is not None:
        statement = statement.where(Guide.author_id == author_id)
    if q:
        pattern = f"%{_escape_like(q.strip())}%"
        statement = statement.where(
            or_(Guide.title.ilike(pattern, escape="\\"), Guide.summary.ilike(pattern, escape="\\"))
        )

    statement = statement.order_by(Guide.updated_at.desc(), Guide.id.desc())
    return [guide_summary_out(guide, count) for guide, count in db.execute(statement)]


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
def read_guide(key: str, db: DbDep, user: AnyUser) -> GuideOut:
    return guide_out(_load_for(db, user, key))


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


@router.post("/{guide_id}/publish", response_model=GuideOut)
def publish_guide(guide_id: str, request: Request, db: DbDep, user: AuthorUser) -> GuideOut:
    guide = _load_editable(db, guide_id)
    if guide.status == "archived":
        raise errors.conflict("Restore this guide before publishing it.")

    now = utcnow()
    guide.status = "published"
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
    if guide.status != READER_STATUS:
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
        select(GuideRevision).where(GuideRevision.guide_id == guide_id, GuideRevision.version == version)
    ).one_or_none()
    if revision is None:
        raise errors.not_found("That revision does not exist.")
    return revision.document
