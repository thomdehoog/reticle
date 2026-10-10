"""Guides: listing, the whole-document save and the PDF export.

Publishing, unpublishing, archiving, view counting and history are the shared
lifecycle in ``content``; what is left here is what only a guide has — tags,
steps and the listing that the wiki's embedded guide lists are built from.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request, Response, status
from sqlalchemy import ColumnElement, Select, distinct, exists, func, or_, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import joinedload, selectinload

from .. import audit, content, errors, images, pdf
from ..auth import AnyUser, AuthorUser, DbDep, client_address
from ..documents import apply_document, assert_publishable
from ..models import (
    Bullet,
    Category,
    Guide,
    GuideContributor,
    GuideRevision,
    GuideTag,
    Step,
    StepMedia,
    Tag,
)
from ..schemas import (
    MAX_SEARCH_TERM_CHARS,
    ContentStatus,
    GuideCreateIn,
    GuideDocumentIn,
    GuideOut,
    GuideSummaryOut,
    guide_out,
    guide_summary_out,
)
from ..settings import get_settings
from ..slugs import tag_slug, unique_slug

router = APIRouter(prefix="/api/guides", tags=["guides"])


def _detail_options() -> list[Any]:
    """Load a whole guide in a fixed number of queries, however many steps it has."""
    return [
        joinedload(Guide.author),
        joinedload(Guide.last_edited_by),
        selectinload(Guide.tags),
        selectinload(Guide.contributor_links),
        selectinload(Guide.steps).selectinload(Step.bullets),
        selectinload(Guide.steps).selectinload(Step.media_links).joinedload(StepMedia.media),
    ]


GUIDES = content.ContentKind(
    name="guide",
    model=Guide,
    revision_model=GuideRevision,
    contributor_model=GuideContributor,
    out_model=GuideOut,
    serialise=guide_out,
    assert_publishable=assert_publishable,
    eager=_detail_options,
)


def _slug_taken(db: DbSession, slug: str) -> bool:
    return db.scalar(select(func.count()).select_from(Guide).where(Guide.slug == slug)) > 0


def summary_statement() -> Select:
    """The listing projection: a guide and its step count, tags and author.

    The count is a correlated subquery and the tags arrive in one extra ``IN``
    query for the whole page of results, so a wiki landing page that embeds a
    list of eighty guides costs the same handful of statements as one that
    embeds three.
    """
    step_count = select(func.count(Step.id)).where(Step.guide_id == Guide.id).correlate(Guide).scalar_subquery()
    return select(Guide, step_count.label("step_count")).options(
        joinedload(Guide.author), selectinload(Guide.tags)
    )


def carries_all_tags(slugs: list[str]) -> ColumnElement[bool]:
    """Guides that carry every one of the given tags, not merely one of them."""
    matching = (
        select(GuideTag.guide_id)
        .join(Tag, Tag.id == GuideTag.tag_id)
        .where(Tag.slug.in_(slugs))
        .group_by(GuideTag.guide_id)
        .having(func.count(distinct(Tag.id)) == len(slugs))
    )
    return Guide.id.in_(matching)


def has_tag_like(term: str) -> ColumnElement[bool]:
    return exists(
        select(GuideTag.guide_id)
        .join(Tag, Tag.id == GuideTag.tag_id)
        .where(GuideTag.guide_id == Guide.id, or_(content.contains(Tag.name, term), content.contains(Tag.slug, term)))
    )


def has_step_text_like(term: str) -> ColumnElement[bool]:
    in_title = exists(select(Step.id).where(Step.guide_id == Guide.id, content.contains(Step.title, term)))
    in_bullet = exists(
        select(Bullet.id)
        .join(Step, Step.id == Bullet.step_id)
        .where(Step.guide_id == Guide.id, content.contains(Bullet.text, term))
    )
    return or_(in_title, in_bullet)


def parse_tag_filter(raw: str | None) -> list[str]:
    if not raw:
        return []
    slugs = {tag_slug(part) for part in raw.split(",")}
    return sorted(slug for slug in slugs if slug)


@router.get("", response_model=list[GuideSummaryOut])
def list_guides(
    db: DbDep,
    user: AnyUser,
    category_id: str | None = Query(default=None, alias="categoryId", max_length=40),
    status_filter: ContentStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=MAX_SEARCH_TERM_CHARS),
    author_id: str | None = Query(default=None, alias="authorId", max_length=40),
    tags: str | None = Query(default=None, max_length=2000),
) -> list[GuideSummaryOut]:
    statement = summary_statement().where(content.visible_to(Guide, user))

    if status_filter is not None:
        statement = statement.where(Guide.status == status_filter)
    if category_id is not None:
        statement = statement.where(Guide.category_id == category_id)
    if author_id is not None:
        statement = statement.where(Guide.author_id == author_id)

    wanted = parse_tag_filter(tags)
    if wanted:
        statement = statement.where(carries_all_tags(wanted))

    term = (q or "").strip()
    if term:
        statement = statement.where(
            or_(content.contains(Guide.title, term), content.contains(Guide.summary, term), has_tag_like(term))
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
    content.add_contributor(db, GUIDES, guide, user)
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
    return guide_out(content.load_visible(db, GUIDES, user, key))


def _image_files(guide: Guide) -> dict[str, Path]:
    """Where each of the guide's images is on disk, leaving out any that are gone."""
    media_root = get_settings().media_root
    files: dict[str, Path] = {}
    for step in guide.steps:
        for link in step.media_links:
            if link.media.kind != "image":
                continue
            try:
                files[link.media.id] = images.resolve_file(media_root, link.media.storage_path)
            except errors.ApiError:
                continue
    return files


@router.get("/{key}/pdf", response_class=Response)
def read_guide_pdf(key: str, db: DbDep, user: AnyUser) -> Response:
    """The guide as a printable document, under the same rule as reading it.

    The session is closed before the layout starts. Rendering can take seconds,
    and nothing it needs is still in the database by then.
    """
    guide = content.load_visible(db, GUIDES, user, key)
    category_name = guide.category.name
    document = guide_out(guide)
    files = _image_files(guide)
    slug = guide.slug
    db.close()

    return Response(
        content=pdf.render_guide(document, category_name, files),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{slug}.pdf"',
            "Cache-Control": "private, no-store",
        },
    )


@router.put("/{guide_id}", response_model=GuideOut)
def save_guide(
    guide_id: str,
    payload: GuideDocumentIn,
    request: Request,
    db: DbDep,
    user: AuthorUser,
) -> GuideOut:
    guide = content.load_editable(db, GUIDES, guide_id)
    content.assert_not_stale(GUIDES, guide, payload.expected_updated_at)
    apply_document(db, guide, payload)
    content.touch(guide, user)
    content.add_contributor(db, GUIDES, guide, user)
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


content.lifecycle_routes(router, GUIDES)
