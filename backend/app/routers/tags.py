"""Tags: the navigation.

There is only a listing. A tag comes into existence when a guide is saved with
it and drops out of this listing when the last guide lets go of it, so there is
nothing to create, rename or delete here and no way for the tag list and the
guides to disagree.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from .. import content
from ..auth import AnyUser, DbDep
from ..models import Guide, GuideTag, Tag
from ..schemas import TagOut

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=list[TagOut])
def list_tags(db: DbDep, user: AnyUser) -> list[TagOut]:
    """Every tag the caller can reach a guide through, with how many.

    The count applies the visibility rule inside the join. Counting first and
    hiding afterwards would tell a viewer that three guides carry a tag while
    showing them one, which discloses the two drafts as surely as listing them.
    """
    guide_count = func.count(Guide.id)
    statement = (
        select(Tag, guide_count)
        .join(GuideTag, GuideTag.tag_id == Tag.id)
        .join(Guide, Guide.id == GuideTag.guide_id)
        .where(content.visible_to(Guide, user))
        .group_by(Tag.id)
        .order_by(func.lower(Tag.name), Tag.slug)
    )
    return [
        TagOut(id=tag.id, slug=tag.slug, name=tag.name, guide_count=count)
        for tag, count in db.execute(statement)
    ]
