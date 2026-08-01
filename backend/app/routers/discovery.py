"""Tags and search — how anything is actually found.

ZMB's site is navigated by tag: 137 of them across 257 guides, with one LAS X
guide appearing under ten instrument headings. So the tag list is not a
reporting nicety, it is the index, and it carries counts because the guide
editor's tag input uses them to steer authors onto the spelling that already
exists rather than inventing a fourth one.

Search spans both content types. A ZMB reader looking for "immersion oil" does
not know or care whether the answer was written as a guide or as a wiki page,
and a search that only covered guides sent them to the one place the answer was
not.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import case, func, or_, select

from ..auth import AnyUser, DbDep
from ..models import Bullet, Guide, GuideTag, Page, Step, Tag
from ..schemas import (
    GuideHitOut,
    PageHitOut,
    SearchHitOut,
    TagOut,
    guide_summary_out,
    page_summary_out,
    tag_out,
)

router = APIRouter(prefix="/api", tags=["discovery"])

READER_STATUS = "published"

SEARCH_LIMIT = 100
"""One screen's worth and then some.

Reticle's corpus is a few hundred documents, so an unbounded query is not slow
today — but the endpoint is reachable by every account, and a search for "e"
that returns everything is a cheap way to make the server serialise the entire
institute's documentation on demand.
"""


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/tags", response_model=list[TagOut])
def list_tags(db: DbDep, user: AnyUser) -> list[TagOut]:
    """Every tag that is actually on something the caller may see.

    The count is computed against the same visibility rule as the guide list, so
    a viewer is never shown a tag whose entire membership is drafts — following
    it would land them on an empty page and look like a broken link.
    """
    countable = select(func.count(GuideTag.id)).select_from(GuideTag).join(
        Guide, Guide.id == GuideTag.guide_id
    )
    if user.role == "viewer":
        countable = countable.where(Guide.status == READER_STATUS)
    else:
        countable = countable.where(Guide.status != "archived")

    guide_count = countable.where(GuideTag.tag_id == Tag.id).correlate(Tag).scalar_subquery()

    rows = db.execute(
        select(Tag, guide_count.label("guide_count")).order_by(Tag.slug)
    ).all()
    return [tag_out(tag, count) for tag, count in rows if count > 0]


@router.get("/search", response_model=list[SearchHitOut])
def search(
    db: DbDep,
    user: AnyUser,
    q: str = Query(default="", max_length=200),
) -> list[SearchHitOut]:
    term = q.strip()
    if not term:
        return []

    pattern = f"%{_escape_like(term)}%"

    step_count = (
        select(func.count(Step.id)).where(Step.guide_id == Guide.id).correlate(Guide).scalar_subquery()
    )
    # A reader searching for "immersion oil" is looking for the step that says
    # it, and at ZMB that phrase is usually in a bullet rather than in a title
    # or a summary. A search that only covered the front matter would answer
    # "nothing found" about a procedure that explains it in detail.
    inside_a_step = (
        select(Step.id)
        .outerjoin(Bullet, Bullet.step_id == Step.id)
        .where(
            Step.guide_id == Guide.id,
            or_(
                Step.title.ilike(pattern, escape="\\"),
                Bullet.text.ilike(pattern, escape="\\"),
            ),
        )
        .correlate(Guide)
        .exists()
    )

    guides = select(Guide, step_count.label("step_count")).where(
        or_(
            Guide.title.ilike(pattern, escape="\\"),
            Guide.summary.ilike(pattern, escape="\\"),
            Guide.introduction.ilike(pattern, escape="\\"),
            Guide.conclusion.ilike(pattern, escape="\\"),
            inside_a_step,
        )
    )
    pages = select(Page).where(
        or_(
            Page.title.ilike(pattern, escape="\\"),
            Page.summary.ilike(pattern, escape="\\"),
            Page.body.ilike(pattern, escape="\\"),
        )
    )

    if user.role == "viewer":
        guides = guides.where(Guide.status == READER_STATUS)
        pages = pages.where(Page.status == READER_STATUS)
    else:
        guides = guides.where(Guide.status != "archived")
        pages = pages.where(Page.status != "archived")

    # A title match is what the reader almost always meant. Without this the
    # ordering is "most recently edited", which puts the guide that merely
    # mentions the term in a bullet above the one named after it.
    guides = guides.order_by(
        case((Guide.title.ilike(pattern, escape="\\"), 0), else_=1),
        Guide.updated_at.desc(),
    ).limit(SEARCH_LIMIT)
    pages = pages.order_by(
        case((Page.title.ilike(pattern, escape="\\"), 0), else_=1),
        Page.updated_at.desc(),
    ).limit(SEARCH_LIMIT)

    hits: list[SearchHitOut] = [
        GuideHitOut(guide=guide_summary_out(guide, count)) for guide, count in db.execute(guides)
    ]
    hits.extend(PageHitOut(page=page_summary_out(page)) for page in db.scalars(pages))
    return hits
