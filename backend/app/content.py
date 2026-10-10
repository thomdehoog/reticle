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

Visibility has two halves. *Which items* a caller may see is the status rule in
:func:`visible_to`. *Which text* of an item they are given is the other half: a
viewer is only ever served the snapshot written by the last publish, never the
working copy the editor is saving into, and :func:`read` and
:func:`published_statement` are where that is decided. ``published`` holds the
snapshot side; this module chooses between the two.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import ColumnElement, Select, or_, select, update
from sqlalchemy.orm import Session as DbSession

from . import audit, errors
from .auth import AdminUser, AnyUser, AuthorUser, DbDep, client_address
from .db import utcnow
from .models import ARCHIVED, PUBLISHED, User
from .schemas import ContentView, RevisionSummaryOut, Wire, snapshot, user_ref_out


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
    # The published side, from ``published``: the projection table, how to
    # write and withdraw it, how to serve a snapshot, how to tell a snapshot
    # from a working copy, and how to put a snapshot back as the working copy.
    projection_model: type
    project: Callable[[DbSession, Any, Any], None]
    unproject: Callable[[DbSession, str], None]
    from_snapshot: Callable[..., Wire]
    fingerprint: Callable[[dict[str, Any]], Any]
    restore: Callable[[DbSession, Any, dict[str, Any]], None]
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


def serves_published(user: User, view: ContentView | None = None) -> bool:
    """Whether this caller is to be given the snapshot rather than the working copy.

    A viewer always is; there is no parameter by which a viewer can ask for
    anything else. An author or an administrator gets the working copy unless
    they ask to see what readers see.
    """
    return user.role == "viewer" or view == "published"


def published_statement(kind: ContentKind, *columns: Any) -> Select:
    """Select from what is published *right now*, joined to its projection.

    The status test is repeated here although a projection row is removed when
    its item is unpublished or archived. A writer that sets a status without
    going through this module — the importer does, to keep vendor dates — then
    leaves at worst a row nobody can reach, instead of a withdrawn guide that
    readers can still list.
    """
    projection = kind.projection_model
    return (
        select(kind.model, projection, *columns)
        .join(projection, projection.owner_id == kind.model.id)
        .where(kind.model.status == PUBLISHED)
    )


def load_published(db: DbSession, kind: ContentKind, key: str) -> tuple[Any, Any]:
    """The item and the snapshot readers are served, by identifier or slug."""
    statement = (
        select(kind.model, kind.revision_model)
        .join(kind.projection_model, kind.projection_model.owner_id == kind.model.id)
        .join(kind.revision_model, kind.revision_model.id == kind.projection_model.revision_id)
        .where(or_(kind.model.id == key, kind.model.slug == key), kind.model.status == PUBLISHED)
    )
    found = db.execute(statement).one_or_none()
    if found is None:
        raise kind.missing()
    return found[0], found[1]


def read(db: DbSession, kind: ContentKind, user: User, key: str, view: ContentView | None = None) -> Wire:
    """One guide or page, as this caller is entitled to read it."""
    if serves_published(user, view):
        entity, revision = load_published(db, kind, key)
        return kind.from_snapshot(revision.document, entity, reveal_changes=user.role != "viewer")
    return kind.serialise(load_visible(db, kind, user, key))


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
    """Write the snapshot of a publish, and make it what readers are served.

    The two happen together or not at all: the snapshot row and its projection
    go into the caller's transaction, so there is no moment at which a reader's
    listing describes one version and the guide behind it is another. Everything
    that publishes ends here — the publish endpoint, the demo seed and the
    importer — which is why the projection is written here and not by any of
    them.
    """
    entity.snapshot_updated_at = entity.updated_at
    revision = kind.revision_model(
        owner_id=entity.id,
        version=entity.version,
        published_at=now,
        published_by_id=actor.id,
        document=snapshot(kind.serialise(entity)),
    )
    db.add(revision)
    db.flush()
    kind.project(db, entity, revision)


def current_snapshot(db: DbSession, kind: ContentKind, entity: Any) -> Any | None:
    """The revision readers are being served, if the item is published."""
    if entity.status != PUBLISHED:
        return None
    return db.scalars(
        select(kind.revision_model)
        .join(kind.projection_model, kind.projection_model.revision_id == kind.revision_model.id)
        .where(kind.projection_model.owner_id == entity.id)
    ).one_or_none()


def settle_changes(db: DbSession, kind: ContentKind, entity: Any) -> Any:
    """After a save, decide whether the working copy still differs from the snapshot.

    A save always moves ``updated_at``, which on its own would mark every saved
    guide as changed. So the saved copy is compared with what readers have, and
    when they read the same the marker is brought up to date. The comparison is
    made on the rows as stored, reloaded in the kind's usual fixed number of
    queries, rather than on the request body: what counts is what was written.

    Returns the reloaded entity. Only published content pays for any of this.
    """
    revision = current_snapshot(db, kind, entity)
    if revision is None:
        return entity
    db.flush()
    stored = db.scalars(
        select(kind.model)
        .where(kind.model.id == entity.id)
        .options(*kind.eager())
        .execution_options(populate_existing=True)
    ).one()
    if kind.fingerprint(snapshot(kind.serialise(stored))) == kind.fingerprint(revision.document):
        stored.snapshot_updated_at = stored.updated_at
    return stored


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
        kind.unproject(db, entity.id)
        touch(entity, user)
        _audit(db, request, "unpublish", entity, user, {"version": entity.version})
        db.commit()
        return kind.serialise(entity)

    @router.post("/{item_id}/revert", response_model=kind.out_model, name=f"revert_{name}")
    def revert_item(item_id: str, request: Request, db: DbDep, user: AuthorUser) -> Any:
        """Discard unpublished changes: make the working copy the published version again.

        Only something currently published has a version to go back to. A draft
        that was published once and then withdrawn is refused rather than
        restored from its last snapshot — readers are being shown nothing, so
        "what readers see" is not a document — and its old versions are still
        there to read under ``/revisions``.
        """
        entity = load_editable(db, kind, item_id)
        revision = current_snapshot(db, kind, entity)
        if revision is None:
            raise errors.conflict(
                f"Only a published {name} has a published version to go back to. "
                "Its earlier versions are in the history."
            )
        kind.restore(db, entity, revision.document)
        touch(entity, user)
        entity.snapshot_updated_at = entity.updated_at
        _audit(db, request, "revert", entity, user, {"version": entity.version})
        db.commit()
        return kind.serialise(load_editable(db, kind, item_id))

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
        kind.unproject(db, entity.id)
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

    @router.get("/{item_id}/revisions/{version}", response_model=kind.out_model, name=f"read_{name}_revision")
    def read_revision(item_id: str, version: int, db: DbDep, user: AuthorUser) -> Any:
        entity = load_editable(db, kind, item_id)
        revision = db.scalars(
            select(kind.revision_model).where(
                kind.revision_model.owner_id == entity.id, kind.revision_model.version == version
            )
        ).one_or_none()
        if revision is None:
            raise errors.not_found("That revision does not exist.")
        # As it was written, apart from fields the contract has gained since.
        return kind.from_snapshot(revision.document)
