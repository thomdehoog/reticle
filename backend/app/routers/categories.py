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
from ..auth import AdminUser, DbDep, MaybeUser, client_address
from ..models import PUBLISHED, Category, CategoryTagOrder, Guide, Media, Page, Tag
from ..schemas import (
    CategoryCreateIn,
    CategoryDeleteIn,
    CategoryOut,
    CategoryPatchIn,
    PageOut,
    TagOrderIn,
    category_out,
    page_out,
)
from ..security import verify_password
from ..slugs import unique_slug
from ..visibility import sees_unpublished

router = APIRouter(prefix="/api/categories", tags=["categories"])


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
    sibling_filter = (
        Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id
    )
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


def _assert_two_levels(db: DbSession, parent_id: str, moving: Category | None = None) -> None:
    """The tree is a section and its sub-sections, and stops there.

    Three levels is not a shape this site can draw. The rail's path is Home, a
    section, a sub-section; a section with sub-sections lists them and a section
    without them lists its guides — so a sub-sub-section would be a level with
    no screen of its own, reachable only by URL, and the guides inside it would
    appear in no listing at all.

    Two rules, and both are the same rule from the two ends:

    - the proposed parent must itself be top-level, or the new child sits at the
      third level;
    - a category that already has children may not become somebody's child,
      because its children would.

    ZMB's tree is exactly two deep already, so this refuses shapes nobody has
    rather than rejecting anything that exists.
    """
    parent = db.get(Category, parent_id)
    if parent is not None and parent.parent_id is not None:
        raise errors.validation_failed(
            "A section holds sub-sections, and a sub-section holds guides — so a sub-section "
            "cannot hold another one."
        )

    if moving is not None:
        children = db.scalar(
            select(func.count()).select_from(Category).where(Category.parent_id == moving.id)
        )
        if children:
            raise errors.validation_failed(
                "Move the sub-sections out of this one first: putting it inside another section "
                "would make them a third level."
            )


def _with_descendants(db: DbSession, root: Category) -> list[Category]:
    """The section and everything filed under it, parents before children.

    Written as a walk rather than as "the section and its children", because the
    depth rule is enforced at the other end and a delete that quietly assumed
    two levels would leave rows behind the day that rule changed. Returned in
    order so the caller can delete the list backwards and never break a foreign
    key.
    """
    ordered: list[Category] = []
    frontier = [root]
    while frontier:
        current = frontier.pop(0)
        ordered.append(current)
        frontier.extend(
            db.scalars(
                select(Category)
                .where(Category.parent_id == current.id)
                .order_by(Category.order_index)
            )
        )
    return ordered


def _landing_heroes(db: DbDep) -> dict[str, str]:
    """Each section's landing-page picture, by section.

    One query for the whole listing rather than one per section: this endpoint
    is asked for on every browse screen there is, and a facility with eighty
    sections would otherwise pay eighty round trips to draw one wall of tiles.
    """
    rows = db.execute(
        select(Page.category_id, Page.hero_media_id).where(
            Page.is_landing.is_(True),
            Page.category_id.is_not(None),
            Page.hero_media_id.is_not(None),
        )
    ).all()
    return dict(rows)  # type: ignore[arg-type]


@router.get("", response_model=list[CategoryOut])
def list_categories(db: DbDep, user: MaybeUser) -> list[CategoryOut]:
    categories = db.scalars(select(Category).order_by(Category.order_index, Category.name)).all()
    heroes = _landing_heroes(db)
    return [category_out(category, heroes.get(category.id)) for category in categories]


@router.get("/{category_id}/page", response_model=PageOut | None)
def read_landing_page(category_id: str, db: DbDep, user: MaybeUser) -> PageOut | None:
    """The category's landing content, or ``null`` when nobody has written it.

    Null rather than 404: a category with no landing page yet is the ordinary
    state of a fresh install, and making the client treat that as an error would
    put a red alert on every category page at ZMB until somebody wrote one.
    """
    _load(db, category_id)
    statement = select(Page).where(Page.category_id == category_id, Page.is_landing.is_(True))
    if not sees_unpublished(user):
        statement = statement.where(Page.status == PUBLISHED)
    else:
        statement = statement.where(Page.status != "archived")
    page = db.scalars(statement).first()
    return page_out(page) if page is not None else None


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreateIn, request: Request, db: DbDep, user: AdminUser
) -> CategoryOut:
    name = payload.name.strip()
    if not name:
        raise errors.validation_failed("A category needs a name.")

    if payload.parent_id is not None:
        if db.get(Category, payload.parent_id) is None:
            raise errors.validation_failed("That parent category does not exist.")
        _assert_two_levels(db, payload.parent_id)

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
            _assert_two_levels(db, payload.parent_id, moving=category)
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


