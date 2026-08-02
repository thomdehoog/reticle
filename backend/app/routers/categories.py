"""The category tree.

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

from .. import audit, errors
from ..auth import AdminUser, AnyUser, DbDep, client_address
from ..models import Category, Guide, Media, Page
from ..schemas import (
    CategoryCreateIn,
    CategoryOut,
    CategoryPatchIn,
    PageOut,
    category_out,
    page_out,
)
from ..slugs import unique_slug

router = APIRouter(prefix="/api/categories", tags=["categories"])

READER_STATUS = "published"


def _load(db: DbSession, category_id: str) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise errors.not_found("That category does not exist.")
    return category


def _slug_taken(db: DbSession, slug: str) -> bool:
    return db.scalar(select(func.count()).select_from(Category).where(Category.slug == slug)) > 0


def _validated_hero(db: DbSession, media_id: str | None) -> str | None:
    """The picture a section is browsed by.

    Refused rather than stored blindly: an identifier that resolves to nothing
    would leave every tile for that section showing a broken image, which is
    worse than the drawn figure it would otherwise fall back to.
    """
    if media_id is None:
        return None
    media = db.get(Media, media_id)
    if media is None or media.kind != "image":
        raise errors.validation_failed("That picture does not exist.")
    return media.id


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


@router.get("/{category_id}/page", response_model=PageOut | None)
def read_landing_page(category_id: str, db: DbDep, user: AnyUser) -> PageOut | None:
    """The category's landing content, or ``null`` when nobody has written it.

    Null rather than 404: a category with no landing page yet is the ordinary
    state of a fresh install, and making the client treat that as an error would
    put a red alert on every category page at ZMB until somebody wrote one.
    """
    _load(db, category_id)
    statement = select(Page).where(Page.category_id == category_id, Page.is_landing.is_(True))
    if user.role == "viewer":
        statement = statement.where(Page.status == READER_STATUS)
    else:
        statement = statement.where(Page.status != "archived")
    page = db.scalars(statement).first()
    return page_out(page) if page is not None else None


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
        hero_media_id=_validated_hero(db, payload.hero_media_id),
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

    if "hero_media_id" in changed:
        category.hero_media_id = _validated_hero(db, payload.hero_media_id)

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


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_category(category_id: str, request: Request, db: DbDep, user: AdminUser) -> Response:
    category = _load(db, category_id)

    children = db.scalar(select(func.count()).select_from(Category).where(Category.parent_id == category.id))
    if children:
        raise errors.conflict("Move or delete the sub-categories first.")

    guides = db.scalar(select(func.count()).select_from(Guide).where(Guide.category_id == category.id))
    if guides:
        raise errors.conflict("Move the guides in this category somewhere else first.")

    pages = db.scalar(select(func.count()).select_from(Page).where(Page.category_id == category.id))
    if pages:
        raise errors.conflict("Move or delete this category's wiki pages first.")

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
