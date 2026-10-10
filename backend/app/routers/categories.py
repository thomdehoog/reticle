"""The category tree, and each category's landing page.

Categories are returned flat and the client assembles the tree from
``parentId``. That keeps the endpoint a single query no matter how deep ZMB
nests its sections, and it means reordering is one PATCH rather than a
recursive rewrite.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .. import audit, content, errors, published
from ..auth import AdminUser, AnyUser, DbDep, client_address
from ..models import Category, Guide, Page, PageRevision, PublishedGuide, PublishedPage
from ..schemas import (
    CategoryCreateIn,
    CategoryOut,
    CategoryPatchIn,
    ContentView,
    PageOut,
    category_out,
    page_out,
)
from ..slugs import unique_slug
from .pages import PAGES

router = APIRouter(prefix="/api/categories", tags=["categories"])


def _load(db: DbSession, category_id: str) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise errors.not_found("That category does not exist.")
    return category


def _slug_taken(db: DbSession, slug: str) -> bool:
    return db.scalar(select(func.count()).select_from(Category).where(Category.slug == slug)) > 0


def _next_order_index(db: DbSession, parent_id: str | None) -> int:
    sibling_filter = Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id
    highest = db.scalar(select(func.max(Category.order_index)).where(sibling_filter))
    return 0 if highest is None else highest + 1


def _assert_no_cycle(db: DbSession, category: Category, parent_id: str) -> None:
    """Walk to the root from the proposed parent.

    A cycle would make the client's tree build recurse forever and would orphan
    every guide underneath it, so it is refused rather than repaired.
    """
    if parent_id == category.id:
        raise errors.validation_failed("A category cannot be its own parent.")
    cursor = db.get(Category, parent_id)
    while cursor is not None:
        if cursor.id == category.id:
            raise errors.validation_failed("That move would put the category inside itself.")
        cursor = db.get(Category, cursor.parent_id) if cursor.parent_id else None


@router.get("", response_model=list[CategoryOut])
def list_categories(db: DbDep, user: AnyUser) -> list[CategoryOut]:
    categories = db.scalars(select(Category).order_by(Category.order_index, Category.name)).all()
    return [category_out(category) for category in categories]


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreateIn, request: Request, db: DbDep, user: AdminUser) -> CategoryOut:
    name = payload.name.strip()
    if not name:
        raise errors.validation_failed("A category needs a name.")

    if payload.parent_id is not None and db.get(Category, payload.parent_id) is None:
        raise errors.validation_failed("That parent category does not exist.")

    category = Category(
        slug=unique_slug(name, lambda candidate: _slug_taken(db, candidate), fallback="category"),
        name=name,
        description=payload.description,
        parent_id=payload.parent_id,
        order_index=_next_order_index(db, payload.parent_id),
        is_hidden=payload.is_hidden,
    )
    db.add(category)
    db.flush()
    audit.record(
        db,
        action="category.create",
        entity_type="category",
        entity_id=category.id,
        actor=user,
        ip_address=client_address(request),
        detail={"name": category.name, "slug": category.slug},
    )
    db.commit()
    return category_out(category)


@router.patch("/{category_id}", response_model=CategoryOut)
def patch_category(
    category_id: str,
    payload: CategoryPatchIn,
    request: Request,
    db: DbDep,
    user: AdminUser,
) -> CategoryOut:
    category = _load(db, category_id)
    changed = payload.model_fields_set

    if "name" in changed and payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise errors.validation_failed("A category needs a name.")
        category.name = name

    if "description" in changed and payload.description is not None:
        category.description = payload.description

    if "parent_id" in changed:
        if payload.parent_id is None:
            category.parent_id = None
        else:
            if db.get(Category, payload.parent_id) is None:
                raise errors.validation_failed("That parent category does not exist.")
            _assert_no_cycle(db, category, payload.parent_id)
            category.parent_id = payload.parent_id

    if "order_index" in changed and payload.order_index is not None:
        category.order_index = payload.order_index

    if "is_hidden" in changed and payload.is_hidden is not None:
        category.is_hidden = payload.is_hidden

    audit.record(
        db,
        action="category.update",
        entity_type="category",
        entity_id=category.id,
        actor=user,
        ip_address=client_address(request),
        detail={"fields": sorted(changed)},
    )
    db.commit()
    return category_out(category)


@router.get("/{category_id}/page", response_model=PageOut | None)
def read_landing_page(
    category_id: str, db: DbDep, user: AnyUser, view: ContentView | None = None
) -> PageOut | None:
    """The category's landing page, or ``null`` when the caller can see none.

    An unwritten landing page is the normal state of most categories, so its
    absence is an answer rather than an error: the frontend falls back to the
    plain listing without having to treat a 404 as success.

    Like any page it is the published snapshot for a viewer (and for an author
    who asks with ``?view=published``), and which page *is* the landing page is
    then the snapshot's say too: a page whose unpublished edit moves it to
    another category is still this category's landing page for readers until
    that edit is published. Two snapshots can claim one category for a moment
    in that way; the more recently published wins.
    """
    category = _load(db, category_id)
    if content.serves_published(user, view):
        found = db.execute(
            content.published_statement(PAGES, PageRevision)
            .join(PageRevision, PageRevision.id == PublishedPage.revision_id)
            .where(PublishedPage.category_id == category.id, PublishedPage.is_landing.is_(True))
            .order_by(Page.published_at.desc(), Page.id.desc())
        ).first()
        if found is None:
            return None
        return PAGES.from_snapshot(found[2].document, found[0], reveal_changes=user.role != "viewer")
    page = db.scalars(
        select(Page)
        .where(Page.category_id == category.id, Page.is_landing.is_(True), content.visible_to(Page, user))
        .options(*PAGES.eager())
    ).first()
    return None if page is None else page_out(page)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_category(category_id: str, request: Request, db: DbDep, user: AdminUser) -> Response:
    category = _load(db, category_id)

    children = db.scalar(select(func.count()).select_from(Category).where(Category.parent_id == category.id))
    if children:
        raise errors.conflict("Move or delete the sub-categories first.")

    guides = db.scalar(select(func.count()).select_from(Guide).where(Guide.category_id == category.id))
    if guides:
        raise errors.conflict(
            "Move the guides in this category somewhere else first. Archived guides count: they still belong to it."
        )

    pages = db.scalar(select(func.count()).select_from(Page).where(Page.category_id == category.id))
    if pages:
        raise errors.conflict(
            "Move the pages in this category somewhere else first, including its landing page and any archived ones."
        )

    # A guide or page can have been moved out in an edit that is not published
    # yet. Readers are still being shown it here, so the category is still in use.
    published.withdraw_stale(db)
    still_published = db.scalar(
        select(func.count()).select_from(PublishedGuide).where(PublishedGuide.category_id == category.id)
    ) + db.scalar(select(func.count()).select_from(PublishedPage).where(PublishedPage.category_id == category.id))
    if still_published:
        raise errors.conflict(
            "Something that was moved out of this category is still published in it. "
            "Publish or discard those unpublished changes first."
        )

    audit.record(
        db,
        action="category.delete",
        entity_type="category",
        entity_id=category.id,
        actor=user,
        ip_address=client_address(request),
        detail={"name": category.name},
    )
    db.delete(category)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
