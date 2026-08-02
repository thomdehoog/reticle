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

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, PlainSerializer, model_validator
from pydantic.alias_generators import to_camel

from . import models

Role = Literal["viewer", "author", "admin"]
ContentStatus = Literal["draft", "in_review", "published", "archived"]
GuideStatus = ContentStatus
Difficulty = Literal["very_easy", "easy", "moderate", "difficult", "very_difficult"]
BulletColor = Literal["black", "red", "orange", "yellow", "green", "light_blue", "blue", "violet"]
BulletIcon = Literal["note", "caution", "reminder"]
BulletLevel = Literal[0, 1, 2]
AnnotationShape = Literal["rectangle", "ellipse", "arrow"]
MediaKind = Literal["image", "video"]

MAX_STEPS_PER_GUIDE = 200
MAX_BULLETS_PER_STEP = 200
MAX_TAGS_PER_GUIDE = 40
MAX_ANNOTATIONS_PER_MEDIA = 60
MAX_PAGE_BODY_CHARS = 200_000
"""Ceilings on what one document may contain.

All of them are far above anything a procedure has ever needed and far below
what one request can be used for: a single ``PUT`` carrying 2000 steps of 20
bullets wrote forty thousand rows and held the only SQLite writer for nearly
five seconds, which is a denial of service that any author account can perform
by accident as easily as on purpose.
"""

EDGE_TOLERANCE = 0.05
"""How far past the edge of its image a shape may sit.

Not zero, because an author aiming at a control against the border of a
screenshot legitimately drags a little past it, and because an imported
annotation carries whatever geometry the other system recorded. Not unbounded,
because a shape whose coordinates put it somewhere else entirely is either a
client that has drifted from the geometry in ``domain/annotation.ts`` or an
attempt to lay an overlay across the page.
"""

TAG_SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
"""What the tag input produces. Validated rather than re-slugified server-side,
because silently rewriting a tag would let two spellings agree on the client and
disagree in the database."""


def iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


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
    """An account as an administrator sees it.

    ``is_active`` is on the wire because it is enforced everywhere and was
    visible nowhere: a deactivated account behaved differently from an active
    one at every turn, yet the user list gave an administrator no way to tell
    which was which, so a colleague switched off after they left could not be
    audited without opening the database.
    """

    id: str
    email: str
    display_name: str
    role: Role
    is_active: bool
    created_at: Instant


class CategoryOut(Wire):
    id: str
    slug: str
    name: str
    description: str
    parent_id: str | None
    order_index: int
    is_hidden: bool
    hero_media_id: str | None
    image_url: str | None
    """What the browse screens are built from.

    Navigation here is meant to be looked at rather than read: somebody heading
    for the confocal recognises the instrument long before they finish reading
    its name. A section with no picture yet falls back to a drawn placeholder on
    the client, never to a broken image."""


class AnnotationOut(Wire):
    id: str
    shape: AnnotationShape
    color: BulletColor
    x: float
    y: float
    width: float
    height: float


class MediaOut(Wire):
    id: str
    url: str
    kind: MediaKind
    alt: str
    width: int | None
    height: int | None
    duration_seconds: float | None
    poster_url: str | None
    annotations: list[AnnotationOut]


class TagOut(Wire):
    id: str
    slug: str
    name: str
    guide_count: int


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
    video: MediaOut | None


class GuideOut(Wire):
    id: str
    slug: str
    title: str
    summary: str
    category_id: str
    tags: list[str]
    difficulty: Difficulty
    time_required_min_minutes: int | None
    time_required_max_minutes: int | None
    introduction: str
    conclusion: str
    status: ContentStatus
    steps: list[StepOut]
    author: UserRefOut
    last_edited_by: UserRefOut
    contributors: list[UserRefOut]
    view_count: int
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
    tags: list[str]
    difficulty: Difficulty
    time_required_min_minutes: int | None
    time_required_max_minutes: int | None
    status: ContentStatus
    step_count: int
    author: UserRefOut
    view_count: int
    thumbnail_url: str | None
    """The guide's first step image, which is what a card shows."""
    updated_at: Instant
    published_at: Instant | None


class PageOut(Wire):
    id: str
    slug: str
    title: str
    summary: str
    category_id: str | None
    is_landing: bool
    body: str
    hero_media_id: str | None
    status: ContentStatus
    author: UserRefOut
    last_edited_by: UserRefOut
    contributors: list[UserRefOut]
    view_count: int
    created_at: Instant
    updated_at: Instant
    published_at: Instant | None
    version: int


class PageSummaryOut(Wire):
    id: str
    slug: str
    title: str
    summary: str
    category_id: str | None
    is_landing: bool
    status: ContentStatus
    hero_image_url: str | None
    updated_at: Instant
    published_at: Instant | None


