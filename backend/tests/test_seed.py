"""Seeding: a bootstrap administrator, and deliberately nothing else.

What is asserted here is mostly an absence, which is unusual enough to say why.
The seeder used to create nine sections named for ZMB's, each with a sentence
describing it, a published landing page, and a worked example guide naming ZMB's
booking calendar and its 405 nm laser — none of it written by anyone who works
there, all of it planted by `python -m app.seed` on every deployment. After a
migration it was actively misleading: the real `Light Micrscopy` arrived from
the vendor and stood beside a `Light Microscopy` this repository had invented.

So the tests below pin the emptiness in place. A future change that makes
seeding "more useful" by adding content is the change they exist to stop.
Demonstration content belongs in `tools/demo_corpus.py`, which says outright
that it is not ZMB's.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Category, Guide, Media, Page, Tag, User
from app.security import verify_password
from app.seed import SeedError, seed
from app.settings import get_settings

SEED_PASSWORD = "Bootstrap-Admin-Passphrase-2"


@pytest.fixture()
def seeded(db_session, monkeypatch):
    monkeypatch.setenv("RETICLE_ADMIN_EMAIL", "zmb.admin@zmb.uzh.ch")
    monkeypatch.setenv("RETICLE_ADMIN_PASSWORD", SEED_PASSWORD)
    get_settings.cache_clear()
    seed(db_session, get_settings())
    return db_session


def test_the_admin_password_comes_from_the_environment(seeded):
    admin = seeded.scalars(select(User).where(User.role == "admin")).one()

    assert admin.email == "zmb.admin@zmb.uzh.ch"
    assert verify_password(admin.password_hash, SEED_PASSWORD)
    assert admin.password_hash.startswith("$argon2id$")


def test_the_administrator_is_the_only_account(seeded):
    assert [user.role for user in seeded.scalars(select(User)).all()] == ["admin"]


def test_seeding_writes_no_content_of_any_kind(seeded):
    """A facility's sections are the facility's, and its guides are its own.

    The migration brings the real ones across with their own words and
    pictures; an installation with no site to import from gets them from
    whoever runs it. Either way this file has nothing true to say about them.
    """
    for model in (Category, Guide, Page, Tag, Media):
        assert seeded.scalars(select(model)).all() == []


def test_seeding_without_an_admin_password_refuses_rather_than_inventing_one(
    db_session, monkeypatch
):
    """A hardcoded fallback would ship a known credential into production."""
    monkeypatch.delenv("RETICLE_ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("RETICLE_ADMIN_EMAIL", "zmb.admin@zmb.uzh.ch")
    get_settings.cache_clear()

    with pytest.raises(SeedError, match="RETICLE_ADMIN_PASSWORD"):
        seed(db_session, get_settings())

    assert db_session.scalars(select(User)).all() == []


def test_seeding_rejects_a_weak_admin_password(db_session, monkeypatch):
    monkeypatch.setenv("RETICLE_ADMIN_EMAIL", "zmb.admin@zmb.uzh.ch")
    monkeypatch.setenv("RETICLE_ADMIN_PASSWORD", "admin")
    get_settings.cache_clear()

    with pytest.raises(SeedError):
        seed(db_session, get_settings())


def test_seeding_twice_changes_nothing(seeded):
    """It runs on every deployment, so a second run has to be a no-op."""
    before = len(seeded.scalars(select(User)).all())

    seed(seeded, get_settings())

    assert len(seeded.scalars(select(User)).all()) == before


def test_reseeding_does_not_reset_a_changed_admin_password(seeded):
    admin = seeded.scalars(select(User).where(User.role == "admin")).one()
    admin.password_hash = "$argon2id$changed-by-the-operator"
    seeded.commit()

    seed(seeded, get_settings())

    assert (
        seeded.scalars(select(User).where(User.role == "admin")).one().password_hash
        == "$argon2id$changed-by-the-operator"
    )
