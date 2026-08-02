"""The shape of everything Reticle stores.

This is the blueprint for the database: one class here becomes one table, and
one attribute becomes one column. A guide, a step, a bullet point, a picture, a
shape drawn on a picture, an account, a category, a tag - if Reticle remembers
it, it is described here.

Reading this file is the fastest way to understand the whole system, because
everything else is either putting things into these tables or taking them out
again. Start with ``Guide``, then follow it down: a guide has steps, a step has
bullets and pictures, a picture has shapes.

Two conventions worth knowing before you read:

Names here use under_scores, but the website speaks in camelCase. That
translation happens in one place only, ``schemas.py``, so nothing else ever has
to think about it.

Identifiers are ULIDs - long random-looking strings like
``01JQZK3T8P9WBRE2880TSQ1736``. Unlike counting from 1, two computers can
generate them without ever colliding, which is what lets the editor create a new
step and draw it immediately, before the server has heard about it. They also
sort by the time they were made, so "newest first" is free.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from ulid import ULID

from .db import Base, JsonDocument, UtcDateTime, utcnow

IP_ADDRESS_LENGTH = 45
LOGIN_ATTEMPT_KEY_LENGTH = 370

ROLES = ("viewer", "author", "admin")

ROLE_RANK = {role: rank for rank, role in enumerate(ROLES)}

PUBLISHED = "published"
"""The one status a reader is ever shown.

Named once and imported, because it is the operand of the ``WHERE`` clause that
keeps a half-written safety procedure internal. A second spelling of it in a
second file is a place that rule can drift out of.

