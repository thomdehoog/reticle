"""Applying a whole guide document in one write.

The editor holds the guide as one object and autosaves it as one object. That
choice is what removes a per-field endpoint zoo and makes reordering a plain
array move on the client, but it puts the entire burden of integrity here: this
module is the only place that decides what a saved guide may look like.

Two rules drive the implementation. Identifiers the client minted are honoured
so an optimistic UI does not have to reconcile keys after every save, and every
deletion is flushed before any insertion, because the unit of work would
otherwise order an insert ahead of the delete that frees its primary key.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from . import errors
from .models import Bullet, Category, Guide, Media, Step, StepMedia, Tag, is_valid_id, new_id
from .schemas import AnnotationIn, BulletIn, GuideDocumentIn, StepIn
from .settings import get_settings
from .slugs import tag_slug


def apply_document(db: DbSession, guide: Guide, payload: GuideDocumentIn) -> None:
    """Write the document onto the guide.

    The references a document makes — its category, its media, its tags — are
    resolved before the first attribute is assigned, and nothing is committed
    here: a document refused part-way is discarded with the session.
    """
    settings = get_settings()

    category = db.get(Category, payload.category_id)
    if category is None:
        raise errors.validation_failed("That category does not exist.")

    media_by_id = _validated_media(db, payload, settings.max_media_per_step)
    tags = resolve_tags(db, normalised_tags(payload.tags))

    guide.title = payload.title.strip()
    guide.summary = payload.summary
    guide.category_id = category.id
    guide.difficulty = payload.difficulty
    guide.time_required_min_minutes = payload.time_required_min_minutes
    guide.time_required_max_minutes = payload.time_required_max_minutes
    guide.introduction = payload.introduction
    guide.conclusion = payload.conclusion
    guide.tags = tags

    _sync_steps(db, guide, payload.steps, media_by_id)


def normalised_tags(raw: list[str]) -> dict[str, str]:
    """Map each tag's slug to the spelling it arrived with, dropping repeats.

    A tag with no letter or digit in it has no slug, so it could never be
    linked to, listed or asked for by a wiki page; it is refused rather than
    quietly discarded, because the author typed it expecting it to work.
    """
    tags: dict[str, str] = {}
    for entry in raw:
        name = entry.strip()
        slug = tag_slug(name)
        if not slug:
            raise errors.validation_failed("A tag needs at least one letter or digit.")
        tags.setdefault(slug, name)
    return tags


def resolve_tags(db: DbSession, tags: dict[str, str]) -> list[Tag]:
    """Fetch the tags that exist and create the ones that do not.

    The first spelling seen becomes the display name and is never overwritten,
    which is what stops "LAS X" drifting to "las x" because one author was in a
    hurry. Creation runs inside a savepoint: with two workers, two guides can
    introduce the same tag in the same instant, and the loser of that race
    should pick up the winner's row rather than fail the whole save.
    """
    if not tags:
        return []
    existing = {tag.slug: tag for tag in db.scalars(select(Tag).where(Tag.slug.in_(tags)))}
    resolved: list[Tag] = []
    for slug, name in tags.items():
        tag = existing.get(slug)
        if tag is None:
            tag = _create_tag(db, slug, name)
        resolved.append(tag)
    return resolved


def _create_tag(db: DbSession, slug: str, name: str) -> Tag:
    tag = Tag(slug=slug, name=name)
    try:
        with db.begin_nested():
            db.add(tag)
            db.flush()
    except IntegrityError:
        return db.scalars(select(Tag).where(Tag.slug == slug)).one()
    return tag


def assert_publishable(guide: Guide) -> None:
    """What a guide must have before readers may be shown it.

    The message names the step, by number and by title, because "a step is
    empty" sends an author hunting through forty of them.
    """
    if not guide.title.strip():
        raise errors.validation_failed("Give the guide a title before publishing it.")
    if not guide.steps:
        raise errors.validation_failed("A guide needs at least one step before it can be published.")
    for number, step in enumerate(guide.steps, start=1):
        has_text = any(bullet.text.strip() for bullet in step.bullets)
        if not has_text and not step.media_links:
            title = step.title.strip()
            label = f'Step {number} ("{title}")' if title else f"Step {number}"
            raise errors.validation_failed(
                f"{label} has neither text nor an image. Add a bullet or a picture, or delete the step."
            )


def _validated_media(db: DbSession, payload: GuideDocumentIn, cap: int) -> dict[str, Media]:
    referenced: set[str] = set()
    for step in payload.steps:
        if len(step.media) > cap:
            raise errors.validation_failed(f"A step may hold at most {cap} images or videos.")
        seen: set[str] = set()
        for item in step.media:
            if item.id in seen:
                raise errors.validation_failed("The same file is attached to a step twice.")
            seen.add(item.id)
            referenced.add(item.id)

    if not referenced:
        return {}

    found = db.scalars(select(Media).where(Media.id.in_(referenced))).all()
    media_by_id = {item.id: item for item in found}
    missing = referenced - media_by_id.keys()
    if missing:
        raise errors.validation_failed("One or more images referenced by this guide no longer exist.")

    for step in payload.steps:
        for item in step.media:
            if item.annotations and media_by_id[item.id].kind != "image":
                raise errors.validation_failed("A video cannot carry annotations.")
    return media_by_id


def _stored_annotations(annotations: list[AnnotationIn], claimed: set[str]) -> list[dict]:
    """The annotations as they are kept on the step-media link.

    Identifiers the client minted are kept so a shape stays selected across an
    autosave. They are held unique across the whole guide, like step and bullet
    identifiers: the editor keys its selection by them, and two shapes answering
    to one identifier on different images would be selected, moved and deleted
    together.
    """
    stored: list[dict] = []
    for annotation in annotations:
        annotation_id = _claim_once(
            claimed, annotation.id or new_id(), "The same annotation appears twice in this guide."
        )
        stored.append(
            {
                "id": annotation_id,
                "shape": annotation.shape,
                "color": annotation.color,
                "x": annotation.x,
                "y": annotation.y,
                "width": annotation.width,
                "height": annotation.height,
            }
        )
    return stored


def _claim_id(db: DbSession, model: type, candidate: str | None, owned: set[str], label: str) -> str:
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
        raise errors.validation_failed(f"That {label} identifier already belongs to something else.")
    return candidate


def _claim_once(claimed: set[str], identifier: str, message: str) -> str:
    """Refuse an identifier that this same document has already used.

    The set is the whole document's, not one step's. A primary key is unique
    across the table, so the same new bullet identifier in two different steps
    passed a per-step check and then died on the insert — as a 500 whose
    traceback carried the bullet text into the log.
    """
    if identifier in claimed:
        raise errors.validation_failed(message)
    claimed.add(identifier)
    return identifier


def _sync_steps(db: DbSession, guide: Guide, steps_in: list[StepIn], media_by_id: dict[str, Media]) -> None:
    existing_steps = {step.id: step for step in guide.steps}

    plan: list[tuple[str, StepIn]] = []
    claimed: set[str] = set()
    for step_in in steps_in:
        step_id = _claim_id(db, Step, step_in.id, set(existing_steps), "step")
        plan.append((_claim_once(claimed, step_id, "The same step appears twice in this guide."), step_in))

    bullet_plan: dict[str, list[tuple[str, BulletIn]]] = {}
    claimed_bullets: set[str] = set()
    for step_id, step_in in plan:
        step = existing_steps.get(step_id)
        owned_bullets = {bullet.id for bullet in step.bullets} if step is not None else set()
        entries: list[tuple[str, BulletIn]] = []
        for bullet_in in step_in.bullets:
            bullet_id = _claim_id(db, Bullet, bullet_in.id, owned_bullets, "bullet")
            _claim_once(claimed_bullets, bullet_id, "The same bullet appears twice in this guide.")
            entries.append((bullet_id, bullet_in))
        bullet_plan[step_id] = entries

    annotation_plan: dict[tuple[str, int], list[dict]] = {}
    claimed_annotations: set[str] = set()
    for step_id, step_in in plan:
        for position, item in enumerate(step_in.media):
            annotation_plan[step_id, position] = _stored_annotations(item.annotations, claimed_annotations)

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

    db.flush()

    for index, (step_id, step_in) in enumerate(plan):
        step = existing_steps.get(step_id)
        if step is None:
            step = Step(id=step_id, guide_id=guide.id)
            db.add(step)
        step.order_index = index
        step.title = step_in.title

        existing_bullets = {bullet.id: bullet for bullet in step.bullets} if step_id in existing_steps else {}
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
            db.add(
                StepMedia(
                    step_id=step.id,
                    media_id=media_by_id[item.id].id,
                    order_index=position,
                    alt=item.alt,
                    annotations=annotation_plan[step_id, position],
                )
            )
