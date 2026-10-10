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
from typing import Any

from fastapi import Request
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


SQLITE_BUSY_TIMEOUT_MS = 5000
"""How long a writer waits for the lock before giving up.

SQLite admits one writer at a time. With more than one uvicorn worker two
autosaves can arrive together, and without a timeout the second fails at once
with "database is locked"; five seconds is far longer than any write here takes
and short enough that a genuinely stuck writer still surfaces as an error.
"""

WRITE_INTENT = "reticle_write_intent"

REQUEST_THREADS = 40
"""How many requests can be inside a handler at once, per worker.

Every synchronous endpoint runs on the server's thread pool, and this is that
pool's size: ``main`` sets it at start-up from this constant, so the number the
connection pool is sized against is the number actually in force.
"""

POOL_SIZE = 10
POOL_OVERFLOW = REQUEST_THREADS
"""Connections kept open, and how many more may be opened under load.

A request holds at most one connection, so the most that can be wanted at once
is one per request thread, plus the few that an upload holds between two trips
to the thread pool. SQLAlchemy's default — five kept, ten more on demand — is
smaller than that, which made the pool itself a queue: sixty slow requests
left forty threads waiting on fifteen connections, and the ones still waiting
after thirty seconds failed with "QueuePool limit reached", the health check
among them. With kept-plus-overflow above the thread count there is always a
connection for a thread that has one to ask for, and what bounds the load is
the thread pool, which answers in order instead of timing out.

Only ten are *kept*, because an idle SQLite connection is not free either: each
carries its own page cache. The rest are opened for a burst and closed after it.
"""

ENGINE_OPTIONS: dict[str, Any] = {
    "future": True,
    # A failed statement is logged with its SQL and never with its values. The
    # values are what people wrote — bullet text, page bodies — and, on the user
    # table, password hashes; none of that belongs in a log file that is kept
    # for a year and read by whoever is on call.
    "hide_parameters": True,
}


def is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def is_memory_sqlite(url: str) -> bool:
    return is_sqlite(url) and (url in {"sqlite://", "sqlite:///"} or ":memory:" in url)


def build_engine(url: str) -> Engine:
    """Create the engine, with SQLite tuned for more than one process.

    Three things are set on every SQLite connection, and they only make sense
    together:

    * **WAL** lets readers carry on while a writer holds the lock, which is the
      difference between a guide opening instantly and a guide waiting for a
      colleague's autosave.
    * **A busy timeout** makes a second writer queue instead of failing.
    * **The driver's implicit transactions are switched off**, and Reticle
      issues ``BEGIN`` itself. A request that will write says so up front with
      ``BEGIN IMMEDIATE``. The default deferred transaction reads first and
      asks for the write lock later, and under WAL that upgrade is refused
      outright — not queued, the busy timeout does not apply — whenever another
      process committed in between. Every mutating request reads the session
      row before it writes anything, so with two workers that refusal is not a
      corner case, it is two people autosaving at the same time.

    None of this applies to PostgreSQL, which gets a plain engine.
    """
    if not is_sqlite(url):
        return create_engine(url, pool_size=POOL_SIZE, max_overflow=POOL_OVERFLOW, **ENGINE_OPTIONS)

    persistent = not is_memory_sqlite(url)
    # An in-memory database exists per connection, so it keeps SQLAlchemy's own
    # choice of pool for it (one shared connection); a pool of several would be
    # several empty databases.
    pooling = {"pool_size": POOL_SIZE, "max_overflow": POOL_OVERFLOW} if persistent else {}
    engine = create_engine(url, connect_args={"check_same_thread": False}, **pooling, **ENGINE_OPTIONS)

    @event.listens_for(engine, "connect")
    def _tune_sqlite(dbapi_connection: Any, connection_record: Any) -> None:
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        if persistent:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _begin(connection: Any) -> None:
        immediate = connection.get_execution_options().get(WRITE_INTENT, False)
        connection.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")

    return engine


def session_factories(bound: Engine) -> tuple[sessionmaker[Session], sessionmaker[Session]]:
    """A factory for sessions that will write, and one for sessions that only read.

    Both share one connection pool; the only difference is the execution option
    that ``build_engine`` turns into ``BEGIN IMMEDIATE``.
    """
    writer = sessionmaker(bind=bound.execution_options(**{WRITE_INTENT: True}), autoflush=False, future=True)
    reader = sessionmaker(bind=bound, autoflush=False, future=True)
    return writer, reader


engine = build_engine(get_settings().database_url)
SessionLocal, ReadSessionLocal = session_factories(engine)


def configure(url: str) -> Engine:
    """Point the application at a different database.

    The engine is built at import time because that is what a server wants;
    this exists for the callers that need to choose afterwards — the migration
    tests, and a script that works on a copy.
    """
    global engine, SessionLocal, ReadSessionLocal
    engine.dispose()
    engine = build_engine(url)
    SessionLocal, ReadSessionLocal = session_factories(engine)
    return engine


@event.listens_for(Engine, "connect")
def _configure_sqlite(dbapi_connection: Any, connection_record: Any) -> None:
    """Foreign keys are off by default in SQLite, which would quietly turn the
    cascade rules in ``models`` into decoration."""
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_db(request: Request) -> Iterator[Session]:
    """One session per request, opened for writing only when the verb can write."""
    factory = ReadSessionLocal if request.method in READ_ONLY_METHODS else SessionLocal
    session = factory()
    try:
        yield session
    finally:
        session.close()
