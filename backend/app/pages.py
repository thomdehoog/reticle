"""Applying a whole wiki page in one write.

A page is Markdown, and the server deliberately does not interpret it: the
frontend renders it to React elements and ignores raw HTML, so there is nothing
here to sanitise and nothing to get wrong. Two things about a page are
structural all the same, and both are decided in this module — which category it
is the landing page of, and which uploads it shows.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import errors
from .models import ARCHIVED, Category, Media, Page, PageMedia, is_valid_id
from .schemas import PageDocumentIn

MEDIA_REFERENCE = re.compile(r"/api/media/([0-9A-Za-z]{26})(?![0-9A-Za-z])")
"""A media URL as it appears in a body, wherever it appears.

Matching the bare path rather than the full ``![alt](...)`` image syntax is on
purpose. A reference-style image, a link to a video and an image inside a table
cell all put the same path in the text, and missing one of them would publish a
page whose pictures 404 for exactly the readers it was published for.
"""


def referenced_media_ids(body: str) -> set[str]:
    return {match for match in MEDIA_REFERENCE.findall(body) if is_valid_id(match)}


def assert_landing_slot_free(db: DbSession, category_id: str, page_id: str | None) -> None:
    """A category has one landing page; a second is a conflict, not an overwrite."""
    statement = select(Page.id).where(
        Page.category_id == category_id, Page.is_landing.is_(True), Page.status != ARCHIVED
    )
    if page_id is not None:
        statement = statement.where(Page.id != page_id)
    if db.scalars(statement).first() is not None:
        raise errors.conflict(
            "That category already has a landing page. Edit that one, or archive it first."
        )


def validated_placement(db: DbSession, category_id: str | None, is_landing: bool, page_id: str | None) -> None:
    if category_id is not None and db.get(Category, category_id) is None:
        raise errors.validation_failed("That category does not exist.")
    if is_landing:
        if category_id is None:
            raise errors.validation_failed("A landing page has to belong to a category.")
        assert_landing_slot_free(db, category_id, page_id)


def validated_hero(db: DbSession, media_id: str | None) -> None:
    if media_id is None:
        return
    media = db.get(Media, media_id)
    if media is None:
        raise errors.validation_failed("That hero image does not exist.")
    if media.kind != "image":
        raise errors.validation_failed("The hero has to be an image, not a video.")


def sync_media_references(db: DbSession, page: Page) -> None:
    """Record which uploads the body points at.

    References to files that do not exist are skipped rather than refused. The
    body is prose: an author may be half-way through pasting a link, and a save
    that failed on it would lose the paragraph they were writing.
    """
    wanted = referenced_media_ids(page.body)
    known = set(db.scalars(select(Media.id).where(Media.id.in_(wanted)))) if wanted else set()

    for link in list(page.media_links):
        if link.media_id in known:
            known.discard(link.media_id)
        else:
            page.media_links.remove(link)
    for media_id in sorted(known):
        page.media_links.append(PageMedia(media_id=media_id))


def apply_document(db: DbSession, page: Page, payload: PageDocumentIn) -> None:
    validated_placement(db, payload.category_id, payload.is_landing, page.id)
    validated_hero(db, payload.hero_media_id)

    page.title = payload.title.strip()
    page.summary = payload.summary
    page.category_id = payload.category_id
    page.is_landing = payload.is_landing
    page.body = payload.body
    page.hero_media_id = payload.hero_media_id

    sync_media_references(db, page)


def assert_publishable(page: Page) -> None:
    if not page.title.strip():
        raise errors.validation_failed("Give the page a title before publishing it.")
    if not page.body.strip():
        raise errors.validation_failed("A page needs some content before it can be published.")