The full status vocabulary is the ``ContentStatus`` literal in ``schemas``,
which is what actually refuses an unknown value at the boundary.
"""


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

    PostgreSQL enforces a declared ``VARCHAR`` length by refusing the row, and
    the values that overflow one arrive from outside — an imported title, a
    pasted slug — so the failure would land on whoever ran the import rather
    than on whoever wrote the column. Truncating here means the guarantee holds
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

    sessions: Mapped[list[Session]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


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
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
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
    __table_args__ = (Index("ix_login_attempts_scope_key_time", "scope", "key", "created_at"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(8))
    key: Mapped[str] = mapped_column(String(LOGIN_ATTEMPT_KEY_LENGTH))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    @validates("key")
    def _clip_key(self, _key: str, value: str) -> str:
        return clip(value, LOGIN_ATTEMPT_KEY_LENGTH)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    hero_media_id: Mapped[str | None] = mapped_column(ForeignKey("media.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)

    children: Mapped[list[Category]] = relationship(back_populates="parent")
    parent: Mapped[Category | None] = relationship(back_populates="children", remote_side=[id])
    guides: Mapped[list[Guide]] = relationship(back_populates="category")


class Guide(Base):
    __tablename__ = "guides"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(240), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    summary: Mapped[str] = mapped_column(Text, default="")
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id"), index=True)
    difficulty: Mapped[str] = mapped_column(String(20), default="moderate")
    time_required_min_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_required_max_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    introduction: Mapped[str] = mapped_column(Text, default="")
    conclusion: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    # A guide the facility wants reached in one move — "Book an instrument",
    # "Get building access" — shown as a picture-and-text block on the front page
    # or a category page instead of as one line in a list.
    is_quick_link: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=0)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    last_edited_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    category: Mapped[Category] = relationship(back_populates="guides")
    author: Mapped[User] = relationship(foreign_keys=[author_id])
    last_edited_by: Mapped[User] = relationship(foreign_keys=[last_edited_by_id])
    steps: Mapped[list[Step]] = relationship(
        back_populates="guide",
        cascade="all, delete-orphan",
        order_by="Step.order_index",
    )
    tag_links: Mapped[list[GuideTag]] = relationship(
        back_populates="guide",
        cascade="all, delete-orphan",
        order_by="GuideTag.order_index",
    )
    contributor_links: Mapped[list[GuideContributor]] = relationship(
        back_populates="guide",
        cascade="all, delete-orphan",
        order_by="GuideContributor.first_edited_at",
    )
    revisions: Mapped[list[GuideRevision]] = relationship(
        back_populates="guide",
        cascade="all, delete-orphan",
        order_by="GuideRevision.version.desc()",
    )

    @property
    def tag_slugs(self) -> list[str]:
        return [link.tag.slug for link in self.tag_links]

    @property
    def contributors(self) -> list[User]:
        return [link.user for link in self.contributor_links]


class Tag(Base):
    """A navigation label.

    ZMB's site is navigated by tag rather than by the category tree — a guide
    sits in one category and carries many tags, which is how one LAS X guide
    appears under every instrument heading it applies to. The slug is the
    identity; ``name`` only exists so a tag can be given a nicer display form
    later without breaking the URLs already written into wiki pages.
    """

    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    guide_links: Mapped[list[GuideTag]] = relationship(
        back_populates="tag", cascade="all, delete-orphan"
    )


class GuideTag(Base):
    """Ordered membership of a guide in a tag, so the author's order survives."""

    __tablename__ = "guide_tags"
    __table_args__ = (UniqueConstraint("guide_id", "tag_id", name="uq_guide_tag"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    guide_id: Mapped[str] = mapped_column(ForeignKey("guides.id", ondelete="CASCADE"), index=True)
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    guide: Mapped[Guide] = relationship(back_populates="tag_links")
    tag: Mapped[Tag] = relationship(back_populates="guide_links", lazy="joined")


class GuideContributor(Base):
    """Everyone who has saved a guide, in the order they first touched it.

    At a facility the edit history is often the only surviving record of why a
    procedure says what it says, so it is kept as data rather than inferred from
    the audit log, which is rotated.
    """

    __tablename__ = "guide_contributors"
    __table_args__ = (UniqueConstraint("guide_id", "user_id", name="uq_guide_contributor"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    guide_id: Mapped[str] = mapped_column(ForeignKey("guides.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    first_edited_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_edited_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    guide: Mapped[Guide] = relationship(back_populates="contributor_links")
    user: Mapped[User] = relationship(lazy="joined")


class Step(Base):
    __tablename__ = "steps"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    guide_id: Mapped[str] = mapped_column(ForeignKey("guides.id", ondelete="CASCADE"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(400), default="")
    video_media_id: Mapped[str | None] = mapped_column(ForeignKey("media.id"), nullable=True)

    guide: Mapped[Guide] = relationship(back_populates="steps")
    video: Mapped[Media | None] = relationship(foreign_keys=[video_media_id], lazy="joined")
    bullets: Mapped[list[Bullet]] = relationship(
        back_populates="step",
        cascade="all, delete-orphan",
        order_by="Bullet.order_index",
    )
    media_links: Mapped[list[StepMedia]] = relationship(
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
    """An uploaded image.

    ``storage_path`` is relative to the configured media root and is generated
    from the identifier, never from anything the uploader supplied.
    """

    __tablename__ = "media"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    storage_path: Mapped[str] = mapped_column(String(300), unique=True)
    content_type: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(8), default="image")
    byte_size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    poster_media_id: Mapped[str | None] = mapped_column(ForeignKey("media.id"), nullable=True)
    alt: Mapped[str] = mapped_column(Text, default="")
    original_filename: Mapped[str] = mapped_column(String(300), default="")
    uploaded_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    uploaded_by: Mapped[User] = relationship()
    poster: Mapped[Media | None] = relationship(remote_side=[id])
    annotations: Mapped[list[Annotation]] = relationship(
        back_populates="media",
        cascade="all, delete-orphan",
        order_by="Annotation.order_index",
    )


class Annotation(Base):
    """A shape drawn over an uploaded image, in a bullet's colour.

    Stored as fractions of the image rather than burned into the pixels: the
    original upload stays intact, the shape stays editable, and it scales with
    whatever size the image is rendered at instead of pixellating.
    """

    __tablename__ = "annotations"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    media_id: Mapped[str] = mapped_column(ForeignKey("media.id", ondelete="CASCADE"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    shape: Mapped[str] = mapped_column(String(16), default="rectangle")
    color: Mapped[str] = mapped_column(String(16), default="red")
    x: Mapped[float] = mapped_column(Float, default=0.0)
    y: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[float] = mapped_column(Float, default=0.0)
    height: Mapped[float] = mapped_column(Float, default=0.0)

    media: Mapped[Media] = relationship(back_populates="annotations")


class StepMedia(Base):
    """Ordered membership of a media item in a step, capped by the editor rule."""

    __tablename__ = "step_media"
    __table_args__ = (UniqueConstraint("step_id", "media_id", name="uq_step_media"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    step_id: Mapped[str] = mapped_column(ForeignKey("steps.id", ondelete="CASCADE"), index=True)
    media_id: Mapped[str] = mapped_column(ForeignKey("media.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    step: Mapped[Step] = relationship(back_populates="media_links")
    media: Mapped[Media] = relationship(lazy="joined")


class GuideRevision(Base):
    """An immutable copy of a guide as it read at the moment it was published.

    Storing the rendered document rather than a diff means a citation of
    "version 3" keeps resolving even after the live guide has been restructured
    beyond recognition.
    """

    __tablename__ = "guide_revisions"
    __table_args__ = (UniqueConstraint("guide_id", "version", name="uq_guide_revision_version"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    guide_id: Mapped[str] = mapped_column(ForeignKey("guides.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    published_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    document: Mapped[dict[str, Any]] = mapped_column(JsonDocument)

    guide: Mapped[Guide] = relationship(back_populates="revisions")
    published_by: Mapped[User] = relationship()


class Page(Base):
    """A wiki page.

    ZMB's category landings are wiki pages whose body embeds tag-filtered guide
    lists, so a landing is a ``Page`` with ``is_landing`` set rather than a body
    column on ``Category``. That way pages, category landings, drafts,
    publishing and version history are one mechanism instead of two.
    """

    __tablename__ = "pages"
    __table_args__ = (
        # One landing per category. Expressed as a partial unique index so the
        # database refuses a second one even if a future writer forgets to ask;
        # the router checks first only to return a readable conflict.
        Index(
            "uq_page_landing_per_category",
            "category_id",
            unique=True,
            postgresql_where=text("is_landing"),
        ),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(240), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    summary: Mapped[str] = mapped_column(Text, default="")
    category_id: Mapped[str | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True, index=True
    )
    is_landing: Mapped[bool] = mapped_column(Boolean, default=False)
    body: Mapped[str] = mapped_column(Text, default="")
    hero_media_id: Mapped[str | None] = mapped_column(ForeignKey("media.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    last_edited_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    category: Mapped[Category | None] = relationship()
    hero_media: Mapped[Media | None] = relationship()
    author: Mapped[User] = relationship(foreign_keys=[author_id])
    last_edited_by: Mapped[User] = relationship(foreign_keys=[last_edited_by_id])
    contributor_links: Mapped[list[PageContributor]] = relationship(
        back_populates="page",
        cascade="all, delete-orphan",
        order_by="PageContributor.first_edited_at",
    )
    revisions: Mapped[list[PageRevision]] = relationship(
        back_populates="page",
        cascade="all, delete-orphan",
        order_by="PageRevision.version.desc()",
    )

    @property
    def contributors(self) -> list[User]:
        return [link.user for link in self.contributor_links]


class PageContributor(Base):
    __tablename__ = "page_contributors"
    __table_args__ = (UniqueConstraint("page_id", "user_id", name="uq_page_contributor"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    first_edited_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_edited_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    page: Mapped[Page] = relationship(back_populates="contributor_links")
    user: Mapped[User] = relationship(lazy="joined")


class PageRevision(Base):
    """An immutable copy of a page as it read when it was published."""

    __tablename__ = "page_revisions"
    __table_args__ = (UniqueConstraint("page_id", "version", name="uq_page_revision_version"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    published_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    document: Mapped[dict[str, Any]] = mapped_column(JsonDocument)

    page: Mapped[Page] = relationship(back_populates="revisions")
    published_by: Mapped[User] = relationship()


class ImportedRecord(Base):
    """What a migrated row was before it was ours.

    Two jobs. It makes the importer idempotent — a re-run after a network
    failure updates what it already created instead of producing a second copy
    of eighty confocal guides — and it keeps the thread back to the original,
    so a reviewer comparing Reticle against the live site can go from a guide
    here to the exact guide there without matching on titles.
    """

    __tablename__ = "imported_records"
    __table_args__ = (
        UniqueConstraint("source_system", "source_kind", "source_id", name="uq_imported_source"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    source_system: Mapped[str] = mapped_column(String(40), default="dozuki")
    source_kind: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[str] = mapped_column(String(200), index=True)
    source_url: Mapped[str] = mapped_column(Text, default="")
    local_id: Mapped[str] = mapped_column(String(26), index=True)
    content_digest: Mapped[str] = mapped_column(String(64), default="")
    imported_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


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
