"""The lifecycle that guides and wiki pages share.

Both are written as drafts, published into numbered immutable snapshots,
unpublished, archived, counted when read and attributed to everyone who saved
them. That is one mechanism, so it lives here once: a :class:`ContentKind`
describes what differs between the two, and :func:`lifecycle_routes` hangs the
identical endpoints off either router.

Visibility is decided here too, and only here. It is always a ``WHERE`` clause
and never a filter applied while serialising: a draft that reaches the
serialiser has already been loaded, and one forgotten branch there is the
difference between a half-written safety procedure staying internal and it
being served to the whole institute.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import ColumnElement, or_, select, update
from sqlalchemy.orm import Session as DbSession

from . import audit, errors
from .auth import AdminUser, AnyUser, AuthorUser, DbDep, client_address
from .db import utcnow
from .models import ARCHIVED, PUBLISHED, User
from .schemas import RevisionSummaryOut, Wire, snapshot, user_ref_out


@dataclass(frozen=True)
class ContentKind:
    """What the shared lifecycle needs to know about one kind of content."""

    name: str
    model: type
    revision_model: type
    contributor_model: type
    out_model: type[Wire]
    serialise: Callable[[Any], Wire]
    assert_publishable: Callable[[Any], None]
    eager: Callable[[], Sequence[Any]] = tuple

    def missing(self) -> errors.ApiError:
        return errors.not_found(f"That {self.name} does not exist.")


def escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def contains(column: Any, term: str) -> ColumnElement[bool]:
    """Case-insensitive substring match with the user's wildcards neutralised."""
    return column.ilike(f"%{escape_like(term)}%", escape="\\")


def visible_to(model: type, user: User) -> ColumnElement[bool]:
    """The one visibility rule, as a predicate.

    A viewer sees what is published. An author or an administrator sees
    everything except what has been archived. Nothing else exists as far as the
    caller can tell, which is why every miss is a 404 and never a 403: saying
    "you may not see this" already says that it is there.
    """
    if user.role == "viewer":
        return model.status == PUBLISHED
    return model.status != ARCHIVED


def load_visible(db: DbSession, kind: ContentKind, user: User, key: str) -> Any:
    """Resolve by identifier or slug, as far as this caller is allowed to see."""
    statement = (
        select(kind.model)
        .where(or_(kind.model.id == key, kind.model.slug == key), visible_to(kind.model, user))
        .options(*kind.eager())
    )
    entity = db.scalars(statement).one_or_none()
    if entity is None:
        raise kind.missing()
    return entity


def load_editable(db: DbSession, kind: ContentKind, item_id: str) -> Any:
    """Resolve by identifier for a write.

    Callers are authors or administrators by the time they get here, so the
    only thing hidden from them is the archive.
    """
    statement = (
        select(kind.model)
        .where(kind.model.id == item_id, kind.model.status != ARCHIVED)
        .options(*kind.eager())
    )
    entity = db.scalars(statement).one_or_none()
    if entity is None:
        raise kind.missing()
    return entity


def next_updated_at(previous: datetime) -> datetime:
    """Guarantee a strictly increasing ``updatedAt``.

    The concurrency token is the timestamp itself, so two saves landing inside
    one tick of the system clock must not compare equal; if they did, the second
    author's stale copy would be accepted as current.
    """
    now = utcnow()
    floor = previous + timedelta(microseconds=1)
    return max(now, floor)


def assert_not_stale(kind: ContentKind, entity: Any, expected: datetime) -> None:
    """Refuse a save made against anything but the stored version.

    The comparison is equality, not "not older than": a token from the future is
    as much evidence that the client is not looking at this row as one from the
    past.
    """
    seen = expected if expected.tzinfo is not None else expected.replace(tzinfo=timezone.utc)
    if entity.updated_at != seen:
        raise errors.conflict(
            f"This {kind.name} changed after you opened it. Reload to pick up the newer version before saving."
        )


def touch(entity: Any, actor: User) -> None:
    entity.updated_at = next_updated_at(entity.updated_at)
    entity.last_edited_by_id = actor.id


def add_contributor(db: DbSession, kind: ContentKind, entity: Any, actor: User) -> None:
    if any(link.user_id == actor.id for link in entity.contributor_links):
        return
    entity.contributor_links.append(kind.contributor_model(user_id=actor.id))


