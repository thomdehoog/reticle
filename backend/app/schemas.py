"""The wire format: camelCase in, camelCase out.

The backend owns the translation between snake_case columns and the camelCase
contract so the frontend never adapts. Timestamps are serialised at a fixed
microsecond precision rather than pydantic's variable-width default, because
``updatedAt`` doubles as the optimistic-concurrency token and a token whose
textual form depends on whether the microsecond happened to be zero is a token
that sorts wrongly and round-trips inconsistently.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, PlainSerializer
from pydantic.alias_generators import to_camel

from . import models

Role = Literal["viewer", "author", "admin"]
GuideStatus = Literal["draft", "in_review", "published", "archived"]
Difficulty = Literal["very_easy", "easy", "moderate", "difficult", "very_difficult"]
BulletColor = Literal["black", "red", "orange", "yellow", "green", "blue", "violet"]
BulletIcon = Literal["note", "caution", "warning", "reminder"]
BulletLevel = Literal[0, 1, 2]


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


Instant = Annotated[datetime, PlainSerializer(iso_utc, return_type=str, when_used="json")]


class Wire(BaseModel):
    """Base for everything crossing the boundary in either direction."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class Document(Wire):
    """Base for request bodies that the client round-trips.

    The editor sends back the whole guide object it was given, read-only fields
    included, so unknown and server-owned keys are ignored rather than refused.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="ignore",
    )


class UserRefOut(Wire):
    id: str
    display_name: str


class UserOut(Wire):
    id: str
    email: str
    display_name: str
    role: Role
    created_at: Instant


class CategoryOut(Wire):
    id: str
    slug: str
    name: str
    description: str
    parent_id: str | None
    order_index: int


class MediaOut(Wire):
    id: str
    url: str
    alt: str
    width: int | None
    height: int | None


class BulletOut(Wire):
    id: str
    text: str
    color: BulletColor
    icon: BulletIcon | None
    level: BulletLevel


class StepOut(Wire):
    id: str
    order_index: int
    title: str
    bullets: list[BulletOut]
    media: list[MediaOut]


class GuideOut(Wire):
    id: str
    slug: str
    title: str
    summary: str
    category_id: str
    difficulty: Difficulty
    time_required_minutes: int | None
    introduction: str
    conclusion: str
    status: GuideStatus
    steps: list[StepOut]
    prerequisite_ids: list[str]
    author: UserRefOut
    last_edited_by: UserRefOut
    created_at: Instant
    updated_at: Instant
    published_at: Instant | None
    version: int


class GuideSummaryOut(Wire):
    id: str
    slug: str
    title: str
    summary: str
    category_id: str
    difficulty: Difficulty
    time_required_minutes: int | None
    status: GuideStatus
    step_count: int
    author: UserRefOut
    updated_at: Instant
    published_at: Instant | None


class RevisionSummaryOut(Wire):
    version: int
    published_at: Instant
    published_by: UserRefOut


class LoginIn(Wire):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class CategoryCreateIn(Wire):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    parent_id: str | None = None


class CategoryPatchIn(Wire):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    parent_id: str | None = None
    order_index: int | None = Field(default=None, ge=0)


class GuideCreateIn(Wire):
    title: str = Field(min_length=1, max_length=240)
    category_id: str


class BulletIn(Document):
    id: str | None = None
    text: str = Field(default="", max_length=4000)
    color: BulletColor = "black"
    icon: BulletIcon | None = None
    level: BulletLevel = 0


class MediaRefIn(Document):
    id: str
    alt: str = Field(default="", max_length=1000)


class StepIn(Document):
    id: str | None = None
    title: str = Field(default="", max_length=400)
    bullets: list[BulletIn] = Field(default_factory=list)
    media: list[MediaRefIn] = Field(default_factory=list)


class GuideDocumentIn(Document):
    """The whole guide, as the editor holds it.

    ``updated_at`` is mandatory: defaulting it would turn the concurrency guard
    into an opt-in, and the one client that forgot to send it would silently
    overwrite everyone else's work.
    """

    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(default="", max_length=4000)
    category_id: str
    difficulty: Difficulty = "moderate"
    time_required_minutes: int | None = Field(default=None, ge=0, le=100_000)
    introduction: str = Field(default="", max_length=20_000)
    conclusion: str = Field(default="", max_length=20_000)
    prerequisite_ids: list[str] = Field(default_factory=list)
    steps: list[StepIn] = Field(default_factory=list)
    updated_at: datetime


class UserCreateIn(Wire):
    email: EmailStr
    display_name: str | None = Field(default=None, max_length=200)
    role: Role = "viewer"
    password: str = Field(min_length=1, max_length=1024)


class UserPatchIn(Wire):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None
    is_active: bool | None = None


class PasswordChangeIn(Wire):
    current_password: str | None = None
    new_password: str = Field(min_length=1, max_length=1024)


def media_url(media_id: str) -> str:
    return f"/api/media/{media_id}"


def media_out(media: models.Media) -> MediaOut:
    return MediaOut(
        id=media.id,
        url=media_url(media.id),
        alt=media.alt,
        width=media.width,
        height=media.height,
    )


def bullet_out(bullet: models.Bullet) -> BulletOut:
    return BulletOut(id=bullet.id, text=bullet.text, color=bullet.color, icon=bullet.icon, level=bullet.level)


def step_out(step: models.Step) -> StepOut:
    return StepOut(
        id=step.id,
        order_index=step.order_index,
        title=step.title,
        bullets=[bullet_out(bullet) for bullet in step.bullets],
        media=[media_out(link.media) for link in step.media_links],
    )


def user_ref_out(user: models.User) -> UserRefOut:
    return UserRefOut(id=user.id, display_name=user.display_name)


def user_out(user: models.User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        created_at=user.created_at,
    )


def category_out(category: models.Category) -> CategoryOut:
    return CategoryOut(
        id=category.id,
        slug=category.slug,
        name=category.name,
        description=category.description,
        parent_id=category.parent_id,
        order_index=category.order_index,
    )


def guide_out(guide: models.Guide) -> GuideOut:
    return GuideOut(
        id=guide.id,
        slug=guide.slug,
        title=guide.title,
        summary=guide.summary,
        category_id=guide.category_id,
        difficulty=guide.difficulty,
        time_required_minutes=guide.time_required_minutes,
        introduction=guide.introduction,
        conclusion=guide.conclusion,
        status=guide.status,
        steps=[step_out(step) for step in guide.steps],
        prerequisite_ids=guide.prerequisite_ids,
        author=user_ref_out(guide.author),
        last_edited_by=user_ref_out(guide.last_edited_by),
        created_at=guide.created_at,
        updated_at=guide.updated_at,
        published_at=guide.published_at,
        version=guide.version,
    )


def guide_summary_out(guide: models.Guide, step_count: int) -> GuideSummaryOut:
    return GuideSummaryOut(
        id=guide.id,
        slug=guide.slug,
        title=guide.title,
        summary=guide.summary,
        category_id=guide.category_id,
        difficulty=guide.difficulty,
        time_required_minutes=guide.time_required_minutes,
        status=guide.status,
        step_count=step_count,
        author=user_ref_out(guide.author),
        updated_at=guide.updated_at,
        published_at=guide.published_at,
    )


def guide_document(guide: models.Guide) -> dict[str, Any]:
    """The camelCase snapshot stored in a revision and replayed on read."""
    return guide_out(guide).model_dump(mode="json", by_alias=True)
