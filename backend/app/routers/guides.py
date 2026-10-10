"""Guides: listing, the whole-document save and the PDF export.

Publishing, unpublishing, archiving, view counting and history are the shared
lifecycle in ``content``; what is left here is what only a guide has — tags,
steps and the listing that the wiki's embedded guide lists are built from.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import ColumnElement, Select, distinct, exists, func, or_, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import joinedload, selectinload

from .. import audit, content, errors, images, pdf, published
from ..auth import AnyUser, AuthorUser, DbDep, client_address
from ..documents import apply_document, assert_publishable
from ..models import (
    Bullet,
    Category,
    Guide,
    GuideContributor,
    GuideRevision,
    GuideTag,
    Media,
    PublishedGuide,
    PublishedGuideTag,
    Step,
    StepMedia,
    Tag,
    User,
)
from ..schemas import (
    MAX_SEARCH_TERM_CHARS,
    ContentStatus,
    ContentView,
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
    projection_model=PublishedGuide,
    project=published.project_guide,
    unproject=published.clear_guide,
    from_snapshot=published.guide_from_snapshot,
    fingerprint=published.guide_fingerprint,
    restore=published.restore_guide,
    eager=_detail_options,
)


def _slug_taken(db: DbSession, slug: str) -> bool:
    return db.scalar(select(func.count()).select_from(Guide).where(Guide.slug == slug)) > 0


def summary_statement() -> Select:
    """The working-copy listing: a guide and its step count, tags and author.

    The count is a correlated subquery and the tags arrive in one extra ``IN``
    query for the whole page of results, so a wiki landing page that embeds a
    list of eighty guides costs the same handful of statements as one that
    embeds three.
    """
    step_count = select(func.count(Step.id)).where(Step.guide_id == Guide.id).correlate(Guide).scalar_subquery()
    return select(Guide, step_count.label("step_count")).options(
        joinedload(Guide.author), selectinload(Guide.tags)
    )


def published_summary_statement(*columns: Any) -> Select:
    """The readers' listing: each published guide with its snapshot's columns.

    Same cost as the working-copy listing — one statement, plus one for the
    tags of everything it returned — and no snapshot is opened.
    """
    return content.published_statement(GUIDES, *columns).options(
        joinedload(Guide.author), selectinload(PublishedGuide.tags)
    )


@dataclass(frozen=True)
class GuideSide:
    """The columns a guide query filters, searches and sorts on, for one audience.

    A reader's query and an author's are the same query over different text:
    the snapshot's for the one, the working copy's for the other. Naming the
    columns once per audience keeps that the only difference, so that a filter
    added to the listing cannot be added for authors and forgotten for readers.
    """

    title: Any
    summary: Any
    category_id: Any
    updated_at: Any
    tag_guide_id: Any
    tag_id: Any
    step_text: Callable[[str], ColumnElement[bool]]

    def carries_all_tags(self, slugs: list[str]) -> ColumnElement[bool]:
        """Guides that carry every one of the given tags, not merely one of them."""
        matching = (
            select(self.tag_guide_id)
            .join(Tag, Tag.id == self.tag_id)
            .where(Tag.slug.in_(slugs))
            .group_by(self.tag_guide_id)
            .having(func.count(distinct(Tag.id)) == len(slugs))
        )
        return Guide.id.in_(matching)

    def has_tag_like(self, term: str) -> ColumnElement[bool]:
        return exists(
            select(self.tag_guide_id)
            .join(Tag, Tag.id == self.tag_id)
            .where(
                self.tag_guide_id == Guide.id,
                or_(content.contains(Tag.name, term), content.contains(Tag.slug, term)),
            )
        )

    def matches_listing(self, term: str) -> ColumnElement[bool]:
        return or_(content.contains(self.title, term), content.contains(self.summary, term), self.has_tag_like(term))

    def matches_search(self, term: str) -> ColumnElement[bool]:
        return or_(self.matches_listing(term), self.step_text(term))


def _working_step_text(term: str) -> ColumnElement[bool]:
    in_title = exists(select(Step.id).where(Step.guide_id == Guide.id, content.contains(Step.title, term)))
    in_bullet = exists(
        select(Bullet.id)
        .join(Step, Step.id == Bullet.step_id)
        .where(Step.guide_id == Guide.id, content.contains(Bullet.text, term))
    )
    return or_(in_title, in_bullet)


def _published_step_text(term: str) -> ColumnElement[bool]:
    return content.contains(PublishedGuide.search_text, term)


WORKING_COPY = GuideSide(
    title=Guide.title,
    summary=Guide.summary,
    category_id=Guide.category_id,
    updated_at=Guide.updated_at,
    tag_guide_id=GuideTag.guide_id,
    tag_id=GuideTag.tag_id,
    step_text=_working_step_text,
)

SNAPSHOT = GuideSide(
    title=PublishedGuide.title,
    summary=PublishedGuide.summary,
    category_id=PublishedGuide.category_id,
    updated_at=func.coalesce(Guide.snapshot_updated_at, Guide.updated_at),
    tag_guide_id=PublishedGuideTag.owner_id,
    tag_id=PublishedGuideTag.tag_id,
    step_text=_published_step_text,
)


def summaries(db: DbSession, user: User, refine: Callable[[Select, GuideSide], Select]) -> list[tuple[Guide, GuideSummaryOut, Any]]:
    """Run a guide query for this caller and serialise each row for them.

    ``refine`` adds the filters, ordering and limit, written against whichever
    side it is handed, and may select one extra column — search uses that for
    its rank — which comes back as the third element.
    """
    if content.serves_published(user):
        rows = db.execute(refine(published_summary_statement(), SNAPSHOT)).all()
        return [(row[0], published.guide_summary(row[0], row[1]), row[2] if len(row) > 2 else None) for row in rows]
    statement = refine(summary_statement().where(content.visible_to(Guide, user)), WORKING_COPY)
    rows = db.execute(statement).all()
    return [(row[0], guide_summary_out(row[0], row[1]), row[2] if len(row) > 2 else None) for row in rows]


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
    """Guides, newest first, as this caller sees them.

    A viewer's listing is the published snapshots': their titles, their tags,
    their categories. An author's is the working copies', because an author
    looks for a guide by what they have been typing into it.
    """
    wanted = parse_tag_filter(tags)
    term = (q or "").strip()

    def refine(statement: Select, side: GuideSide) -> Select:
        if status_filter is not None:
            statement = statement.where(Guide.status == status_filter)
        if category_id is not None:
            statement = statement.where(side.category_id == category_id)
        if author_id is not None:
            statement = statement.where(Guide.author_id == author_id)
        if wanted:
            statement = statement.where(side.carries_all_tags(wanted))
        if term:
            statement = statement.where(side.matches_listing(term))
        return statement.order_by(side.updated_at.desc(), Guide.id.desc())

    return [summary for _, summary, _ in summaries(db, user, refine)]


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
def read_guide(key: str, db: DbDep, user: AnyUser, view: ContentView | None = None) -> Any:
    """A guide: the published snapshot for a viewer, the working copy for an author.

    ``?view=published`` gives an author exactly what a viewer is given, and is
    404 for a guide that is not published at the moment.
    """
    return content.read(db, GUIDES, user, key, view)


def _image_files(db: DbSession, document: GuideOut) -> dict[str, Path]:
    """Where each of the document's images is on disk, leaving out any that are gone.

    The path is the display copy's. A printed column is thirteen centimetres
    wide, and the display copy is already more than it can show; handing the
    renderer a forty-megapixel original instead costs over a hundred megabytes
    per image to throw nearly all of it away.
    """
    wanted = {item.id for step in document.steps for item in step.media if item.kind == "image"}
    if not wanted:
        return {}
    media_root = get_settings().media_root
    rows = db.execute(
        select(Media.id, Media.storage_path, Media.width, Media.height, Media.content_type).where(Media.id.in_(wanted))
    ).all()
    db.close()
    files: dict[str, Path] = {}
    for media_id, storage_path, width, height, content_type in rows:
        try:
            files[media_id] = images.display_file(media_root, storage_path, width, height, content_type)
        except errors.ApiError:
            continue
    return files


def _pdf_headers(slug: str) -> dict[str, str]:
    return {
        "Content-Disposition": f'attachment; filename="{slug}.pdf"',
        "Cache-Control": "private, no-store",
    }


@router.get("/{key}/pdf", response_class=Response)
def read_guide_pdf(key: str, db: DbDep, user: AnyUser, view: ContentView | None = None) -> Response:
    """The guide as a printable document, under the same rule as reading it.

    A viewer gets the published snapshot; an author gets the working copy, or
    the snapshot with ``?view=published``. The order of what follows is the
    design, because this is the most expensive thing a reader can ask for:

    1. One short query says whether the caller may have the guide at all, and
       the connection goes straight back to the pool.
    2. A published version is immutable, so its export is kept on disk. If it
       is there it is sent, and nothing else below happens.
    3. Otherwise a render slot is taken — at once or not at all, 429 with
       ``Retry-After`` — *before* the document is loaded.
    4. The document and the image paths are read, and the connection is given
       back again before the layout starts. Rendering can take seconds, and
       nothing it needs is still in the database by then.

    So a request that is waiting never holds a connection, and a request that
    cannot be served yet does not wait.
    """
    user_id = user.id
    as_published = content.serves_published(user, view)
    settings = get_settings()

    if as_published:
        found = db.execute(
            content.published_statement(GUIDES)
            .join(Category, Category.id == PublishedGuide.category_id)
            .where(or_(Guide.id == key, Guide.slug == key))
            .with_only_columns(Guide.id, Guide.slug, PublishedGuide.revision_id, Category.name)
        ).one_or_none()
    else:
        found = db.execute(
            select(Guide.id, Guide.slug).where(or_(Guide.id == key, Guide.slug == key), content.visible_to(Guide, user))
        ).one_or_none()
    db.close()
    if found is None:
        raise GUIDES.missing()
    guide_id, slug = found[0], found[1]

    cache_path = None
    if as_published:
        cache_path = pdf.cache_file(settings.pdf_cache_root, guide_id, found[2], found[3])
        if pdf.cached(cache_path) is not None:
            return FileResponse(cache_path, media_type="application/pdf", headers=_pdf_headers(slug))

    with pdf.render_slot(user_id):
        if as_published:
            # Asked for again rather than fetched by the identifier found
            # above: in the moment between, the guide can have been withdrawn.
            guide, revision = content.load_published(db, GUIDES, guide_id)
            document = published.guide_from_snapshot(revision.document, guide)
            category_name = found[3]
            cache_path = pdf.cache_file(settings.pdf_cache_root, guide_id, revision.id, category_name)
        else:
            guide = content.load_editable(db, GUIDES, guide_id)
            document = guide_out(guide)
            category_name = guide.category.name
        files = _image_files(db, document)
        db.close()
        payload = pdf.render_guide(document, category_name, files)

    if cache_path is not None:
        pdf.store(cache_path, payload)
    return Response(content=payload, media_type="application/pdf", headers=_pdf_headers(slug))


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
    guide = content.settle_changes(db, GUIDES, guide)
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