class GuideHitOut(Wire):
    """Search spans both content types, so a hit says which one it is."""

    kind: Literal["guide"] = "guide"
    guide: GuideSummaryOut


class PageHitOut(Wire):
    kind: Literal["page"] = "page"
    page: PageSummaryOut


SearchHitOut = GuideHitOut | PageHitOut


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
    is_hidden: bool = False
    hero_media_id: str | None = None


class CategoryPatchIn(Wire):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    parent_id: str | None = None
    order_index: int | None = Field(default=None, ge=0)
    is_hidden: bool | None = None
    hero_media_id: str | None = None


class GuideCreateIn(Wire):
    title: str = Field(min_length=1, max_length=240)
    category_id: str


class BulletIn(Document):
    id: str | None = None
    text: str = Field(default="", max_length=4000)
    color: BulletColor = "black"
    icon: BulletIcon | None = None
    level: BulletLevel = 0


class AnnotationIn(Document):
    """One shape drawn over a step image, as fractions of that image.

    An arrow carries a **signed** vector, because which end has the head is the
    entire point of drawing one: an author pointing at a control on the left of
    a screenshot drags leftwards, and a rule that extents must be positive would
    make that guide unsaveable — every autosave from then on refused, with the
    editor able to say only "could not save".

    A rectangle or an ellipse has no direction, so it is stored from its top-left
    corner with non-negative extents; a negative one there is a client that has
    drifted from the geometry in ``domain/annotation.ts``.
    """

    id: str | None = None
    shape: AnnotationShape = "rectangle"
    color: BulletColor = "red"
    x: float = Field(default=0.0, ge=-EDGE_TOLERANCE, le=1.0 + EDGE_TOLERANCE)
    y: float = Field(default=0.0, ge=-EDGE_TOLERANCE, le=1.0 + EDGE_TOLERANCE)
    width: float = Field(default=0.0, ge=-1.0 - EDGE_TOLERANCE, le=1.0 + EDGE_TOLERANCE)
    height: float = Field(default=0.0, ge=-1.0 - EDGE_TOLERANCE, le=1.0 + EDGE_TOLERANCE)

    @model_validator(mode="after")
    def _is_a_shape_the_reader_can_be_shown(self) -> AnnotationIn:
        if self.shape != "arrow" and (self.width < 0 or self.height < 0):
            raise ValueError("only an arrow may have a negative extent")
        lower, upper = -EDGE_TOLERANCE, 1.0 + EDGE_TOLERANCE
        if not lower <= self.x + self.width <= upper or not lower <= self.y + self.height <= upper:
            raise ValueError("an annotation has to stay on the image it belongs to")
        return self


class MediaRefIn(Document):
    """A step's reference to an already-uploaded file.

    The coordinates are bounded rather than clamped to 0..1 because an author
    may legitimately drag a shape a little past the edge of the image while
    aiming at something at its border; what is refused is a value so far out
    that it is either a bug or an attempt to make the overlay cover the page.
    """

    id: str
    alt: str = Field(default="", max_length=1000)
    annotations: list[AnnotationIn] = Field(default_factory=list, max_length=MAX_ANNOTATIONS_PER_MEDIA)


class StepIn(Document):
    """One step.

    ``media`` carries no schema-level cap because its limit is operator-owned:
    ``documents`` rejects anything over ``max_media_per_step`` so that raising
    the setting raises the real limit rather than colliding with a second one
    hidden here.
    """

    id: str | None = None
    title: str = Field(default="", max_length=400)
    bullets: list[BulletIn] = Field(default_factory=list, max_length=MAX_BULLETS_PER_STEP)
    media: list[MediaRefIn] = Field(default_factory=list)
    video: MediaRefIn | None = None


class GuideDocumentIn(Document):
    """The whole guide, as the editor holds it.

    ``updated_at`` is mandatory: defaulting it would turn the concurrency guard
    into an opt-in, and the one client that forgot to send it would silently
    overwrite everyone else's work.
    """

    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(default="", max_length=4000)
    category_id: str
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS_PER_GUIDE)
    difficulty: Difficulty = "moderate"
    time_required_min_minutes: int | None = Field(default=None, ge=0, le=100_000)
    time_required_max_minutes: int | None = Field(default=None, ge=0, le=100_000)
    introduction: str = Field(default="", max_length=20_000)
    conclusion: str = Field(default="", max_length=20_000)
    steps: list[StepIn] = Field(default_factory=list, max_length=MAX_STEPS_PER_GUIDE)
    updated_at: datetime


class PageCreateIn(Wire):
    title: str = Field(min_length=1, max_length=240)
    category_id: str | None = None
    is_landing: bool = False


class PageDocumentIn(Document):
    """The whole wiki page, as its editor holds it."""

    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(default="", max_length=4000)
    category_id: str | None = None
    is_landing: bool = False
    body: str = Field(default="", max_length=MAX_PAGE_BODY_CHARS)
    hero_media_id: str | None = None
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


