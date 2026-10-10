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

from pydantic import BaseModel, ConfigDict, EmailStr, Field, PlainSerializer, model_validator
from pydantic.alias_generators import to_camel

from . import models

Role = Literal["viewer", "author", "admin"]
ContentStatus = Literal["draft", "in_review", "published", "archived"]
Difficulty = Literal["very_easy", "easy", "moderate", "difficult", "very_difficult"]
BulletColor = Literal["black", "red", "orange", "yellow", "green", "light_blue", "blue", "violet"]
BulletIcon = Literal["note", "caution", "reminder"]
BulletLevel = Literal[0, 1, 2]
MediaKind = Literal["image", "video"]
AnnotationShape = Literal["rectangle", "ellipse", "arrow"]

MAX_STEPS_PER_GUIDE = 200
MAX_BULLETS_PER_STEP = 200
"""Ceilings on what one document may contain.

Both are far above anything a procedure has ever needed and far below what one
request can be used for: a single ``PUT`` carrying 2000 steps of 20 bullets
wrote forty thousand rows and held the only SQLite writer for nearly five
seconds, which is a denial of service that any author account can perform by
accident as easily as on purpose.
"""

MAX_TAGS_PER_GUIDE = 30
MAX_TAG_LENGTH = models.TAG_LENGTH
MAX_ANNOTATIONS_PER_IMAGE = 50
MAX_PAGE_BODY_CHARS = 200_000
MAX_SEARCH_TERM_CHARS = 200


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


Instant = Annotated[datetime, PlainSerializer(iso_utc, return_type=str, when_used="json")]

Fraction = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
SignedFraction = Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)]


class Wire(BaseModel):
    """Base for everything crossing the boundary in either direction."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class Document(Wire):
    """Base for request bodies that the client round-trips.

    The editor sends back the whole object it was given, read-only fields
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


class TagOut(Wire):
    id: str
    slug: str
    name: str
    guide_count: int


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
    kind: MediaKind
    url: str
    alt: str
    width: int | None
    height: int | None
    annotations: list[AnnotationOut]


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
    updated_at: Instant
    published_at: Instant | None


class GuideResultOut(Wire):
    kind: Literal["guide"] = "guide"
    guide: GuideSummaryOut


class PageResultOut(Wire):
    kind: Literal["page"] = "page"
    page: PageSummaryOut


SearchResultOut = GuideResultOut | PageResultOut


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


class CategoryPatchIn(Wire):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    parent_id: str | None = None
    order_index: int | None = Field(default=None, ge=0)
    is_hidden: bool | None = None


class GuideCreateIn(Wire):
    title: str = Field(min_length=1, max_length=240)
    category_id: str


class PageCreateIn(Wire):
    title: str = Field(min_length=1, max_length=240)
    category_id: str | None = None
    is_landing: bool = False


class BulletIn(Document):
    id: str | None = None
    text: str = Field(default="", max_length=4000)
    color: BulletColor = "black"
    icon: BulletIcon | None = None
    level: BulletLevel = 0


class AnnotationIn(Document):
    """A shape over an image, in fractions of the image.

    ``x`` and ``y`` stay inside the picture. ``width`` and ``height`` are signed
    because an arrow has a direction — one pointing up and to the left has two
    negative extents — and bounded so that a shape cannot be parked a thousand
    image-widths off the edge, where the reader never sees it and the PDF
    renderer still has to draw it.
    """

    id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    shape: AnnotationShape
    color: BulletColor = "red"
    x: Fraction
    y: Fraction
    width: SignedFraction
    height: SignedFraction


class MediaRefIn(Document):
    id: str
    alt: str = Field(default="", max_length=1000)
    annotations: list[AnnotationIn] = Field(default_factory=list, max_length=MAX_ANNOTATIONS_PER_IMAGE)


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


class GuideDocumentIn(Document):
    """The whole guide, as the editor holds it.

    ``expected_updated_at`` is mandatory: defaulting it would turn the
    concurrency guard into an opt-in, and the one client that forgot to send it
    would silently overwrite everyone else's work.

    The title may be empty. An author who clears the field to retype it must not
    have the autosave underneath them start failing; publishing is where a title
    becomes compulsory.
    """

    title: str = Field(default="", max_length=240)
    summary: str = Field(default="", max_length=4000)
    category_id: str
    tags: list[Annotated[str, Field(max_length=MAX_TAG_LENGTH)]] = Field(
        default_factory=list, max_length=MAX_TAGS_PER_GUIDE
    )
    difficulty: Difficulty = "moderate"
    time_required_min_minutes: int | None = Field(default=None, ge=0, le=100_000)
    time_required_max_minutes: int | None = Field(default=None, ge=0, le=100_000)
    introduction: str = Field(default="", max_length=20_000)
    conclusion: str = Field(default="", max_length=20_000)
    steps: list[StepIn] = Field(default_factory=list, max_length=MAX_STEPS_PER_GUIDE)
    expected_updated_at: datetime

    @model_validator(mode="after")
    def _range_is_ordered(self) -> "GuideDocumentIn":
        low, high = self.time_required_min_minutes, self.time_required_max_minutes
        if low is not None and high is not None and low > high:
            raise ValueError("the minimum time required must not exceed the maximum")
        return self


class PageDocumentIn(Document):
    """The whole wiki page, as the editor holds it."""

    title: str = Field(default="", max_length=240)
    summary: str = Field(default="", max_length=4000)
    category_id: str | None = None
    is_landing: bool = False
    body: str = Field(default="", max_length=MAX_PAGE_BODY_CHARS)
    hero_media_id: str | None = None
    expected_updated_at: datetime


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
    current_password: str | None = Field(default=None, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


def media_url(media_id: str) -> str:
    return f"/api/media/{media_id}"


def media_out(media: models.Media, alt: str | None = None, annotations: list[dict[str, Any]] | None = None) -> MediaOut:
    """Serialise an upload, optionally as it appears in one particular step."""
    return MediaOut(
        id=media.id,
        kind=media.kind,
        url=media_url(media.id),
        alt=media.alt if alt is None else alt,
        width=media.width,
        height=media.height,
        annotations=[AnnotationOut(**annotation) for annotation in annotations or []],
    )


def bullet_out(bullet: models.Bullet) -> BulletOut:
    return BulletOut(id=bullet.id, text=bullet.text, color=bullet.color, icon=bullet.icon, level=bullet.level)


def step_out(step: models.Step) -> StepOut:
    return StepOut(
        id=step.id,
        order_index=step.order_index,
        title=step.title,
        bullets=[bullet_out(bullet) for bullet in step.bullets],
        media=[media_out(link.media, link.alt, link.annotations) for link in step.media_links],
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
        contributors=[user_ref_out(user) for user in guide.contributors],
        view_count=guide.view_count,
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
        tags=guide.tag_slugs,
        difficulty=guide.difficulty,
        time_required_min_minutes=guide.time_required_min_minutes,
        time_required_max_minutes=guide.time_required_max_minutes,
        status=guide.status,
        step_count=step_count,
        author=user_ref_out(guide.author),
        view_count=guide.view_count,
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
        contributors=[user_ref_out(user) for user in page.contributors],
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
        updated_at=page.updated_at,
        published_at=page.published_at,
    )


def snapshot(document: Wire) -> dict[str, Any]:
    """The camelCase form stored in a revision and replayed on read."""
    return document.model_dump(mode="json", by_alias=True)
