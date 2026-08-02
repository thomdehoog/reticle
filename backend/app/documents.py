"""Saving a whole guide, or a whole wiki page, in one write.

The editor does not save a step or a bullet; it sends the entire guide back
every few seconds and this module makes the database match it. That is why there
is no endpoint for "add a bullet" or "move step 3 above step 2" — reordering is
an array move in the browser — and it is why **this file is the only thing
standing between the editor and the database**. Everything a saved guide is
allowed to be is decided here: which files it may show, which tags, whether the
copy being saved is still current.

Two rules run through the implementation.

*Identifiers the browser invented are kept.* The editor gives a new step an id
immediately so it can draw it, and honouring that id means the browser does not
have to go back and renumber everything after each save.

*Every deletion is written out before any insertion.* This one is not obvious
and it is the reason ``_sync_steps`` is shaped the way it is. SQLAlchemy batches
the changes and decides their order itself, and left alone it will happily try
to insert a row before deleting the one holding that id — so a save that merely
rewrites a step fails on a duplicate key. Forcing the deletes out first (a
``flush``) removes the choice.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import errors
from .db import utcnow
from .models import (
    Annotation,
    Bullet,
    Category,
    Guide,
    GuideContributor,
    GuideTag,
    Media,
    Page,
    PageContributor,
    Step,
    StepMedia,
    Tag,
    User,
    is_valid_id,
    new_id,
)
from .schemas import (
    TAG_SLUG_PATTERN,
    BulletIn,
    GuideDocumentIn,
    MediaRefIn,
    PageDocumentIn,
    StepIn,
)
from .settings import get_settings


def next_updated_at(previous: datetime) -> datetime:
    """Guarantee a strictly increasing ``updatedAt``.

    The concurrency token is the timestamp itself, so two saves landing inside
    one tick of the system clock must not compare equal; if they did, the second
    author's stale copy would be accepted as current.
    """
    now = utcnow()
    floor = previous + timedelta(microseconds=1)
    return max(now, floor)


def assert_not_stale(record: Guide | Page, client_seen: datetime, noun: str = "guide") -> None:
    seen = client_seen if client_seen.tzinfo is not None else client_seen.replace(tzinfo=UTC)
    if record.updated_at > seen:
        raise errors.conflict(
            f"This {noun} changed after you opened it. "
            "Reload to pick up the newer version before saving."
        )


def apply_document(db: DbSession, guide: Guide, payload: GuideDocumentIn, actor: User) -> None:
    settings = get_settings()

    assert_not_stale(guide, payload.updated_at)

    category = db.get(Category, payload.category_id)
    if category is None:
        raise errors.validation_failed("That category does not exist.")

    tag_slugs = _validated_tags(payload.tags)
    media_by_id = _validated_media(db, guide, payload, settings.max_media_per_step)
    minimum, maximum = _validated_time_range(
        payload.time_required_min_minutes, payload.time_required_max_minutes
    )

    guide.title = payload.title.strip()
    guide.summary = payload.summary
    guide.category_id = category.id
    guide.difficulty = payload.difficulty
    guide.time_required_min_minutes = minimum
    guide.time_required_max_minutes = maximum
    guide.introduction = payload.introduction
    guide.conclusion = payload.conclusion
    guide.is_quick_link = payload.is_quick_link
    guide.last_edited_by_id = actor.id
    guide.updated_at = next_updated_at(guide.updated_at)

    _sync_tags(db, guide, tag_slugs)
    _sync_steps(db, guide, payload.steps, media_by_id)
    record_contribution(db, guide, actor)


def apply_page_document(db: DbSession, page: Page, payload: PageDocumentIn, actor: User) -> None:
    """The wiki half of the same whole-document write.

    A page is one Markdown body rather than a tree of steps, so this is short —
    but it goes through the same staleness check, the same contributor ledger
    and the same landing-page rule as everything else, because a wiki page at
    ZMB *is* a category landing and is edited by the same people.
    """
    assert_not_stale(page, payload.updated_at, noun="page")

    category_id: str | None = None
    if payload.category_id is not None:
        category = db.get(Category, payload.category_id)
        if category is None:
            raise errors.validation_failed("That category does not exist.")
        category_id = category.id

    if payload.is_landing and category_id is None:
        raise errors.validation_failed("A landing page has to belong to a category.")

    if payload.is_landing:
        _assert_landing_is_free(db, category_id, page.id)

    if payload.hero_media_id is not None:
        if not is_valid_id(payload.hero_media_id) or db.get(Media, payload.hero_media_id) is None:
            raise errors.validation_failed("That hero image no longer exists.")

    page.title = payload.title.strip()
    page.summary = payload.summary
    page.category_id = category_id
    page.is_landing = payload.is_landing
    page.body = payload.body
    page.hero_media_id = payload.hero_media_id
    page.last_edited_by_id = actor.id
    page.updated_at = next_updated_at(page.updated_at)

    record_contribution(db, page, actor)


def _assert_landing_is_free(db: DbSession, category_id: str | None, page_id: str) -> None:
    clash = db.scalars(
        select(Page).where(
            Page.category_id == category_id,
            Page.is_landing.is_(True),
            Page.id != page_id,
        )
    ).first()
    if clash is not None:
        raise errors.conflict("That category already has a landing page.")


def record_contribution(db: DbSession, record: Guide | Page, actor: User) -> None:
    """Credit whoever saved it, once, in the order they first appeared.

    Kept as data rather than derived from the audit log: the audit log is
    rotated, and at a facility the edit history is frequently the only surviving
    answer to "why does this procedure say that, and who do I ask about it".
    """
    link_model = GuideContributor if isinstance(record, Guide) else PageContributor
    now = utcnow()
    for link in record.contributor_links:
        if link.user_id == actor.id:
            link.last_edited_at = now
            return
    owner_column = "guide_id" if isinstance(record, Guide) else "page_id"
    db.add(
        link_model(
            **{owner_column: record.id},
            user_id=actor.id,
            first_edited_at=now,
            last_edited_at=now,
        )
    )


def _validated_time_range(
    minimum: int | None, maximum: int | None
) -> tuple[int | None, int | None]:
    """A range, not two independent numbers.

    ZMB writes estimates as "30 – 90 min" because that is how long a procedure
    honestly takes. A reversed pair is refused rather than quietly swapped: the
    author meant one of the two numbers to be something else, and guessing which
    would publish a time nobody wrote.
    """
    if minimum is not None and maximum is not None and minimum > maximum:
        raise errors.validation_failed("The shortest time cannot be longer than the longest time.")
    return minimum, maximum


def _validated_tags(requested: list[str]) -> list[str]:
    """Keep the author's order, drop repeats, refuse anything not already a slug.

    The tag input slugifies as you type, so a value arriving here in another
    shape is a client that has drifted from the contract. Re-slugifying it
    server-side would be worse than refusing: two spellings would agree in the
    editor and disagree in the database, which is exactly how ZMB's live site
    ended up with four spellings of one instrument.
    """
    ordered: list[str] = []
    for candidate in requested:
        slug = candidate.strip()
        if slug == "" or slug in ordered:
            continue
        if not re.fullmatch(TAG_SLUG_PATTERN, slug) or len(slug) > 120:
            raise errors.validation_failed(
                f"“{candidate}” is not a usable tag. Use lower-case words joined by hyphens."
            )
        ordered.append(slug)
    return ordered


def _sync_tags(db: DbSession, guide: Guide, slugs: list[str]) -> None:
    """Attach the guide to each tag, minting any tag that does not exist yet.

    Authors are not administrators of a taxonomy; making them create a tag
    before they can use it is how a corpus ends up with none. The input suggests
    existing tags first, which keeps the vocabulary tidy without a gate.
    """
    for link in list(guide.tag_links):
        db.delete(link)
    db.flush()

    if not slugs:
        return

    known = {tag.slug: tag for tag in db.scalars(select(Tag).where(Tag.slug.in_(slugs))).all()}
    for index, slug in enumerate(slugs):
        tag = known.get(slug)
        if tag is None:
            tag = Tag(slug=slug, name=slug.replace("-", " "))
            db.add(tag)
            db.flush()
            known[slug] = tag
        db.add(GuideTag(guide_id=guide.id, tag_id=tag.id, order_index=index))


def _validated_media(
    db: DbSession, guide: Guide, payload: GuideDocumentIn, cap: int
) -> dict[str, Media]:
    """Resolve every file the document references, and refuse the impossible ones.

    Three things are refused here, and the second and third are the ones with
    teeth.

    A video dropped into an image slot renders as a broken picture and an image
    in the video slot as a player that never starts. Both are silent until a
    reader opens the step.

    **One file may appear once in the whole guide**, not once per step. The
    shapes drawn on a picture and the alt text hang off the ``Media`` row, so
    two steps showing the same file cannot hold different shapes for it — the
    save would write one step's shapes and then overwrite them with the next's,
    and only the last would survive.

    **A file another guide displays is refused outright**, for the same reason
    across a wider gap. Saving would replace that guide's shapes and its alt
    text without touching its ``updated_at``, so its author gets no conflict and
    no warning; the overlay simply disappears from a procedure they are not
    editing. Duplicating the upload is cheap and is what the editor does.
    """
    image_ids: set[str] = set()
    video_ids: set[str] = set()
    for step in payload.steps:
        if len(step.media) > cap:
            raise errors.validation_failed(f"A step may hold at most {cap} images.")
        for item in step.media:
            _claim_file(item.id, image_ids, video_ids)
            image_ids.add(item.id)
        if step.video is not None:
            _claim_file(step.video.id, image_ids, video_ids)
            video_ids.add(step.video.id)

    referenced = image_ids | video_ids
    if not referenced:
        return {}

    found = db.scalars(select(Media).where(Media.id.in_(referenced))).all()
    media_by_id = {item.id: item for item in found}
    if referenced - media_by_id.keys():
        raise errors.validation_failed(
            "One or more files referenced by this guide no longer exist."
        )

    for media_id, media in media_by_id.items():
        wanted = "video" if media_id in video_ids else "image"
        if media.kind != wanted:
            raise errors.validation_failed(
                "The file in a step's video slot is not a video."
                if wanted == "video"
                else "A video cannot be used as one of a step's images."
            )

    if _displayed_by_another_guide(db, guide.id, referenced):
        raise errors.validation_failed(
            "One of these files is already part of another guide. Upload it again here, so each "
            "guide keeps its own shapes and its own alt text."
        )
    return media_by_id


def _claim_file(media_id: str, image_ids: set[str], video_ids: set[str]) -> None:
    if media_id in image_ids or media_id in video_ids:
        raise errors.validation_failed(
            "The same file appears twice in this guide. Upload a second copy to show it in more "
            "than one place."
        )


def _displayed_by_another_guide(db: DbSession, guide_id: str, referenced: set[str]) -> bool:
    """Both ways a step can show a file: the image strip and the video slot."""
    as_an_image = db.scalars(
        select(StepMedia.media_id)
        .join(Step, Step.id == StepMedia.step_id)
        .where(StepMedia.media_id.in_(referenced), Step.guide_id != guide_id)
    ).first()
    if as_an_image is not None:
        return True
    as_a_video = db.scalars(
        select(Step.video_media_id).where(
            Step.video_media_id.in_(referenced), Step.guide_id != guide_id
        )
    ).first()
    return as_a_video is not None


def _sync_annotations(db: DbSession, media: Media, item: MediaRefIn) -> None:
    """Replace an image's shapes with the set the editor is holding.

    Annotations are stored as fractions of the image rather than burned into the
    pixels, so the upload stays untouched, the shape stays editable and it
    scales with whatever size the reader's screen renders it at. The colour is
    the bullet's colour: that pairing is the whole point — a red shape on the
    picture and the red bullet beside it are one instruction.
    """
    for annotation in list(media.annotations):
        db.delete(annotation)
    db.flush()
    for index, spec in enumerate(item.annotations):
        db.add(
            Annotation(
                id=spec.id if spec.id is not None and is_valid_id(spec.id) else new_id(),
                media_id=media.id,
                order_index=index,
                shape=spec.shape,
                color=spec.color,
                x=spec.x,
                y=spec.y,
                width=spec.width,
                height=spec.height,
            )
        )


def _claim_id(
    db: DbSession, model: type, candidate: str | None, owned: set[str], label: str
) -> str:
    """Resolve a client-supplied identifier, or mint one.

    An identifier the client already owns is reused; an unknown one is accepted
    so an optimistically created row keeps its key; one that belongs to a
    different parent is refused, because honouring it would silently move
    another guide's content.
    """
    if candidate is None:
        return new_id()
    if not is_valid_id(candidate):
        raise errors.validation_failed(f"{label} identifiers must be ULIDs.")
    if candidate in owned:
        return candidate
    if db.get(model, candidate) is not None:
        raise errors.validation_failed(
            f"That {label} identifier already belongs to something else."
        )
    return candidate


def _pinned_first(steps_in: list[StepIn]) -> list[StepIn]:
    """Move the pinned blocks to the front, keeping everything else in order.

    A pinned block is the thing a reader must see before starting - "this room
    is shared, knock first" - so where it sits in the document is not the
    author's decision to get wrong. Enforcing it here rather than trusting the
    editor to send them first means it also holds for an import, a restore and
    anything else that writes a whole document.

    Sorting on the kind alone would be enough, but ``sorted`` is stable, so the
    author's order survives within each group.
    """
    return sorted(steps_in, key=lambda step: 0 if step.kind == "pinned" else 1)


def _sync_steps(
    db: DbSession, guide: Guide, steps_in: list[StepIn], media_by_id: dict[str, Media]
) -> None:
    """Make the guide's steps, bullets and pictures match the document exactly.

    Four passes, and the split is not tidiness — it is the rule in this module's
    header. The whole plan is worked out first, then every deletion is issued
    and flushed, and only then is anything written. Interleaving them lets the
    unit of work order an insert ahead of the delete that frees its primary key,
    and the save fails on a duplicate key for a row the author is replacing with
    itself.
    """
    existing_steps = {step.id: step for step in guide.steps}
    steps_in = _pinned_first(steps_in)

    # Pass 1: settle which identifier every step and bullet will have, before
    # anything is written, so a clash is a readable error rather than a
    # half-applied save.
    plan: list[tuple[str, StepIn]] = []
    claimed: set[str] = set()
    for step_in in steps_in:
        step_id = _claim_id(db, Step, step_in.id, set(existing_steps), "step")
        if step_id in claimed:
            raise errors.validation_failed("The same step appears twice in this guide.")
        claimed.add(step_id)
        plan.append((step_id, step_in))

    bullet_plan: dict[str, list[tuple[str, BulletIn]]] = {}
    for step_id, step_in in plan:
        step = existing_steps.get(step_id)
        owned_bullets = {bullet.id for bullet in step.bullets} if step is not None else set()
        entries: list[tuple[str, BulletIn]] = []
        seen: set[str] = set()
        for bullet_in in step_in.bullets:
            bullet_id = _claim_id(db, Bullet, bullet_in.id, owned_bullets, "bullet")
            if bullet_id in seen:
                raise errors.validation_failed("The same bullet appears twice in a step.")
            seen.add(bullet_id)
            entries.append((bullet_id, bullet_in))
        bullet_plan[step_id] = entries

    # Pass 2: every deletion, and nothing else. Steps the document dropped,
    # bullets it dropped, and all of the picture links — the links are rebuilt
    # from scratch below because their order is part of what changed.
    for step_id, step in existing_steps.items():
        if step_id not in claimed:
            db.delete(step)

    for step_id, _ in plan:
        step = existing_steps.get(step_id)
        if step is None:
            continue
        keep = {bullet_id for bullet_id, _ in bullet_plan[step_id]}
        for bullet in list(step.bullets):
            if bullet.id not in keep:
                db.delete(bullet)
        for link in list(step.media_links):
            db.delete(link)

    # Pass 3: the flush that makes those deletions real in the database, so the
    # keys they held are free before pass 4 asks for them again.
    db.flush()

    # Pass 4: write the document.
    for index, (step_id, step_in) in enumerate(plan):
        step = existing_steps.get(step_id)
        if step is None:
            step = Step(id=step_id, guide_id=guide.id)
            db.add(step)
        step.order_index = index
        step.kind = step_in.kind
        step.title = step_in.title

        existing_bullets = (
            {bullet.id: bullet for bullet in step.bullets} if step_id in existing_steps else {}
        )
        for position, (bullet_id, bullet_in) in enumerate(bullet_plan[step_id]):
            bullet = existing_bullets.get(bullet_id)
            if bullet is None:
                bullet = Bullet(id=bullet_id, step_id=step.id)
                db.add(bullet)
            bullet.order_index = position
            bullet.text = bullet_in.text
            bullet.color = bullet_in.color
            bullet.icon = bullet_in.icon
            bullet.level = bullet_in.level

        for position, item in enumerate(step_in.media):
            media = media_by_id[item.id]
            media.alt = item.alt
            _sync_annotations(db, media, item)
            db.add(StepMedia(step_id=step.id, media_id=media.id, order_index=position))

        if step_in.video is None:
            step.video_media_id = None
        else:
            video = media_by_id[step_in.video.id]
            video.alt = step_in.video.alt
            step.video_media_id = video.id
