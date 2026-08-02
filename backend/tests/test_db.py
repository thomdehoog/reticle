"""The engine, and the guarantee every relationship in the schema rests on.

Two things here, and both fail silently rather than loudly. A pool that hands
out a connection whose server has been restarted underneath it fails one request
per dead connection, which looks like a flapping readiness probe rather than a
pool setting. And a foreign key that is declared but not enforced is not a bug
anybody sees on the day it is introduced: orphaned steps accumulate under
deleted guides, and the discovery is a page that crashes months later.

Nothing else in the suite would notice either. These tests would.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import build_engine

DATABASE_URL = "postgresql+psycopg://reticle:secret@localhost/reticle"


def test_a_pooled_connection_is_checked_before_it_is_used():
    """``pool_pre_ping`` is the difference between a database restart being
    invisible and being an outage: without it every request that picks up a
    connection the server has already dropped fails, until the pool churns."""
    engine = build_engine(DATABASE_URL)

    assert engine.pool._pre_ping is True


def test_an_idle_connection_is_not_kept_indefinitely():
    """The quieter version of the same failure — a firewall or NAT dropping an
    idle connection without telling either side."""
    engine = build_engine(DATABASE_URL)

    assert engine.pool._recycle == 1800


def test_a_row_pointing_at_a_guide_that_does_not_exist_is_refused(db_session):
    """Every ``ondelete="CASCADE"`` in ``models`` is worth what the database
    enforces and nothing more."""
    from app import models

    db_session.add(models.Step(guide_id="01NOSUCHGUIDE", title="Orphan"))

    with pytest.raises(IntegrityError):
        db_session.commit()
