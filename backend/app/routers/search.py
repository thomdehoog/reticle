"""Search across guides and wiki pages.

One endpoint, because a reader looking for "Stellaris" does not know or care
whether the answer is a procedure or an article. It is plain substring matching
in SQL: the whole corpus is a few hundred documents, and a search engine to
operate would cost the facility more than it would ever return.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import case, or_, select

from .. import content
from ..auth import AnyUser, DbDep
from ..models import Guide, Page
from ..schemas import (
    MAX_SEARCH_TERM_CHARS,
    GuideResultOut,
    PageResultOut,
    SearchResultOut,
    guide_summary_out,
    page_summary_out,
)
from .guides import has_step_text_like, has_tag_like, summary_statement

router = APIRouter(prefix="/api/search", tags=["search"])

MAX_RESULTS = 50

TITLE_MATCH = 0
BODY_MATCH = 1


@router.get("", response_model=list[SearchResultOut])
def search(
    db: DbDep,
    user: AnyUser,
    q: str = Query(default="", max_length=MAX_SEARCH_TERM_CHARS),
) -> list[SearchResultOut]:
    """Guides and pages matching the term, title matches first.

    Each content type is ranked and cut to the limit in SQL, then the two short
    lists are merged, so the work stays bounded however much matches. Within a
    rank the most recently updated comes first, on the reasoning that of two
    equally relevant procedures the maintained one is the one to read.
    """
    term = q.strip()
    if not term:
        return []

    guide_rank = case((content.contains(Guide.title, term), TITLE_MATCH), else_=BODY_MATCH).label("rank")
    guides = db.execute(
        summary_statement()
        .add_columns(guide_rank)
        .where(
            content.visible_to(Guide, user),
            or_(
                content.contains(Guide.title, term),
                content.contains(Guide.summary, term),
                has_tag_like(term),
                has_step_text_like(term),
            ),
        )
        .order_by(guide_rank, Guide.updated_at.desc(), Guide.id.desc())
        .limit(MAX_RESULTS)
    ).all()

    page_rank = case((content.contains(Page.title, term), TITLE_MATCH), else_=BODY_MATCH).label("rank")
    pages = db.execute(
        select(Page, page_rank)
        .where(
            content.visible_to(Page, user),
            or_(
                content.contains(Page.title, term),
                content.contains(Page.summary, term),
                content.contains(Page.body, term),
            ),
        )
        .order_by(page_rank, Page.updated_at.desc(), Page.id.desc())
        .limit(MAX_RESULTS)
    ).all()

    ranked: list[tuple[int, float, SearchResultOut]] = []
    for guide, step_count, rank in guides:
        ranked.append(
            (rank, -guide.updated_at.timestamp(), GuideResultOut(guide=guide_summary_out(guide, step_count)))
        )
    for page, rank in pages:
        ranked.append((rank, -page.updated_at.timestamp(), PageResultOut(page=page_summary_out(page))))

    ranked.sort(key=lambda entry: (entry[0], entry[1]))
    return [result for _, _, result in ranked[:MAX_RESULTS]]
