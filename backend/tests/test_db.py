"""The three pragmas, and why each one is worth a test.

SQLite's defaults are chosen for a program embedded in a phone, not for a
server several people are reading while one of them writes. All three settings
below are corrections to those defaults, all three are applied per connection,
and all three fail *silently* if the listener stops firing — foreign keys become
decoration, a write locks out every reader, and durability quietly weakens.

Nothing else in the suite would notice. These tests would.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import build_engine


def pragma(engine, name):
    with engine.connect() as connection:
        return connection.execute(text(f"PRAGMA {name}")).scalar()


@pytest.fixture
def on_disk(tmp_path):
    """A real file. The in-memory database the rest of the suite uses cannot
    show journal behaviour, because there is no journal to write."""
    return build_engine(f"sqlite:///{tmp_path / 'reticle.db'}")


def test_foreign_keys_are_enforced_rather_than_declared(on_disk):
    assert pragma(on_disk, "foreign_keys") == 1


def test_a_row_pointing_at_a_guide_that_does_not_exist_is_refused(on_disk):
    """The declaration proved by its effect: without the pragma this inserts
    happily and the orphan is discovered months later by a page that crashes."""
    from app import models

    models.Base.metadata.create_all(on_disk)

    with Session(on_disk) as session:
        session.add(models.Step(guide_id="01NOSUCHGUIDE", title="Orphan"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_readers_are_not_blocked_by_the_autosave(on_disk):
    """Write-ahead logging is the difference between a colleague's page loading
    while somebody edits and it stalling until they stop typing."""
    assert pragma(on_disk, "journal_mode") == "wal"


def test_durability_is_not_traded_away_for_speed(on_disk):
    """2 is FULL. The usual pairing with WAL is NORMAL, which loses recent
    commits on power loss in exchange for throughput this application will
    never need — a few writes a minute, each one a safety procedure."""
    assert pragma(on_disk, "synchronous") == 2


def test_an_in_memory_database_is_not_broken_by_asking_for_wal(tmp_path):
    """WAL needs a file to put the log beside, so SQLite declines it in memory.
    Worth pinning: the whole test suite runs in memory, and a listener that
    raised instead of being declined would take every test with it."""
    memory = build_engine("sqlite://")

    assert pragma(memory, "journal_mode") == "memory"
    assert pragma(memory, "foreign_keys") == 1


def test_a_postgres_url_does_not_get_sqlite_pragmas(monkeypatch):
    """The listener is registered against every Engine, so it has to recognise
    connections it must keep its hands off. This matters the day the database
    moves; a stray ``PRAGMA`` would fail at connect time, before any test runs."""
    from app import db

    executed = []

    class NotSqlite:
        pass

    NotSqlite.__module__ = "psycopg.connection"

    class Recorder(NotSqlite):
        def cursor(self):  # pragma: no cover -- must never be called
            executed.append("cursor")
            raise AssertionError("pragmas were sent to a non-SQLite connection")

    db._configure_sqlite(Recorder(), None)

    assert executed == []
