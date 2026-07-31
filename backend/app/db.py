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
    """Foreign keys are off by default in SQLite, which would quietly turn the
    cascade rules in ``models`` into decoration."""
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    from . import models  # noqa: F401  -- registers the mappers before create_all

    Base.metadata.create_all(engine)