@router.put("/{category_id}/tag-order", response_model=CategoryOut)
def set_tag_order(
    category_id: str,
    payload: TagOrderIn,
    request: Request,
    db: DbDep,
    user: AdminUser,
) -> CategoryOut:
    """Stack this section's groups in the order given.

    The whole order at once, not one group's new position: the index is a
    position rather than a weight, so writing one and leaving the rest would put
    two groups on the same number and let the tie decide which came first.

    Administrator, where moving a row between groups is author. The difference is
    what is being changed: a row's group is a fact about the document and is
    reachable from its own editor, while the running order of a section's page is
    the section's, and every reader gets it.

    Tags that do not exist are refused rather than minted. This names groups, and
    a group with nothing in it is not one — an order that could invent them would
    let a typo add a heading no document could ever be under.
    """
    category = _load(db, category_id)

    slugs: list[str] = []
    for slug in payload.tags:
        if slug not in slugs:
            slugs.append(slug)

    found = {tag.slug: tag for tag in db.scalars(select(Tag).where(Tag.slug.in_(slugs)))}
    missing = [slug for slug in slugs if slug not in found]
    if missing:
        raise errors.validation_failed(f"No such tag: {', '.join(missing)}.")

    # Cleared and flushed before the new rows are added, not replaced in one
    # assignment. `delete-orphan` would issue the inserts first and the deletes
    # after, and every tag that is in both the old order and the new one collides
    # with itself on `uq_category_tag_order` — so re-stacking the same groups was
    # the one case that failed.
    category.tag_order.clear()
    db.flush()
    category.tag_order = [
        CategoryTagOrder(category_id=category.id, tag_id=found[slug].id, order_index=index)
        for index, slug in enumerate(slugs)
    ]

    audit.record(
        db,
        action="category.reorder_tags",
        entity_type="category",
        entity_id=category.id,
        actor=user,
        ip_address=client_address(request),
        detail={"tags": slugs},
    )
    db.commit()
    return category_out(category)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_category(
    category_id: str,
    payload: CategoryDeleteIn,
    request: Request,
    db: DbDep,
    user: AdminUser,
) -> Response:
    """Remove a section, once the caller has proved they are still themselves.

    **The password is checked here and not only in the dialog.** A confirmation
    an administrator types into a modal is a guard against the hand, and this
    endpoint is reachable without the modal — so a check that lived in the
    browser would stop the mis-click and nothing else. It is the same shape as
    changing one's own password in ``users``: the current password, verified
    against the stored hash, and a wrong one is ``invalid_credentials`` rather
    than a validation error, because it is a credential that was wrong.

    **It takes everything underneath with it.** Sub-sections, every guide filed
    in any of them, and every wiki page including the landing pages. It used to
    refuse while a section still held anything, which made deleting one a chore
    of emptying it by hand first and meant the button could not do what it said.
    It does what it says now, and the password is what stands in the way instead.

    This is the one place in Reticle where content is destroyed rather than
    archived. A guide deleted on its own is marked ``archived`` and its rows
    stay; a guide inside a deleted section is gone, with its steps, its
    annotations and its revisions. Media rows are left alone — a photograph may
    be used by a guide in another section, and an orphaned upload wastes disk
    where a missing one breaks a page that still exists.
    """
    if not verify_password(user.password_hash, payload.password):
        audit.record(
            db,
            action="category.delete_refused",
            entity_type="category",
            entity_id=category_id,
            actor=user,
            ip_address=client_address(request),
            detail={"reason": "password"},
        )
        db.commit()
        raise errors.invalid_credentials("That is not your password.")

    category = _load(db, category_id)
    doomed = _with_descendants(db, category)
    ids = [row.id for row in doomed]

    guides = list(db.scalars(select(Guide).where(Guide.category_id.in_(ids))))
    pages = list(db.scalars(select(Page).where(Page.category_id.in_(ids))))

    for guide in guides:
        db.delete(guide)
    for page in pages:
        db.delete(page)
    # Children before parents: the foreign key points upwards.
    for row in reversed(doomed):
        db.delete(row)

    # Counted, because this is the record of what was destroyed and the rows
    # themselves are about to stop existing. "Deleted Electron Microscopy" is
    # not an answer to "where did those eleven guides go".
    audit.record(
        db,
        action="category.delete",
        entity_type="category",
        entity_id=category.id,
        actor=user,
        ip_address=client_address(request),
        detail={
            "name": category.name,
            "sections": [row.name for row in doomed],
            "guides": len(guides),
            "pages": len(pages),
        },
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
