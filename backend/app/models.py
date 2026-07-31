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

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ulid import ULID

from .db import Base, JsonDocument, UtcDateTime, utcnow

ROLES = ("viewer", "author", "admin")
GUIDE_STATUSES = ("draft", "in_review", "published", "archived")
DIFFICULTIES = ("very_easy", "easy", "moderate", "difficult", "very_difficult")
BULLET_COLORS = ("black", "red", "orange", "yellow", "green", "blue", "violet")
BULLET_ICONS = ("note", "caution", "warning", "reminder")

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
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")

    def is_live(self, now: datetime) -> bool:
        return self.revoked_at is None and self.expires_at > now


class LoginAttempt(Base):
    """Throttle ledger.

    Kept in the database rather than in process memory so that the limit still
    holds when Reticle runs under more than one uvicorn worker, and so that a
    restart is not a free reset for an attacker mid-spray.
    """

    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_scope_key_time", "scope", "key", "created_at"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(8))
    key: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"), nullable=True, index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)

    children: Mapped[list["Category"]] = relationship(back_populates="parent")
    parent: Mapped["Category | None"] = relationship(back_populates="children", remote_side=[id])
    guides: Mapped[list["Guide"]] = relationship(back_populates="category")


class Guide(Base):
    __tablename__ = "guides"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(240), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    summary: Mapped[str] = mapped_column(Text, default="")
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id"), index=True)
    difficulty: Mapped[str] = mapped_column(String(20), default="moderate")
    time_required_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    introduction: Mapped[str] = mapped_column(Text, default="")
    conclusion: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    last_edited_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    category: Mapped[Category] = relationship(back_populates="guides")
    author: Mapped[User] = relationship(foreign_keys=[author_id])
    last_edited_by: Mapped[User] = relationship(foreign_keys=[last_edited_by_id])
    steps: Mapped[list["Step"]] = relationship(
        back_populates="guide",
        cascade="all, delete-orphan",
        order_by="Step.order_index",
    )
    prerequisites: Mapped[list["GuidePrerequisite"]] = relationship(
        back_populates="guide",
        cascade="all, delete-orphan",
        order_by="GuidePrerequisite.order_index",
        foreign_keys="GuidePrerequisite.guide_id",
    )
    revisions: Mapped[list["GuideRevision"]] = relationship(
        back_populates="guide",
        cascade="all, delete-orphan",
        order_by="GuideRevision.version.desc()",
    )

    @property
    def prerequisite_ids(self) -> list[str]:
        return [link.prerequisite_id for link in self.prerequisites]


class GuidePrerequisite(Base):
    """An ordered edge from a guide to a guide that should be read first."""

    __tablename__ = "guide_prerequisites"
    __table_args__ = (UniqueConstraint("guide_id", "prerequisite_id", name="uq_guide_prerequisite"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    guide_id: Mapped[str] = mapped_column(ForeignKey("guides.id", ondelete="CASCADE"), index=True)
    prerequisite_id: Mapped[str] = mapped_column(ForeignKey("guides.id", ondelete="CASCADE"))
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    guide: Mapped[Guide] = relationship(back_populates="prerequisites", foreign_keys=[guide_id])


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

    @property
    def media(self) -> list["Media"]:
        return [link.media for link in self.media_links]


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
    byte_size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alt: Mapped[str] = mapped_column(Text, default="")
    original_filename: Mapped[str] = mapped_column(String(300), default="")
    uploaded_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    uploaded_by: Mapped[User] = relationship()


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


class AuditLog(Base):
    """Who changed what, when, and from where."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(26), nullable=True, index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JsonDocument, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)

    actor: Mapped[User | None] = relationship()
