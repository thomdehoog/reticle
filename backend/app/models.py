"""The persistent model behind ``frontend/src/domain/types.ts``.

Column names are snake_case; the wire format is camelCase and the translation
lives entirely in ``schemas``. Identifiers are ULIDs stored as text: they sort
by creation time, which makes "newest first" a plain index scan, and they are
safe to mint on the client so the editor can key a new step optimistically
before the server has seen it.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship, validates
from ulid import ULID

from .db import Base, JsonDocument, UtcDateTime, utcnow

IP_ADDRESS_LENGTH = 45
TAG_LENGTH = 60
LOGIN_ATTEMPT_KEY_LENGTH = 370

ROLES = ("viewer", "author", "admin")
CONTENT_STATUSES = ("draft", "in_review", "published", "archived")
DIFFICULTIES = ("very_easy", "easy", "moderate", "difficult", "very_difficult")
BULLET_COLORS = ("black", "red", "orange", "yellow", "green", "light_blue", "blue", "violet")
BULLET_ICONS = ("note", "caution", "reminder")
MEDIA_KINDS = ("image", "video")
ANNOTATION_SHAPES = ("rectangle", "ellipse", "arrow")

PUBLISHED = "published"
ARCHIVED = "archived"

ROLE_RANK = {role: rank for rank, role in enumerate(ROLES)}


def new_id() -> str:
    return str(ULID())


def is_valid_id(value: str) -> bool:
    """Guard client-supplied identifiers before they reach a path or a query."""
    try:
        ULID.from_str(value)
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def clip(value: str | None, length: int) -> str | None:
    """Hold a string to its column width at the boundary, not at each caller.

    SQLite ignores a declared ``VARCHAR`` length, so an over-long value inserts
    happily in development and raises on PostgreSQL in production — which is the
    worst possible place to find out. Truncating here means the guarantee holds
    for every writer, including the ones that do not exist yet.
    """
    if value is None:
        return None
    return value[:length]


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16), default="viewer")
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)

    sessions: Mapped[list["Session"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    """A server-side session, so logout is a revocation and not a hope.

    Only a hash of the cookie value is kept; a leaked database backup therefore
    does not hand over live sessions.
    """

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(IP_ADDRESS_LENGTH), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")

    @validates("ip_address")
    def _clip_ip_address(self, _key: str, value: str | None) -> str | None:
        return clip(value, IP_ADDRESS_LENGTH)

    def is_live(self, now: datetime) -> bool:
        return self.revoked_at is None and self.expires_at > now


class LoginAttempt(Base):
    """Throttle ledger.

    Kept in the database rather than in process memory so that the limit still
    holds when Reticle runs under more than one uvicorn worker, and so that a
    restart is not a free reset for an attacker mid-spray.

    ``key`` is wide enough for the longest scope, ``email_ip``, whose key is an
    address and a source address joined together.
    """

    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_scope_key_time", "scope", "key", "created_at"),
        Index("ix_login_attempts_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(8))
    key: Mapped[str] = mapped_column(String(LOGIN_ATTEMPT_KEY_LENGTH))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    @validates("key")
    def _clip_key(self, _key: str, value: str) -> str:
        return clip(value, LOGIN_ATTEMPT_KEY_LENGTH)


class Category(Base):
    """A place a guide or page is filed.

    ``is_hidden`` marks a holding category. ZMB keeps most guides in categories
    nobody browses and surfaces them through tags, so the flag is a hint to the
    navigation and deliberately nothing more: it grants and withholds no access.
    """

    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"), nullable=True, index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)

    children: Mapped[list["Category"]] = relationship(back_populates="parent")
    parent: Mapped["Category | None"] = relationship(back_populates="children", remote_side=[id])


class Tag(Base):
    """A label a guide is found by.

    ``slug`` is the identity and ``name`` is whichever spelling arrived first.
    There is no delete: a tag nobody carries simply stops being listed, which
    costs one row and saves a class of "who removed my tag" questions.
    """

    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(TAG_LENGTH), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(TAG_LENGTH))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class GuideTag(Base):
    __tablename__ = "guide_tags"

    guide_id: Mapped[str] = mapped_column(ForeignKey("guides.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True)


class ContentMixin:
    """The lifecycle a guide and a wiki page have in common.

    Draft, publish, unpublish, archive, a version that counts publishes, a view
    counter and the record of who touched it are one mechanism in ``content``;
    these are the columns that mechanism reads and writes, declared once so the
    two tables cannot drift apart.
    """

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(240), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    @declared_attr
    def author_id(cls) -> Mapped[str]:
        return mapped_column(ForeignKey("users.id"), index=True)

    @declared_attr
    def last_edited_by_id(cls) -> Mapped[str]:
        return mapped_column(ForeignKey("users.id"))

    @declared_attr
    def author(cls) -> Mapped[User]:
        return relationship(User, foreign_keys=f"{cls.__name__}.author_id")

    @declared_attr
    def last_edited_by(cls) -> Mapped[User]:
        return relationship(User, foreign_keys=f"{cls.__name__}.last_edited_by_id")

    @property
    def contributors(self) -> list[User]:
        return [link.user for link in self.contributor_links]


class ContributorMixin:
    """One row per person who has saved a piece of content, in order of arrival."""

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    @declared_attr
    def user_id(cls) -> Mapped[str]:
        return mapped_column(ForeignKey("users.id"), primary_key=True)

    @declared_attr
    def user(cls) -> Mapped[User]:
        return relationship(User, lazy="joined")


class RevisionMixin:
    """An immutable copy of content as it read at the moment it was published.

    Storing the rendered document rather than a diff means a citation of
    "version 3" keeps resolving even after the live content has been
    restructured beyond recognition.
    """

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    version: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    document: Mapped[dict[str, Any]] = mapped_column(JsonDocument)

    @declared_attr
    def published_by_id(cls) -> Mapped[str]:
        return mapped_column(ForeignKey("users.id"))

    @declared_attr
    def published_by(cls) -> Mapped[User]:
        return relationship(User, lazy="joined")


class Guide(ContentMixin, Base):
    __tablename__ = "guides"

    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id"), index=True)
    difficulty: Mapped[str] = mapped_column(String(20), default="moderate")
    time_required_min_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_required_max_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    introduction: Mapped[str] = mapped_column(Text, default="")
    conclusion: Mapped[str] = mapped_column(Text, default="")

    category: Mapped[Category] = relationship()
    steps: Mapped[list["Step"]] = relationship(
        back_populates="guide",
        cascade="all, delete-orphan",
        order_by="Step.order_index",
    )
    tags: Mapped[list[Tag]] = relationship(secondary="guide_tags", order_by="Tag.slug")
    contributor_links: Mapped[list["GuideContributor"]] = relationship(
        cascade="all, delete-orphan",
        order_by="GuideContributor.created_at, GuideContributor.user_id",
    )
    revisions: Mapped[list["GuideRevision"]] = relationship(
        cascade="all, delete-orphan",
        order_by="GuideRevision.version.desc()",
    )

    @property
    def tag_slugs(self) -> list[str]:
        return sorted(tag.slug for tag in self.tags)


class GuideContributor(ContributorMixin, Base):
    __tablename__ = "guide_contributors"

    owner_id: Mapped[str] = mapped_column(
        "guide_id", ForeignKey("guides.id", ondelete="CASCADE"), primary_key=True
    )


class GuideRevision(RevisionMixin, Base):
    __tablename__ = "guide_revisions"
    __table_args__ = (UniqueConstraint("guide_id", "version", name="uq_guide_revision_version"),)

    owner_id: Mapped[str] = mapped_column("guide_id", ForeignKey("guides.id", ondelete="CASCADE"), index=True)


class Step(Base):
    __tablename__ = "steps"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    guide_id: Mapped[str] = mapped_column(ForeignKey("guides.id", ondelete="CASCADE"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(400), default="")

    guide: Mapped[Guide] = relationship(back_populates="steps")
    bullets: Mapped[list["Bullet"]] = relationship(
        back_populates="step",
        cascade="all, delete-orphan",
        order_by="Bullet.order_index",
    )
    media_links: Mapped[list["StepMedia"]] = relationship(
        back_populates="step",
        cascade="all, delete-orphan",
        order_by="StepMedia.order_index",
    )


class Bullet(Base):
    __tablename__ = "bullets"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    step_id: Mapped[str] = mapped_column(ForeignKey("steps.id", ondelete="CASCADE"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(16), default="black")
    icon: Mapped[str | None] = mapped_column(String(16), nullable=True)
    level: Mapped[int] = mapped_column(Integer, default=0)

    step: Mapped[Step] = relationship(back_populates="bullets")


class Media(Base):
    """An uploaded image or video.

    ``storage_path`` is relative to the configured media root and is generated
    from the identifier, never from anything the uploader supplied. ``alt`` is
    what the uploader typed, if anything; the text a reader actually gets is
    kept on the link that places the file in a step.
    """

    __tablename__ = "media"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(8), default="image")
    storage_path: Mapped[str] = mapped_column(String(300), unique=True)
    content_type: Mapped[str] = mapped_column(String(60))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alt: Mapped[str] = mapped_column(Text, default="")
    original_filename: Mapped[str] = mapped_column(String(300), default="")
    uploaded_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    uploaded_by: Mapped[User] = relationship()


class StepMedia(Base):
    """Ordered membership of a media item in a step, capped by the editor rule.

    The alt text and the annotations live here rather than on ``Media``. A shape
    drawn round a button belongs to the instruction it illustrates, so the same
    screenshot reused in another step has to start clean instead of arriving
    with somebody else's arrows on it.
    """

    __tablename__ = "step_media"
    __table_args__ = (UniqueConstraint("step_id", "media_id", name="uq_step_media"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    step_id: Mapped[str] = mapped_column(ForeignKey("steps.id", ondelete="CASCADE"), index=True)
    media_id: Mapped[str] = mapped_column(ForeignKey("media.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    alt: Mapped[str] = mapped_column(Text, default="")
    annotations: Mapped[list[dict[str, Any]]] = mapped_column(JsonDocument, default=list)

    step: Mapped[Step] = relationship(back_populates="media_links")
    media: Mapped[Media] = relationship(lazy="joined")


class Page(ContentMixin, Base):
    """A wiki page: long-form Markdown.

    A category's landing content is a page with ``is_landing`` set, rather than
    a body column on ``Category``, so drafts, publishing and history are the
    same mechanism for both. The partial unique index is the backstop for the
    "one landing page per category" rule: the router checks first so it can say
    something helpful, and the index is what holds when two requests check at
    the same moment.
    """

    __tablename__ = "pages"
    __table_args__ = (
        Index(
            "uq_pages_one_landing_per_category",
            "category_id",
            unique=True,
            sqlite_where=text("is_landing = 1 AND status != 'archived'"),
            postgresql_where=text("is_landing AND status != 'archived'"),
        ),
    )

    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"), nullable=True, index=True)
    is_landing: Mapped[bool] = mapped_column(Boolean, default=False)
    body: Mapped[str] = mapped_column(Text, default="")
    hero_media_id: Mapped[str | None] = mapped_column(ForeignKey("media.id"), nullable=True, index=True)
    # The description lives on the page, not on the upload, for the same reason a
    # step's alt text lives on the step: the same picture can head two pages and
    # be described differently on each. The server default is what lets the
    # column be added to a table that already has rows.
    hero_alt: Mapped[str] = mapped_column(Text, default="", server_default="")

    category: Mapped[Category | None] = relationship()
    contributor_links: Mapped[list["PageContributor"]] = relationship(
        cascade="all, delete-orphan",
        order_by="PageContributor.created_at, PageContributor.user_id",
    )
    revisions: Mapped[list["PageRevision"]] = relationship(
        cascade="all, delete-orphan",
        order_by="PageRevision.version.desc()",
    )
    media_links: Mapped[list["PageMedia"]] = relationship(cascade="all, delete-orphan")


class PageContributor(ContributorMixin, Base):
    __tablename__ = "page_contributors"

    owner_id: Mapped[str] = mapped_column(
        "page_id", ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True
    )


class PageRevision(RevisionMixin, Base):
    __tablename__ = "page_revisions"
    __table_args__ = (UniqueConstraint("page_id", "version", name="uq_page_revision_version"),)

    owner_id: Mapped[str] = mapped_column("page_id", ForeignKey("pages.id", ondelete="CASCADE"), index=True)


class PageMedia(Base):
    """A media file a page's Markdown body points at.

    The body is free text, so nothing in the schema says which uploads it shows.
    Recording the ``/api/media/<id>`` references on every save turns "may this
    viewer fetch this image" into a join, the same as it is for a guide step,
    instead of a scan of every published body on every image request.
    """

    __tablename__ = "page_media"

    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True)
    media_id: Mapped[str] = mapped_column(ForeignKey("media.id"), primary_key=True, index=True)


class AuditLog(Base):
    """Who changed what, when, and from where."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(26), nullable=True, index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JsonDocument, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(IP_ADDRESS_LENGTH), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)

    actor: Mapped[User | None] = relationship()

    @validates("ip_address")
    def _clip_ip_address(self, _key: str, value: str | None) -> str | None:
        return clip(value, IP_ADDRESS_LENGTH)


class ImportRecord(Base):
    """Which vendor item became which Reticle row, for the one-off content import.

    The mapping lives in the database rather than in a file beside the export
    because it describes *this* database: it is backed up, restored and rolled
    back with the rows it points at, it commits in the same transaction as the
    guide it records, and one export archive can be loaded into a test instance
    and into production without either load mistaking the other's identifiers
    for its own.

    ``imported_updated_at`` is the ``updated_at`` the content carried when the
    importer last wrote it. Any later edit in Reticle moves ``updated_at``, and
    that difference is what stops a re-run from overwriting a colleague's work.
    """

    __tablename__ = "import_records"
    __table_args__ = (UniqueConstraint("source", "kind", "vendor_id", name="uq_import_record_source_item"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    source: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))
    vendor_id: Mapped[str] = mapped_column(String(300))
    reticle_id: Mapped[str] = mapped_column(String(26), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    imported_updated_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)
