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

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import errors
from .db import utcnow
from .models import (
    Bullet,
    Category,
    Guide,
    GuidePrerequisite,
    Media,
    Step,
    StepMedia,
    User,
    is_valid_id,
    new_id,
)
from .schemas import BulletIn, GuideDocumentIn, StepIn
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


def assert_not_stale(guide: Guide, client_seen: datetime) -> None:
    seen = client_seen if client_seen.tzinfo is not None else client_seen.replace(tzinfo=timezone.utc)
    if guide.updated_at > seen:
        raise errors.conflict(
            "This guide changed after you opened it. Reload to pick up the newer version before saving."
        )


def apply_document(db: DbSession, guide: Guide, payload: GuideDocumentIn, actor: User) -> None:
    settings = get_settings()

    assert_not_stale(guide, payload.updated_at)

    category = db.get(Category, payload.category_id)
    if category is None:
        raise errors.validation_failed("That category does not exist.")

    prerequisite_ids = _validated_prerequisites(db, guide, payload.prerequisite_ids)
    media_by_id = _validated_media(db, payload, settings.max_media_per_step)

    guide.title = payload.title.strip()
    guide.summary = payload.summary
    guide.category_id = category.id
    guide.difficulty = payload.difficulty
    guide.time_required_minutes = payload.time_required_minutes
    guide.introduction = payload.introduction
    guide.conclusion = payload.conclusion
    guide.last_edited_by_id = actor.id
    guide.updated_at = next_updated_at(guide.updated_at)

    _sync_prerequisites(db, guide, prerequisite_ids)
    _sync_steps(db, guide, payload.steps, media_by_id)


def _validated_prerequisites(db: DbSession, guide: Guide, requested: list[str]) -> list[str]:
    ordered: list[str] = []
    for candidate in requested:
        if candidate in ordered:
            continue
        if candidate == guide.id:
            raise errors.validation_failed("A guide cannot be its own prerequisite.")
        if not is_valid_id(candidate) or db.get(Guide, candidate) is None:
            raise errors.validation_failed("A prerequisite guide does not exist.")
        ordered.append(candidate)
    return ordered


def _validated_media(db: DbSession, payload: GuideDocumentIn, cap: int) -> dict[str, Media]:
    referenced: set[str] = set()
    for step in payload.steps:
        if len(step.media) > cap:
            raise errors.validation_failed(f"A step may hold at most {cap} images.")
        seen: set[str] = set()
        for item in step.media:
            if item.id in seen:
                raise errors.validation_failed("The same image is attached to a step twice.")
            seen.add(item.id)
            referenced.add(item.id)

    if not referenced:
        return {}

    found = db.scalars(select(Media).where(Media.id.in_(referenced))).all()
    media_by_id = {item.id: item for item in found}
    missing = referenced - media_by_id.keys()
    if missing:
        raise errors.validation_failed("One or more images referenced by this guide no longer exist.")
    return media_by_id


def _sync_prerequisites(db: DbSession, guide: Guide, prerequisite_ids: list[str]) -> None:
    for link in list(guide.prerequisites):
        db.delete(link)
    db.flush()
    for index, prerequisite_id in enumerate(prerequisite_ids):
        db.add(GuidePrerequisite(guide_id=guide.id, prerequisite_id=prerequisite_id, order_index=index))


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


def _sync_steps(db: DbSession, guide: Guide, steps_in: list[StepIn], media_by_id: dict[str, Media]) -> None:
    existing_steps = {step.id: step for step in guide.steps}

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
            media = media_by_id[item.id]
            media.alt = item.alt
            db.add(StepMedia(step_id=step.id, media_id=media.id, order_index=position))