def annotation_out(annotation: models.Annotation) -> AnnotationOut:
    return AnnotationOut(
        id=annotation.id,
        shape=annotation.shape,
        color=annotation.color,
        x=annotation.x,
        y=annotation.y,
        width=annotation.width,
        height=annotation.height,
    )


def media_out(media: models.Media) -> MediaOut:
    return MediaOut(
        id=media.id,
        url=media_url(media.id),
        kind=media.kind,
        alt=media.alt,
        width=media.width,
        height=media.height,
        duration_seconds=media.duration_seconds,
        poster_url=media_url(media.poster_media_id) if media.poster_media_id else None,
        annotations=[annotation_out(annotation) for annotation in media.annotations],
    )


def tag_out(tag: models.Tag, guide_count: int) -> TagOut:
    return TagOut(id=tag.id, slug=tag.slug, name=tag.name, guide_count=guide_count)


def bullet_out(bullet: models.Bullet) -> BulletOut:
    return BulletOut(id=bullet.id, text=bullet.text, color=bullet.color, icon=bullet.icon, level=bullet.level)


def step_out(step: models.Step) -> StepOut:
    return StepOut(
        id=step.id,
        order_index=step.order_index,
        title=step.title,
        bullets=[bullet_out(bullet) for bullet in step.bullets],
        media=[media_out(link.media) for link in step.media_links],
        video=media_out(step.video) if step.video is not None else None,
    )


def user_ref_out(user: models.User) -> UserRefOut:
    return UserRefOut(id=user.id, display_name=user.display_name)


def user_out(user: models.User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
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
        is_hidden=category.is_hidden,
        hero_media_id=category.hero_media_id,
        image_url=media_url(category.hero_media_id) if category.hero_media_id else None,
    )


def guide_out(guide: models.Guide) -> GuideOut:
    return GuideOut(
        id=guide.id,
        slug=guide.slug,
        title=guide.title,
        summary=guide.summary,
        category_id=guide.category_id,
        tags=guide.tag_slugs,
        difficulty=guide.difficulty,
        time_required_min_minutes=guide.time_required_min_minutes,
        time_required_max_minutes=guide.time_required_max_minutes,
        introduction=guide.introduction,
        conclusion=guide.conclusion,
        status=guide.status,
        steps=[step_out(step) for step in guide.steps],
        author=user_ref_out(guide.author),
        last_edited_by=user_ref_out(guide.last_edited_by),
        contributors=[user_ref_out(person) for person in guide.contributors],
        view_count=guide.view_count,
        created_at=guide.created_at,
        updated_at=guide.updated_at,
        published_at=guide.published_at,
        version=guide.version,
    )


def guide_summary_out(
    guide: models.Guide, step_count: int, thumbnail_media_id: str | None = None
) -> GuideSummaryOut:
    return GuideSummaryOut(
        id=guide.id,
        slug=guide.slug,
        title=guide.title,
        summary=guide.summary,
        category_id=guide.category_id,
        tags=guide.tag_slugs,
        difficulty=guide.difficulty,
        time_required_min_minutes=guide.time_required_min_minutes,
        time_required_max_minutes=guide.time_required_max_minutes,
        status=guide.status,
        step_count=step_count,
        author=user_ref_out(guide.author),
        view_count=guide.view_count,
        thumbnail_url=media_url(thumbnail_media_id) if thumbnail_media_id else None,
        updated_at=guide.updated_at,
        published_at=guide.published_at,
    )


def page_out(page: models.Page) -> PageOut:
    return PageOut(
        id=page.id,
        slug=page.slug,
        title=page.title,
        summary=page.summary,
        category_id=page.category_id,
        is_landing=page.is_landing,
        body=page.body,
        hero_media_id=page.hero_media_id,
        status=page.status,
        author=user_ref_out(page.author),
        last_edited_by=user_ref_out(page.last_edited_by),
        contributors=[user_ref_out(person) for person in page.contributors],
        view_count=page.view_count,
        created_at=page.created_at,
        updated_at=page.updated_at,
        published_at=page.published_at,
        version=page.version,
    )


def page_summary_out(page: models.Page) -> PageSummaryOut:
    return PageSummaryOut(
        id=page.id,
        slug=page.slug,
        title=page.title,
        summary=page.summary,
        category_id=page.category_id,
        is_landing=page.is_landing,
        status=page.status,
        hero_image_url=media_url(page.hero_media_id) if page.hero_media_id else None,
        updated_at=page.updated_at,
        published_at=page.published_at,
    )


def guide_document(guide: models.Guide) -> dict[str, Any]:
    """The camelCase snapshot stored in a revision and replayed on read."""
    return guide_out(guide).model_dump(mode="json", by_alias=True)


def page_document(page: models.Page) -> dict[str, Any]:
    return page_out(page).model_dump(mode="json", by_alias=True)
