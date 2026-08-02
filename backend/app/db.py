"""The connection to the database, and the two column types everything reuses.

Three things live here, and a newcomer will not have met the first two.

A **session** in this file is not a login — it is SQLAlchemy's word for one
conversation with the database. A request opens one, does its reading and
writing, and closes it at the end; ``get_db`` is what hands one to an endpoint
and guarantees it is closed however the request ends.

The **column types** are two small adapters used by nearly every table.
``UtcDateTime`` makes sure every instant is stored and read back as UTC: the
column is a plain ``TIMESTAMP``, so a value that comes back without a zone
silently compares unequal to the one that went in — and instants are what decide
whether an editor's copy of a guide is stale. ``JsonDocument`` stores a whole
published snapshot as text, so an old revision still reads correctly after the
schema around it has changed.

**The database is PostgreSQL**, one per facility, and nothing else. That is what
``deploy/provision-facility.sh`` creates, what the suite runs against and what
the settings below assume.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Engine, Text, TypeDecorator, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import get_settings


class Base(DeclarativeBase):
    pass


class UtcDateTime(TypeDecorator):
    """Store naive UTC, hand back aware UTC.

    The column is ``TIMESTAMP WITHOUT TIME ZONE``, so without this every value
    read back would be naive and would silently compare unequal to
    ``datetime.now(utc)``. Normalising at the column boundary means the rest of
    the application only ever deals in aware UTC instants, which is also what
    the wire format needs.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetimes must not reach the database")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class JsonDocument(TypeDecorator):
    """A JSON blob kept as text so a revision snapshot survives schema drift."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def process_result_value(self, value: str | None, dialect: Any) -> Any:
        if value is None:
            return None
        return json.loads(value)


def utcnow() -> datetime:
    return datetime.now(UTC)


def escape_like(term: str) -> str:
    """Make a search term mean itself inside a ``LIKE`` pattern.

    ``%`` and ``_`` are wildcards, so a reader searching for ``100_x`` would
    otherwise match anything with ``100`` and one more character, and a search
    for ``%`` would return the whole corpus. The backslash has to be escaped
    first, because it is the escape character every caller passes as
    ``escape="\\\\"``.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_engine(url: str) -> Engine:
    """Open the connection pool.

    Both pool settings are the difference between a PostgreSQL restart being
    invisible and being an outage. A pooled connection whose far end has gone
    away looks fine until it is used; without ``pool_pre_ping`` every request
    that picks up a dead one fails, and the readiness probe flaps, until the
    pool happens to churn. ``pool_recycle`` covers the quieter version of the
    same thing - a firewall or NAT that drops an idle connection without telling
    either side.
    """
    return create_engine(url, future=True, pool_pre_ping=True, pool_recycle=1800)


engine = build_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db(target_engine: Engine | None = None) -> None:
    """Bring the database up to the current schema, whatever state it is in.

    Three cases, and the middle one is the reason this is not simply
    ``alembic upgrade head``:

    1. **Empty.** Migrations run from the beginning. Ordinary first install.
    2. **Has tables but no ``alembic_version``.** A database created by the
       ``create_all`` this function used to call, before migrations existed.
       Running migrations against it would try to create tables that are
       already there and fail. It is stamped instead — recorded as being at the
       current revision — which is correct because the schema-equivalence test
       proves ``create_all`` and ``upgrade head`` produce the same thing.
    3. **Already stamped.** Any pending migrations run; usually none.

    Called on startup so a deployment that forgets the migration step does not
    serve traffic against last release's schema. That is safe for the additive
    migrations this project writes, and it is the right trade for an
    installation whose operator is a microscopy facility rather than a DBA.

    ⚠️ A destructive migration should not run itself on startup. When one is
    written, run it deliberately and take a backup first — ``MAINTENANCE.md``.
    """
    from alembic import command
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import inspect

    from . import models  # noqa: F401  -- registers the mappers

    target = target_engine or engine
    config = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    config.attributes["connection"] = target

    with target.connect() as connection:
        stamped = MigrationContext.configure(connection).get_current_revision()
        existing = set(inspect(connection).get_table_names()) - {"alembic_version"}

    if existing and stamped is None:
        Base.metadata.create_all(target)  # fills in anything a partial install missed
        command.stamp(config, "head")
        return

    command.upgrade(config, "head")
