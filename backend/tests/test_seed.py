"""Seeding: the real ZMB category set, a bootstrap admin, one example guide —
and, on request, a demonstration dataset to click through."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Bullet, Category, Guide, GuideRevision, Media, Page, PageMedia, PageRevision, Step, StepMedia, Tag, User
from app.seed import DEMO_GUIDES, DEMO_PAGES, ZMB_CATEGORIES, SeedError, draw_placeholder, seed
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
    assert guide.time_required_min_minutes == 20
    assert guide.time_required_max_minutes == 30
    assert guide.tag_slugs == ["confocal", "getting-started"]
    assert [user.role for user in guide.contributors] == ["admin"]
    assert guide.category.name == "Light Microscopy"


def test_the_example_guide_has_several_steps_with_contiguous_numbering(seeded):
    steps = seeded.scalars(select(Step).order_by(Step.order_index)).all()

    assert len(steps) >= 4
    assert [s.order_index for s in steps] == list(range(len(steps)))
    assert all(s.title for s in steps)


def test_the_example_bullets_exercise_the_annotation_vocabulary(seeded):
    bullets = seeded.scalars(select(Bullet)).all()

    assert len(bullets) >= 8
    assert {b.icon for b in bullets if b.icon} == {"caution", "note", "reminder"}
    assert {"black", "red", "orange", "light_blue"} <= {b.color for b in bullets}
    assert {b.level for b in bullets} == {0, 1, 2}


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


def test_plain_seeding_creates_no_demo_content(seeded, media_root):
    assert seeded.scalars(select(Page)).all() == []
    assert seeded.scalars(select(Media)).all() == []
    assert all(not category.is_hidden for category in seeded.scalars(select(Category)))
    assert [user.role for user in seeded.scalars(select(User))] == ["admin"]
    assert not media_root.exists()


# ---------------------------------------------------------------- demo mode


@pytest.fixture()
def demo(db_session, monkeypatch):
    monkeypatch.setenv("RETICLE_ADMIN_EMAIL", "zmb.admin@zmb.uzh.ch")
    monkeypatch.setenv("RETICLE_ADMIN_PASSWORD", SEED_PASSWORD)
    monkeypatch.setenv("RETICLE_DEMO_PASSWORD", "Demo-Accounts-Passphrase-3")
    get_settings.cache_clear()
    report = seed(db_session, get_settings(), demo=True)
    db_session.info["report"] = report
    return db_session


def counts(session) -> dict[str, int]:
    models = (User, Category, Tag, Guide, GuideRevision, Step, Bullet, StepMedia, Media, Page, PageRevision, PageMedia)
    return {model.__name__: len(session.scalars(select(model)).all()) for model in models}


def test_demo_mode_is_idempotent(demo, media_root):
    before = counts(demo)
    files_before = sorted(path.name for path in media_root.rglob("*") if path.is_file())

    report = seed(demo, get_settings(), demo=True)

    assert report.created == []
    assert counts(demo) == before
    assert sorted(path.name for path in media_root.rglob("*") if path.is_file()) == files_before


def test_demo_mode_can_be_added_to_an_already_seeded_installation(seeded):
    report = seed(seeded, get_settings(), demo=True)

    assert "guide Setting Up a Tile Scan in LAS X" in report.created
    assert not [line for line in report.created if line.startswith("administrator")]
    assert len(seeded.scalars(select(Guide)).all()) == 1 + len(DEMO_GUIDES)


def test_the_demo_has_visible_categories_with_landing_pages_and_one_hidden_holding_category(demo):
    hidden = [category for category in demo.scalars(select(Category)) if category.is_hidden]
    landings = demo.scalars(select(Page).where(Page.is_landing.is_(True), Page.status == "published")).all()

    assert [category.name for category in hidden] == ["Confocal – hidden guides"]
    assert len(landings) >= 2
    for page in landings:
        assert page.category is not None and not page.category.is_hidden
        assert "```guidelist\ntags:" in page.body
    assert demo.scalars(select(Guide).where(Guide.category_id == hidden[0].id)).all(), "the holding category holds a guide"


def test_the_demo_guide_lists_resolve_to_published_guides(demo, as_role):
    """A landing page whose embedded list came back empty would make the demo
    look broken, so every ``guidelist`` block must actually find something."""
    import re

    viewer = as_role("viewer", "reader@zmb.uzh.ch")
    blocks = []
    for page in demo.scalars(select(Page).where(Page.status == "published")):
        blocks += re.findall(r"```guidelist\ntags: ([^\n]+)", page.body)

    assert len(blocks) >= 3
    for tags in blocks:
        listing = viewer.get("/api/guides", params={"tags": tags}).json()
        assert listing, tags
        assert all(entry["status"] == "published" for entry in listing)


def test_the_demo_has_several_tags_and_guides_in_every_state_a_tester_needs(demo):
    guides = demo.scalars(select(Guide)).all()
    bullets = demo.scalars(select(Bullet)).all()

    assert 3 <= len(DEMO_GUIDES) <= 4
    assert {guide.status for guide in guides} == {"published", "draft"}
    assert len(demo.scalars(select(Tag)).all()) >= 5
    assert {bullet.color for bullet in bullets} == {
        "black", "red", "orange", "yellow", "green", "light_blue", "blue", "violet",
    }
    assert {bullet.icon for bullet in bullets} == {None, "note", "caution", "reminder"}
    assert {bullet.level for bullet in bullets} == {0, 1, 2}
    assert any(guide.time_required_max_minutes is None and guide.time_required_min_minutes for guide in guides)


def test_a_published_demo_guide_carries_generated_images_with_annotations(demo, media_root, as_role):
    from io import BytesIO

    from PIL import Image

    guide = demo.scalars(select(Guide).where(Guide.slug == "setting-up-a-tile-scan-in-las-x")).one()
    links = [link for step in guide.steps for link in step.media_links]
    shapes = {annotation["shape"] for link in links for annotation in link.annotations}

    assert guide.status == "published"
    assert len(links) >= 3
    assert max(len(step.media_links) for step in guide.steps) >= 2
    assert shapes == {"rectangle", "ellipse", "arrow"}
    assert all(link.alt for link in links)

    viewer = as_role("viewer", "reader@zmb.uzh.ch")
    body = viewer.get(f"/api/guides/{guide.slug}").json()
    first = body["steps"][0]["media"][0]
    assert first["kind"] == "image" and first["annotations"]
    image = viewer.get(first["url"])
    assert image.status_code == 200
    assert Image.open(BytesIO(image.content)).size == (960, 600)
    assert viewer.get(f"/api/guides/{guide.slug}/pdf").status_code == 200
    assert len(guide.revisions) == 1
    assert guide.revisions[0].document["steps"][0]["media"][0]["annotations"]


def test_demo_pages_cover_landing_standalone_draft_hero_and_body_image(demo, as_role):
    pages = {page.slug: page for page in demo.scalars(select(Page))}
    standalone = pages["booking-rules-and-fair-use"]
    landing = pages["light-microscopy"]
    draft = pages["image-analysis"]

    assert len(pages) == len(DEMO_PAGES)
    assert standalone.category_id is None and not standalone.is_landing and standalone.status == "published"
    assert draft.status == "draft" and draft.is_landing
    assert landing.hero_media_id is not None
    assert len(landing.media_links) == 1
    assert f"/api/media/{landing.media_links[0].media_id}" in landing.body
    assert "{figure}" not in landing.body
    assert len(demo.scalars(select(PageRevision)).all()) == 3

    viewer = as_role("viewer", "reader@zmb.uzh.ch")
    assert viewer.get(f"/api/categories/{landing.category_id}/page").json()["slug"] == "light-microscopy"
    assert viewer.get(f"/api/categories/{draft.category_id}/page").json() is None
    assert viewer.get(f"/api/media/{landing.hero_media_id}").status_code == 200
    assert viewer.get(f"/api/media/{landing.media_links[0].media_id}").status_code == 200
    assert {page["slug"] for page in viewer.get("/api/pages").json()} == {
        "booking-rules-and-fair-use", "light-microscopy", "sample-preparation",
    }


def test_demo_accounts_exist_only_when_a_password_was_supplied(demo, db_session, client_factory):
    accounts = {user.email: user.role for user in demo.scalars(select(User))}

    assert accounts == {
        "zmb.admin@zmb.uzh.ch": "admin",
        "demo.author@zmb.uzh.ch": "author",
        "demo.viewer@zmb.uzh.ch": "viewer",
    }
    assert client_factory().login("demo.viewer@zmb.uzh.ch", "Demo-Accounts-Passphrase-3").status_code == 200
    assert "viewer account demo.viewer@zmb.uzh.ch" in demo.info["report"].created


def test_without_a_demo_password_no_demo_account_is_created(seeded):
    seed(seeded, get_settings(), demo=True)

    assert [user.role for user in seeded.scalars(select(User))] == ["admin"]


def test_a_weak_demo_password_is_refused(db_session, monkeypatch):
    monkeypatch.setenv("RETICLE_ADMIN_PASSWORD", SEED_PASSWORD)
    monkeypatch.setenv("RETICLE_DEMO_PASSWORD", "demo")
    get_settings.cache_clear()

    with pytest.raises(SeedError, match="RETICLE_DEMO_PASSWORD"):
        seed(db_session, get_settings(), demo=True)

    assert db_session.scalars(select(User)).all() == []


def test_a_category_that_already_has_a_landing_page_keeps_it(seeded, as_role):
    """An operator trying the demo on an installation that has real content
    must not get a second landing page, or an error, for a category of theirs."""
    author = as_role("author", "writer@zmb.uzh.ch")
    category = seeded.scalars(select(Category).where(Category.name == "Sample Preparation")).one()
    existing = author.post("/api/pages", json={"title": "Our own landing page", "categoryId": category.id, "isLanding": True})
    assert existing.status_code == 201

    report = seed(seeded, get_settings(), demo=True)

    assert "page Sample Preparation" not in report.created
    landings = seeded.scalars(select(Page).where(Page.category_id == category.id, Page.is_landing.is_(True))).all()
    assert [page.title for page in landings] == ["Our own landing page"]


def test_placeholder_screenshots_are_drawn_locally_and_are_valid_pngs():
    from io import BytesIO

    from PIL import Image

    from app.seed import ShapeSpec

    payload = draw_placeholder("LAS X", (ShapeSpec("rectangle", "red", 0.5, 0.1, 0.2, 0.1), ShapeSpec("arrow", "red", 0, 0, 1, 1)))

    image = Image.open(BytesIO(payload))
    assert image.format == "PNG"
    assert image.size == (960, 600)
    assert image.getpixel((5, 300)) == (13, 17, 23), "a dark background, like the software it stands in for"
