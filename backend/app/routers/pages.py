"""Wiki pages.

A page moves through exactly the lifecycle a guide does, so every endpoint below
the save is ``content.lifecycle_routes`` again. The one place a page differs is
that it can be a category's landing content, and a category has room for one.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import joinedload, selectinload

from .. import audit, content, errors
from ..auth import AnyUser, AuthorUser, DbDep, client_address
from ..models import Page, PageContributor, PageRevision
from ..pages import apply_document, assert_publishable, validated_placement
from ..schemas import (
    MAX_SEARCH_TERM_CHARS,
    ContentStatus,
    PageCreateIn,
    PageDocumentIn,
    PageOut,
    PageSummaryOut,
    page_out,
    page_summary_out,
)
from ..slugs import unique_slug

router = APIRouter(prefix="/api/pages", tags=["pages"])


def _detail_options() -> list[Any]:
    return [
        joinedload(Page.author),
        joinedload(Page.last_edited_by),
        selectinload(Page.contributor_links),
        selectinload(Page.media_links),
    ]


PAGES = content.ContentKind(
    name="page",
    model=Page,
    revision_model=PageRevision,
    contributor_model=PageContributor,
    out_model=PageOut,
    serialise=page_out,
    assert_publishable=assert_publishable,
    eager=_detail_options,
)


def _slug_taken(db: DbSession, slug: str) -> bool:
    return db.scalar(select(func.count()).select_from(Page).where(Page.slug == slug)) > 0


LANDING_INDEX = "uq_pages_one_landing_per_category"


@contextmanager
def landing_race_is_a_conflict(db: DbSession) -> Iterator[None]:
    """Turn a lost race for a landing slot into the usual conflict.

    ``validated_placement`` checks before writing so that it can explain itself,
    but two requests can both pass that check. The partial unique index on
    ``pages`` is what actually decides, and its verdict arrives as an integrity
    error on whichever statement loses. Any other integrity error is not ours to
    explain and is left alone.
    """
    try:
        yield
    except IntegrityError as exc:
        detail = str(exc.orig)
        if LANDING_INDEX not in detail and "pages.category_id" not in detail:
            raise
        db.rollback()
        raise errors.conflict(
            "That category already has a landing page. Edit that one, or archive it first."
        ) from exc


@router.get("", response_model=list[PageSummaryOut])
def list_pages(
    db: DbDep,
    user: AnyUser,
    category_id: str | None = Query(default=None, alias="categoryId", max_length=40),
    status_filter: ContentStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=MAX_SEARCH_TERM_CHARS),
) -> list[PageSummaryOut]:
    statement = select(Page).where(content.visible_to(Page, user))

    if status_filter is not None:
        statement = statement.where(Page.status == status_filter)
    if category_id is not None:
        statement = statement.where(Page.category_id == category_id)

    term = (q or "").strip()
    if term:
        statement = statement.where(or_(content.contains(Page.title, term), content.contains(Page.summary, term)))

    statement = statement.order_by(func.lower(Page.title), Page.id)
    return [page_summary_out(page) for page in db.scalars(statement)]


@router.post("", response_model=PageOut, status_code=status.HTTP_201_CREATED)
def create_page(payload: PageCreateIn, request: Request, db: DbDep, user: AuthorUser) -> PageOut:
    title = payload.title.strip()
    if not title:
        raise errors.validation_failed("A page needs a title.")
    validated_placement(db, payload.category_id, payload.is_landing, None)

    page = Page(
        slug=unique_slug(title, lambda candidate: _slug_taken(db, candidate), fallback="page"),
        title=title,
        category_id=payload.category_id,
        is_landing=payload.is_landing,
        author_id=user.id,
        last_edited_by_id=user.id,
    )
    content.add_contributor(db, PAGES, page, user)
    db.add(page)
    with landing_race_is_a_conflict(db):
        db.flush()
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
    return page_out(content.load_visible(db, PAGES, user, key))


@router.put("/{page_id}", response_model=PageOut)
def save_page(
    page_id: str,
    payload: PageDocumentIn,
    request: Request,
    db: DbDep,
    user: AuthorUser,
) -> PageOut:
    page = content.load_editable(db, PAGES, page_id)
    content.assert_not_stale(PAGES, page, payload.expected_updated_at)
    apply_document(db, page, payload)
    content.touch(page, user)
    content.add_contributor(db, PAGES, page, user)
    audit.record(
        db,
        action="page.update",
        entity_type="page",
        entity_id=page.id,
        actor=user,
        ip_address=client_address(request),
        detail={"bodyLength": len(payload.body), "isLanding": page.is_landing},
    )
    with landing_race_is_a_conflict(db):
        db.commit()
    return page_out(page)


content.lifecycle_routes(router, PAGES)