def write_revision(db: DbSession, kind: ContentKind, entity: Any, actor: User, now: datetime) -> None:
    db.add(
        kind.revision_model(
            owner_id=entity.id,
            version=entity.version,
            published_at=now,
            published_by_id=actor.id,
            document=snapshot(kind.serialise(entity)),
        )
    )


def publish(db: DbSession, kind: ContentKind, entity: Any, actor: User) -> None:
    kind.assert_publishable(entity)
    now = utcnow()
    entity.status = PUBLISHED
    entity.version += 1
    entity.published_at = now
    touch(entity, actor)
    db.flush()
    write_revision(db, kind, entity, actor, now)


def lifecycle_routes(router: APIRouter, kind: ContentKind) -> None:
    """Attach publish, unpublish, view, archive and history to a router.

    Declared once and registered twice, so a guide and a page cannot come to
    disagree about what "unpublish" means or which role may archive.
    """
    name = kind.name

    def _audit(db: DbSession, request: Request, action: str, entity: Any, actor: User, detail: dict[str, Any]) -> None:
        audit.record(
            db,
            action=f"{name}.{action}",
            entity_type=name,
            entity_id=entity.id,
            actor=actor,
            ip_address=client_address(request),
            detail=detail,
        )

    @router.post("/{item_id}/publish", response_model=kind.out_model, name=f"publish_{name}")
    def publish_item(item_id: str, request: Request, db: DbDep, user: AuthorUser) -> Any:
        entity = load_editable(db, kind, item_id)
        publish(db, kind, entity, user)
        _audit(db, request, "publish", entity, user, {"version": entity.version})
        db.commit()
        return kind.serialise(entity)

    @router.post("/{item_id}/unpublish", response_model=kind.out_model, name=f"unpublish_{name}")
    def unpublish_item(item_id: str, request: Request, db: DbDep, user: AuthorUser) -> Any:
        entity = load_editable(db, kind, item_id)
        if entity.status != PUBLISHED:
            raise errors.conflict(f"Only a published {name} can be unpublished.")
        entity.status = "draft"
        touch(entity, user)
        _audit(db, request, "unpublish", entity, user, {"version": entity.version})
        db.commit()
        return kind.serialise(entity)

    @router.post(
        "/{item_id}/view",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        name=f"view_{name}",
    )
    def view_item(item_id: str, db: DbDep, user: AnyUser) -> Response:
        """Count one read.

        The increment is a single ``UPDATE`` so that two readers arriving
        together are both counted, and it leaves ``updated_at`` alone: a view is
        not an edit, and moving the concurrency token would make every open
        editor's next autosave conflict with a reader.
        """
        entity = load_visible(db, kind, user, item_id)
        db.execute(
            update(kind.model).where(kind.model.id == entity.id).values(view_count=kind.model.view_count + 1)
        )
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.delete(
        "/{item_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        name=f"archive_{name}",
    )
    def archive_item(item_id: str, request: Request, db: DbDep, user: AdminUser) -> Response:
        entity = load_editable(db, kind, item_id)
        entity.status = ARCHIVED
        touch(entity, user)
        _audit(db, request, "archive", entity, user, {"title": entity.title})
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get(
        "/{item_id}/revisions",
        response_model=list[RevisionSummaryOut],
        name=f"list_{name}_revisions",
    )
    def list_revisions(item_id: str, db: DbDep, user: AuthorUser) -> list[RevisionSummaryOut]:
        entity = load_editable(db, kind, item_id)
        return [
            RevisionSummaryOut(
                version=revision.version,
                published_at=revision.published_at,
                published_by=user_ref_out(revision.published_by),
            )
            for revision in entity.revisions
        ]

    @router.get("/{item_id}/revisions/{version}", response_model=None, name=f"read_{name}_revision")
    def read_revision(item_id: str, version: int, db: DbDep, user: AuthorUser) -> dict[str, Any]:
        entity = load_editable(db, kind, item_id)
        revision = db.scalars(
            select(kind.revision_model).where(
                kind.revision_model.owner_id == entity.id, kind.revision_model.version == version
            )
        ).one_or_none()
        if revision is None:
            raise errors.not_found("That revision does not exist.")
        return revision.document
