"""Tags: the index the whole site is navigated by.

A guide sits in one category and carries many tags, and the wiki pages that
readers actually browse are lists filtered by tag. That makes every failure here
a navigation failure rather than a cosmetic one: a tag silently re-spelled on
save splits one instrument's guides into two headings that neither lists them
all, a tag counted against content the caller cannot see turns a link on the
busiest page into an empty result, and a filter that means "any of these"
instead of "all of these" turns a specific heading into an undifferentiated
dump of the corpus.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Tag

from .conftest import create_guide, document_from


def save_tags(client, guide: dict, tags: list[str]):
    return client.put(f"/api/guides/{guide['id']}", json=document_from(guide, tags=tags))


def tagged_guide(client, category_id: str, tags: list[str], title: str = "Tagged Guide") -> dict:
    guide = create_guide(client, category_id, title)
    response = save_tags(client, guide, tags)
    assert response.status_code == 200, response.text
    return response.json()


def test_saving_a_guide_creates_the_tags_it_names(author, category, db_session):
    """Authors are not administrators of a taxonomy. Making them register a tag
    before they can use it is how a corpus ends up with none."""
    saved = tagged_guide(author, category.id, ["confocal", "stellaris"])

    assert saved["tags"] == ["confocal", "stellaris"]
    assert {tag.slug for tag in db_session.scalars(select(Tag))} == {"confocal", "stellaris"}


def test_a_minted_tag_gets_a_readable_display_name(author, category, db_session):
    tagged_guide(author, category.id, ["live-cell-imaging"])

    tag = db_session.scalars(select(Tag).where(Tag.slug == "live-cell-imaging")).one()
    assert tag.name == "live cell imaging"


def test_the_authored_tag_order_is_the_order_that_comes_back(author, category):
    saved = tagged_guide(author, category.id, ["stellaris", "confocal", "startup"])

    assert saved["tags"] == ["stellaris", "confocal", "startup"]
    assert author.get(f"/api/guides/{saved['id']}").json()["tags"] == [
        "stellaris",
        "confocal",
        "startup",
    ]


def test_a_repeated_tag_is_collapsed_rather_than_stored_twice(author, category, db_session):
    saved = tagged_guide(author, category.id, ["confocal", "startup", "confocal"])

    assert saved["tags"] == ["confocal", "startup"]
    assert len(db_session.scalars(select(Tag)).all()) == 2


def test_an_empty_tag_is_dropped_rather_than_refusing_the_whole_save(author, category):
    """The tag input emits a trailing empty term while the author is still
    typing; refusing the save would make autosave fail mid-word."""
    saved = tagged_guide(author, category.id, ["confocal", "", "   ", "startup"])

    assert saved["tags"] == ["confocal", "startup"]


def test_an_existing_tag_is_reused_rather_than_duplicated(author, category, db_session):
    tagged_guide(author, category.id, ["confocal"], title="First")
    tagged_guide(author, category.id, ["confocal"], title="Second")

    assert len(db_session.scalars(select(Tag).where(Tag.slug == "confocal")).all()) == 1


@pytest.mark.parametrize(
    "candidate",
    ["Confocal", "con focal", "-confocal", "confocal-", "con--focal", "confocal_2", "Kühlung", "conf.ocal"],
)
def test_a_tag_that_is_not_already_a_slug_is_refused_rather_than_rewritten(author, category, candidate):
    """Re-slugifying server-side would be worse than refusing: two spellings
    would agree in the editor and disagree in the database, which is exactly how
    the live site ended up with four spellings of one instrument."""
    guide = create_guide(author, category.id)

    response = save_tags(author, guide, [candidate])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_an_overlong_tag_slug_is_refused(author, category):
    guide = create_guide(author, category.id)

    response = save_tags(author, guide, ["a" * 121])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_rejected_tag_leaves_the_rest_of_the_document_untouched(author, category):
    saved = tagged_guide(author, category.id, ["confocal"])

    refused = save_tags(author, saved, ["confocal", "NOT A SLUG"])

    assert refused.status_code == 422
    reloaded = author.get(f"/api/guides/{saved['id']}").json()
    assert reloaded["tags"] == ["confocal"]
    assert reloaded["updatedAt"] == saved["updatedAt"]


def test_forty_tags_fit_and_a_forty_first_does_not(author, category):
    """The cap is far above anything a guide has ever carried and far below what
    one request can be turned into: each tag is a row plus a lookup."""
    guide = create_guide(author, category.id)
    forty = [f"tag-{index}" for index in range(40)]

    accepted = save_tags(author, guide, forty)
    refused = save_tags(author, accepted.json(), forty + ["tag-40"])

    assert accepted.status_code == 200
    assert accepted.json()["tags"] == forty
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "validation_failed"


def test_removing_a_tag_from_the_document_detaches_the_guide_from_it(author, category):
    saved = tagged_guide(author, category.id, ["confocal", "startup"])

    trimmed = save_tags(author, saved, ["startup"]).json()

    assert trimmed["tags"] == ["startup"]
    assert [g["title"] for g in author.get("/api/guides", params={"tags": "confocal"}).json()] == []


def test_the_tag_list_matches_the_domain_model_exactly(author, category):
    tagged_guide(author, category.id, ["confocal"])

    entry = author.get("/api/tags").json()[0]

    assert set(entry) == {"id", "slug", "name", "guideCount"}
    assert entry["slug"] == "confocal"
    assert entry["guideCount"] == 1


def test_the_tag_list_counts_the_guides_behind_each_tag(author, category):
    tagged_guide(author, category.id, ["confocal", "startup"], title="One")
    tagged_guide(author, category.id, ["confocal"], title="Two")

    counts = {entry["slug"]: entry["guideCount"] for entry in author.get("/api/tags").json()}

    assert counts == {"confocal": 2, "startup": 1}


def test_the_tag_list_is_ordered_by_slug(author, category):
    tagged_guide(author, category.id, ["startup", "confocal", "airyscan"])

    assert [entry["slug"] for entry in author.get("/api/tags").json()] == [
        "airyscan",
        "confocal",
        "startup",
    ]


def test_a_viewer_is_not_shown_a_tag_whose_only_guide_is_a_draft(author, viewer, category):
    """Following it would land the reader on an empty page, which reads as a
    broken link and leaks that unpublished work exists under that heading."""
    tagged_guide(author, category.id, ["unreleased"])

    assert [entry["slug"] for entry in author.get("/api/tags").json()] == ["unreleased"]
    assert viewer.get("/api/tags").json() == []


def test_a_viewers_tag_counts_exclude_the_drafts_an_author_can_see(author, viewer, category):
    published = tagged_guide(author, category.id, ["confocal"], title="Published")
    tagged_guide(author, category.id, ["confocal"], title="Still A Draft")
    author.post(f"/api/guides/{published['id']}/publish")

    assert author.get("/api/tags").json()[0]["guideCount"] == 2
    assert viewer.get("/api/tags").json()[0]["guideCount"] == 1


def test_a_tag_left_with_only_archived_guides_disappears_from_the_list(author, admin, category):
    saved = tagged_guide(author, category.id, ["retired"])

    admin.delete(f"/api/guides/{saved['id']}")

    assert author.get("/api/tags").json() == []


def test_the_tag_filter_requires_every_tag_not_any_of_them(author, category):
    """A wiki heading that asks for "stellaris, confocal" means the guides that
    are both; "any" would turn every embed on the busiest page into a dump."""
    tagged_guide(author, category.id, ["confocal", "stellaris"], title="Both")
    tagged_guide(author, category.id, ["confocal"], title="Confocal Only")
    tagged_guide(author, category.id, ["stellaris"], title="Stellaris Only")

    titles = [g["title"] for g in author.get("/api/guides", params={"tags": "confocal,stellaris"}).json()]

    assert titles == ["Both"]


def test_the_tag_filter_ignores_repeats_case_and_surrounding_space(author, category):
    tagged_guide(author, category.id, ["confocal"], title="Only One")

    listing = author.get("/api/guides", params={"tags": " Confocal , confocal ,CONFOCAL"}).json()

    assert [g["title"] for g in listing] == ["Only One"]


def test_an_unknown_tag_filters_the_listing_down_to_nothing(author, category):
    tagged_guide(author, category.id, ["confocal"])

    assert author.get("/api/guides", params={"tags": "no-such-tag"}).json() == []


def test_the_tag_filter_is_capped_at_twenty_terms(author, category):
    """Each term becomes one correlated subquery, so an unbounded filter is a
    thousand-way join a caller can ask for in one URL."""
    create_guide(author, category.id)
    twenty = ",".join(f"tag-{index}" for index in range(20))

    assert author.get("/api/guides", params={"tags": twenty}).status_code == 200

    response = author.get("/api/guides", params={"tags": twenty + ",tag-20"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert "20" in response.json()["error"]["message"]


def test_an_empty_tag_filter_is_no_filter_at_all(author, category):
    tagged_guide(author, category.id, ["confocal"], title="Visible")

    assert [g["title"] for g in author.get("/api/guides", params={"tags": ""}).json()] == ["Visible"]
    assert [g["title"] for g in author.get("/api/guides", params={"tags": " , "}).json()] == ["Visible"]


def test_the_tag_filter_still_hides_drafts_from_a_viewer(author, viewer, category):
    tagged_guide(author, category.id, ["confocal"], title="Draft Under A Public Tag")
    published = tagged_guide(author, category.id, ["confocal"], title="Published")
    author.post(f"/api/guides/{published['id']}/publish")

    listing = viewer.get("/api/guides", params={"tags": "confocal"}).json()

    assert [g["title"] for g in listing] == ["Published"]


def test_the_summary_projection_carries_the_tags_a_card_shows(author, category):
    tagged_guide(author, category.id, ["confocal", "startup"])

    assert author.get("/api/guides").json()[0]["tags"] == ["confocal", "startup"]


def test_the_tag_list_requires_a_session(anon):
    assert anon.get("/api/tags").status_code == 401
