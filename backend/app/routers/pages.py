"""Wiki pages: the other half of what ZMB actually uses.

A census of the live site found that navigation does not run on the category
tree at all. Category pages are wiki pages whose body embeds tag-filtered guide
lists, and guides sit in deliberately hidden holding categories and surface
through tags. So a landing page here is a ``Page`` with ``is_landing`` set
rather than a body column on ``Category``: pages, category landings, drafts,
publishing and version history stay one mechanism instead of two.

Visibility is the same ``WHERE`` clause as guides use, for the same reason — a
draft that reaches the serialiser has already been loaded.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request, Response, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session as DbSession

from .. import audit, errors
from ..auth import AdminUser, AnyUser, AuthorUser, DbDep, client_address
from ..db import utcnow
from ..documents import apply_page_document, next_updated_at, record_contribution
from ..models import Category, Page, PageRevision, User
from ..schemas import (
    PageCreateIn,
    PageDocumentIn,
    PageOut,
    PageSummaryOut,
    RevisionSummaryOut,
    page_document,
    page_out,
    page_summary_out,
    user_ref_out,
)
from ..slugs import unique_slug

router = APIRouter(prefix="/api/pages", tags=["pages"])

READER_STATUS = "published"


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def slug_taken(db: DbSession, slug: str) -> bool:
    return db.scalar(select(func.count()).select_from(Page).where(Page.slug == slug)) > 0


def _load_for(db: DbSession, user: User, key: str) -> Page:
    page = db.scalars(select(Page).where(or_(Page.id == key, Page.slug == key))).one_or_none()
    if page is None:
        raise errors.not_found("That page does not exist.")
    if user.role == "viewer" and page.status != READER_STATUS:
        raise errors.not_found("That page does not exist.")
    return page


def _load_editable(db: DbSession, page_id: str) -> Page:
    page = db.get(Page, page_id)
    if page is None:
        raise errors.not_found("That page does not exist.")
    return page


def count_reading(db: DbSession, page: Page) -> None:
    """See ``guides._count_reading``: a bare UPDATE, and never on a draft."""
    if page.status != READER_STATUS:
        return
    db.execute(update(Page).where(Page.id == page.id).values(view_count=Page.view_count + 1))
    db.commit()
    db.refresh(page)


@router.get("", response_model=list[PageSummaryOut])
def list_pages(
    db: DbDep,
    user: AnyUser,
    category_id: str | None = Query(default=None, alias="categoryId"),
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
) -> list[PageSummaryOut]:
    statement = select(Page)

    if user.role == "viewer":
        statement = statement.where(Page.status == READER_STATUS)
    if status_filter is not None:
        statement = statement.where(Page.status == status_filter)
    elif user.role != "viewer":
        statement = statement.where(Page.status != "archived")

    if category_id is not None:
        statement = statement.where(Page.category_id == category_id)
    if q:
        pattern = f"%{_escape_like(q.strip())}%"
        statement = statement.where(
            or_(
                Page.title.ilike(pattern, escape="\\"),
                Page.summary.ilike(pattern, escape="\\"),
                Page.body.ilike(pattern, escape="\\"),
            )
        )

    statement = statement.order_by(Page.updated_at.desc(), Page.id.desc())
    return [page_summary_out(page) for page in db.scalars(statement)]


@router.post("", response_model=PageOut, status_code=status.HTTP_201_CREATED)
def create_page(payload: PageCreateIn, request: Request, db: DbDep, user: AuthorUser) -> PageOut:
    title = payload.title.strip()
    if not title:
        raise errors.validation_failed("A page needs a title.")

    category_id: str | None = None
    if payload.category_id is not None:
        if db.get(Category, payload.category_id) is None:
            raise errors.validation_failed("That category does not exist.")
        category_id = payload.category_id

    if payload.is_landing:
        if category_id is None:
            raise errors.validation_failed("A landing page has to belong to a category.")
        existing = db.scalars(
            select(Page).where(Page.category_id == category_id, Page.is_landing.is_(True))
        ).first()
        if existing is not None:
            raise errors.conflict("That category already has a landing page.")

    page = Page(
        slug=unique_slug(title, lambda candidate: slug_taken(db, candidate), fallback="page"),
        title=title,
        category_id=category_id,
        is_landing=payload.is_landing,
        author_id=user.id,
        last_edited_by_id=user.id,
    )
    db.add(page)
    db.flush()
    record_contribution(db, page, user)
    audit.record(
        db,
        action="page.create",
        entity_type="page",
        entity_id=page.id,
        actor=user,
        ip_address=client_address(request),
        detail={"title": page.title, "slug": page.slug, "isLanding": page.is_landing},
    )
    db.commit()
    return page_out(page)


@router.get("/{key}", response_model=PageOut)
def read_page(key: str, db: DbDep, user: AnyUser) -> PageOut:
    page = _load_for(db, user, key)
    count_reading(db, page)
    return page_out(page)


@router.put("/{page_id}", response_model=PageOut)
def save_page(
    page_id: str,
    payload: PageDocumentIn,
    request: Request,
    db: DbDep,
    user: AuthorUser,
) -> PageOut:
    page = _load_editable(db, page_id)
    apply_page_document(db, page, payload, user)
    audit.record(
        db,
        action="page.update",
        entity_type="page",
        entity_id=page.id,
        actor=user,
        ip_address=client_address(request),
        detail={"bodyChars": len(payload.body)},
    )
    db.commit()
    return page_out(page)


@router.post("/{page_id}/publish", response_model=PageOut)
def publish_page(page_id: str, request: Request, db: DbDep, user: AuthorUser) -> PageOut:
    page = _load_editable(db, page_id)
    if page.status == "archived":
        raise errors.conflict("Restore this page before publishing it.")

    now = utcnow()
    page.status = "published"
    page.version += 1
    page.published_at = now
    page.updated_at = next_updated_at(page.updated_at)
    page.last_edited_by_id = user.id
    record_contribution(db, page, user)
    db.flush()

    db.add(
        PageRevision(
            page_id=page.id,
            version=page.version,
            published_at=now,
            published_by_id=user.id,
            document=page_document(page),
        )
    )
    audit.record(
        db,
        action="page.publish",
        entity_type="page",
        entity_id=page.id,
        actor=user,
        ip_address=client_address(request),
        detail={"version": page.version},
    )
    db.commit()
    return page_out(page)


@router.post("/{page_id}/unpublish", response_model=PageOut)
def unpublish_page(page_id: str, request: Request, db: DbDep, user: AuthorUser) -> PageOut:
    page = _load_editable(db, page_id)
    if page.status != READER_STATUS:
        raise errors.conflict("Only a published page can be unpublished.")

    page.status = "draft"
    page.updated_at = next_updated_at(page.updated_at)
    page.last_edited_by_id = user.id
    audit.record(
        db,
        action="page.unpublish",
        entity_type="page",
        entity_id=page.id,
        actor=user,
        ip_address=client_address(request),
        detail={"version": page.version},
    )
    db.commit()
    return page_out(page)


@router.delete("/{page_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def archive_page(page_id: str, request: Request, db: DbDep, user: AdminUser) -> Response:
    page = _load_editable(db, page_id)
    if page.status != "archived":
        page.status = "archived"
        page.updated_at = next_updated_at(page.updated_at)
        page.last_edited_by_id = user.id
    audit.record(
        db,
        action="page.archive",
        entity_type="page",
        entity_id=page.id,
        actor=user,
        ip_address=client_address(request),
        detail={"title": page.title},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{page_id}/revisions", response_model=list[RevisionSummaryOut])
def list_revisions(page_id: str, db: DbDep, user: AuthorUser) -> list[RevisionSummaryOut]:
    page = _load_editable(db, page_id)
    return [
        RevisionSummaryOut(
            version=revision.version,
            published_at=revision.published_at,
            published_by=user_ref_out(revision.published_by),
        )
        for revision in page.revisions
    ]


@router.get("/{page_id}/revisions/{version}", response_model=None)
def read_revision(page_id: str, version: int, db: DbDep, user: AuthorUser) -> dict[str, Any]:
    _load_editable(db, page_id)
    revision = db.scalars(
        select(PageRevision).where(PageRevision.page_id == page_id, PageRevision.version == version)
    ).one_or_none()
    if revision is None:
        raise errors.not_found("That revision does not exist.")
    return revision.document
