"""Seeding: the real ZMB category set, a bootstrap admin and one example guide."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Bullet, Category, Guide, GuideRevision, Step, User
from app.seed import ZMB_CATEGORIES, SeedError, seed
from app.security import verify_password
from app.settings import get_settings

SEED_PASSWORD = "Bootstrap-Admin-Passphrase-2"


@pytest.fixture()
def seeded(db_session, monkeypatch):
    monkeypatch.setenv("RETICLE_ADMIN_EMAIL", "zmb.admin@zmb.uzh.ch")
    monkeypatch.setenv("RETICLE_ADMIN_PASSWORD", SEED_PASSWORD)
    get_settings.cache_clear()
    seed(db_session, get_settings())
    return db_session


def test_the_eight_zmb_categories_are_seeded_in_order(seeded):
    categories = seeded.scalars(select(Category).order_by(Category.order_index)).all()

    assert [c.name for c in categories] == [
        "Basics, Access and IT",
        "Sample Preparation",
        "Light Microscopy",
        "Electron Microscopy",
        "Image Analysis",
        "Internal Guides",
        "CryoEM",
        "Spatial Biology",
    ]
    assert [c.order_index for c in categories] == list(range(8))
    assert all(c.parent_id is None for c in categories)


def test_sample_preparation_carries_its_scope_note(seeded):
    entry = seeded.scalars(select(Category).where(Category.name == "Sample Preparation")).one()

    assert "light microscopy" in entry.description.lower()


def test_category_slugs_are_url_safe(seeded):
    slugs = seeded.scalars(select(Category.slug).order_by(Category.order_index)).all()

    assert slugs[0] == "basics-access-and-it"
    assert slugs[6] == "cryoem"
    assert all(slug == slug.lower() and " " not in slug and "," not in slug for slug in slugs)


def test_the_declared_category_set_is_the_one_seeded(seeded):
    assert [name for name, _ in ZMB_CATEGORIES] == [c.name for c in seeded.scalars(select(Category).order_by(Category.order_index))]


def test_the_admin_password_comes_from_the_environment(seeded):
    admin = seeded.scalars(select(User).where(User.role == "admin")).one()

    assert admin.email == "zmb.admin@zmb.uzh.ch"
    assert verify_password(admin.password_hash, SEED_PASSWORD)
    assert admin.password_hash.startswith("$argon2id$")


def test_seeding_without_an_admin_password_refuses_rather_than_inventing_one(db_session, monkeypatch):
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
    before = (
        seeded.scalars(select(Category)).all().__len__(),
        seeded.scalars(select(Guide)).all().__len__(),
        seeded.scalars(select(User)).all().__len__(),
    )

    seed(seeded, get_settings())

    after = (
        seeded.scalars(select(Category)).all().__len__(),
        seeded.scalars(select(Guide)).all().__len__(),
        seeded.scalars(select(User)).all().__len__(),
    )
    assert before == after


def test_reseeding_does_not_reset_a_changed_admin_password(seeded):
    admin = seeded.scalars(select(User).where(User.role == "admin")).one()
    admin.password_hash = "$argon2id$changed-by-the-operator"
    seeded.commit()

    seed(seeded, get_settings())

    assert seeded.scalars(select(User).where(User.role == "admin")).one().password_hash == "$argon2id$changed-by-the-operator"


def test_the_example_guide_is_published_and_richly_annotated(seeded):
    guide = seeded.scalars(select(Guide)).one()

    assert guide.status == "published"
    assert guide.version == 1
    assert guide.published_at is not None
    assert guide.summary
    assert guide.introduction and guide.conclusion
    assert guide.time_required_minutes and guide.time_required_minutes > 0
    assert guide.category.name == "Light Microscopy"


def test_the_example_guide_has_several_steps_with_contiguous_numbering(seeded):
    steps = seeded.scalars(select(Step).order_by(Step.order_index)).all()

    assert len(steps) >= 4
    assert [s.order_index for s in steps] == list(range(len(steps)))
    assert all(s.title for s in steps)


def test_the_example_bullets_exercise_the_annotation_vocabulary(seeded):
    bullets = seeded.scalars(select(Bullet)).all()

    assert len(bullets) >= 8
    assert {"caution", "warning", "note"} <= {b.icon for b in bullets if b.icon}
    assert {"black", "red", "orange"} <= {b.color for b in bullets}
    assert max(b.level for b in bullets) >= 1


def test_seeding_records_the_publish_snapshot(seeded):
    revision = seeded.scalars(select(GuideRevision)).one()

    assert revision.version == 1
    assert revision.document["title"] == seeded.scalars(select(Guide)).one().title
    assert len(revision.document["steps"]) >= 4


def test_the_seeded_guide_is_immediately_readable_by_a_viewer(seeded, as_role):
    client = as_role("viewer", "reader@zmb.uzh.ch")

    listing = client.get("/api/guides").json()

    assert len(listing) == 1
    assert listing[0]["stepCount"] >= 4
    assert client.get(f"/api/guides/{listing[0]['slug']}").status_code == 200
