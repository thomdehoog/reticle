"""Database engine, session lifecycle and the shared column types.

SQLite is deliberate rather than a placeholder: Reticle serves one institute's
staff, the write volume is a handful of autosaves per minute, and a single file
is something ZMB's IT can back up without operating a database server. The ORM
layer keeps that reversible.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Engine, Text, TypeDecorator, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import get_settings


class Base(DeclarativeBase):
    pass


class UtcDateTime(TypeDecorator):
    """Store naive UTC, hand back aware UTC.

    SQLite has no timezone-aware type, so without this every value read back
    would be naive and would silently compare unequal to ``datetime.now(utc)``.
    Normalising at the column boundary means the rest of the application only
    ever deals in aware UTC instants, which is also what the wire format needs.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetimes must not reach the database")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


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
    return datetime.now(timezone.utc)


def build_engine(url: str) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


engine = build_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)


@event.listens_for(Engine, "connect")
def _configure_sqlite(dbapi_connection: Any, connection_record: Any) -> None:
    """The three settings that decide whether SQLite behaves like a database.

    All of them are per-connection or persistent defaults that SQLite gets wrong
    for a server, and all three have to be set here because there is nowhere
    else that every connection passes through.

    **Foreign keys are off by default**, which would quietly turn every
    ``ForeignKey`` and every ``ondelete="CASCADE"`` in ``models`` into
    decoration: orphaned steps would accumulate under deleted guides and nothing
    would say so.

    **The default journal blocks readers against the writer.** In the rollback
    journal a write takes the whole database, so an autosave — which the editor
    performs every few seconds while somebody types — stalls every colleague
    reading a guide at that moment. Write-ahead logging lets them proceed
    concurrently, which is the difference between a system that feels responsive
    at a bench and one that stutters whenever anybody is writing.

    **Synchronous stays FULL**, rather than the NORMAL usually paired with WAL.
    NORMAL trades a small window of durability on power loss for speed, and the
    speed is worth nothing here: this is a few writes a minute, and the thing
    being written is a safety procedure somebody is part-way through revising.

    ⚠️ WAL does not work on a network filesystem. If the database is ever moved
    onto an SMB or NFS share, this has to change and the move is a bad idea for
    other reasons too.

    The fourth thing here is not a pragma but belongs with them: SQLite's
    built-in ``lower()`` only folds A–Z. See ``_unicode_lower``.
    """
    if not dbapi_connection.__class__.__module__.startswith("sqlite3"):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=FULL")
    cursor.close()
    dbapi_connection.create_function("lower", 1, _unicode_lower, deterministic=True)


def _unicode_lower(value: Any) -> Any:
    """Replace SQLite's ``lower()``, which stops at Z.

    SQLite folds ASCII and leaves every other letter alone — ``lower('PRÄP')``
    is ``'prÄp'`` — because full Unicode folding would drag ICU into a library
    that fits on a microcontroller. Reasonable for SQLite; wrong here.

    It matters because SQLAlchemy renders ``ilike`` on SQLite as
    ``lower(a) LIKE lower(b)``, and every search in the application is an
    ``ilike``. Against a German corpus that means searching *Präparation*,
    *Färbung* or *Auflösung* in the case they appear in a title silently
    returns nothing, and "no results" is indistinguishable from "not written
    yet" — the reader goes and asks somebody instead.

    Overriding the built-in is supported and applies to every use of ``lower``
    on the connection. Python's ``str.lower`` is Unicode-aware, so the fix is
    the whole implementation. On PostgreSQL none of this exists: ``ILIKE`` is
    a real operator that folds by collation, and this function is never
    registered.
    """
    return value.lower() if isinstance(value, str) else value


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
