"""Search across guides and wiki pages.

One endpoint, because a reader looking for "Stellaris" does not know or care
whether the answer is a procedure or an article. It is plain substring matching
in SQL: the whole corpus is a few hundred documents, and a search engine to
operate would cost the facility more than it would ever return.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import Select, case, func, or_, select

from .. import content, published
from ..auth import AnyUser, DbDep
from ..models import Guide, Page, PublishedPage
from ..schemas import (
    MAX_SEARCH_TERM_CHARS,
    GuideResultOut,
    PageResultOut,
    SearchResultOut,
    page_summary_out,
)
from .guides import GuideSide, summaries
from .pages import PAGES

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

    What is searched is what the caller would be shown. A viewer's term is
    matched against the published snapshots only — their titles, tags, step text
    and page bodies as last published — so a sentence in an unpublished edit can
    neither be found nor, by being found, be confirmed to exist. An author's is
    matched against the working copies, like the author's listings.
    """
    term = q.strip()
    if not term:
        return []

    def ranked_guides(statement: Select, side: GuideSide) -> Select:
        rank = case((content.contains(side.title, term), TITLE_MATCH), else_=BODY_MATCH).label("rank")
        return (
            statement.add_columns(rank)
            .where(side.matches_search(term))
            .order_by(rank, side.updated_at.desc(), Guide.id.desc())
            .limit(MAX_RESULTS)
        )

    ranked: list[tuple[int, float, SearchResultOut]] = []
    for _, summary, rank in summaries(db, user, ranked_guides):
        ranked.append((rank, -summary.updated_at.timestamp(), GuideResultOut(guide=summary)))

    as_published = content.serves_published(user)
    side = PublishedPage if as_published else Page
    page_updated_at = func.coalesce(Page.snapshot_updated_at, Page.updated_at) if as_published else Page.updated_at
    page_rank = case((content.contains(side.title, term), TITLE_MATCH), else_=BODY_MATCH).label("rank")
    pages = (
        content.published_statement(PAGES, page_rank)
        if as_published
        else select(Page, page_rank).where(content.visible_to(Page, user))
    )
    pages = (
        pages.where(
            or_(
                content.contains(side.title, term),
                content.contains(side.summary, term),
                content.contains(side.body, term),
            )
        )
        .order_by(page_rank, page_updated_at.desc(), Page.id.desc())
        .limit(MAX_RESULTS)
    )
    for row in db.execute(pages):
        summary = published.page_summary(row[0], row[1]) if as_published else page_summary_out(row[0])
        ranked.append((row[-1], -summary.updated_at.timestamp(), PageResultOut(page=summary)))

    ranked.sort(key=lambda entry: (entry[0], entry[1]))
    return [result for _, _, result in ranked[:MAX_RESULTS]]
