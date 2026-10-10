"""Tags as navigation, tag-filtered listings, and search across guides and pages.

These are what a ZMB category page is built from: guides live in holding
categories and surface wherever a wiki page asks for their tag, so the tag
filter and the tag counts have to obey the visibility rule as strictly as the
guides themselves do.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from .conftest import (
    bullet,
    create_guide,
    create_page,
    publish_guide,
    published_guide,
    published_page,
    save_guide,
    save_page,
    step,
)


def titles(response) -> list[str]:
    return [entry["title"] for entry in response.json()]


# ---------------------------------------------------------------------- tags


def test_the_tag_listing_matches_the_domain_model_and_is_sorted_by_name(author, category):
    created = create_guide(author, category.id)
    save_guide(author, created, tags=["stellaris", "Confocal", "LAS X"])

    listing = author.get("/api/tags").json()

    assert [tag["name"] for tag in listing] == ["Confocal", "LAS X", "stellaris"]
    assert [tag["slug"] for tag in listing] == ["confocal", "las-x", "stellaris"]
    assert all(set(tag) == {"id", "slug", "name", "guideCount"} for tag in listing)
    assert all(tag["guideCount"] == 1 for tag in listing)


def test_tag_counts_only_count_what_the_caller_can_see(author, admin, viewer, category):
    """A count is a reference to content. Telling a viewer that three guides
    carry a tag while showing them one discloses the two drafts."""
    published_guide(author, category.id, "Live", tags=["confocal", "stellaris"])
    save_guide(author, create_guide(author, category.id, "Draft"), tags=["confocal", "secret-project"])
    archived = published_guide(author, category.id, "Archived", tags=["confocal", "retired"])
    admin.delete(f"/api/guides/{archived['id']}")

    as_viewer = {tag["slug"]: tag["guideCount"] for tag in viewer.get("/api/tags").json()}
    as_author = {tag["slug"]: tag["guideCount"] for tag in author.get("/api/tags").json()}

    assert as_viewer == {"confocal": 1, "stellaris": 1}
    assert as_author == {"confocal": 2, "stellaris": 1, "secret-project": 1}
    assert admin.get("/api/tags").json() == author.get("/api/tags").json()


def test_a_tag_no_guide_carries_any_more_stops_being_listed(author, category):
    created = create_guide(author, category.id)
    saved = save_guide(author, created, tags=["confocal"])
    assert [tag["slug"] for tag in author.get("/api/tags").json()] == ["confocal"]

    save_guide(author, saved, tags=[])

    assert author.get("/api/tags").json() == []


def test_there_is_no_way_to_create_or_delete_a_tag_directly(admin):
    created = admin.post("/api/tags", json={"name": "confocal"})

    assert created.status_code == 405
    assert created.json()["error"]["code"] == "not_found"
    assert admin.delete("/api/tags/confocal").status_code == 404
    assert admin.get("/api/tags").json() == []


def test_tags_require_a_session(anon):
    assert anon.get("/api/tags").status_code == 401


# ---------------------------------------------------------- tag-filtered lists


def test_the_tag_filter_requires_every_tag(author, category):
    published_guide(author, category.id, "Both", tags=["confocal", "las-x"])
    published_guide(author, category.id, "Confocal only", tags=["confocal"])
    published_guide(author, category.id, "LAS X only", tags=["las-x", "stellaris"])
    published_guide(author, category.id, "Neither", tags=["fiji"])

    assert sorted(titles(author.get("/api/guides", params={"tags": "confocal"}))) == ["Both", "Confocal only"]
    assert titles(author.get("/api/guides", params={"tags": "confocal,las-x"})) == ["Both"]
    assert titles(author.get("/api/guides", params={"tags": "confocal,las-x,stellaris"})) == []
    assert titles(author.get("/api/guides", params={"tags": "no-such-tag"})) == []


def test_the_tag_filter_tolerates_how_people_write_it(author, category):
    """A ``guidelist`` block is typed by hand into a wiki page: spaces after
    commas, a display name instead of a slug, a tag given twice."""
    published_guide(author, category.id, "Both", tags=["confocal", "las-x"])
    published_guide(author, category.id, "One", tags=["confocal"])

    assert titles(author.get("/api/guides", params={"tags": " Confocal , LAS X "})) == ["Both"]
    assert titles(author.get("/api/guides", params={"tags": "confocal,confocal,las-x"})) == ["Both"]
    assert len(author.get("/api/guides", params={"tags": " , "}).json()) == 2
    assert len(author.get("/api/guides", params={"tags": ""}).json()) == 2


def test_the_tag_filter_obeys_visibility(author, viewer, category):
    published_guide(author, category.id, "Live", tags=["confocal"])
    save_guide(author, create_guide(author, category.id, "Draft"), tags=["confocal"])

    assert titles(viewer.get("/api/guides", params={"tags": "confocal"})) == ["Live"]
    assert sorted(titles(author.get("/api/guides", params={"tags": "confocal"}))) == ["Draft", "Live"]


def test_the_tag_filter_combines_with_the_other_filters(author, admin, category):
    other = admin.post("/api/categories", json={"name": "Electron Microscopy"}).json()
    published_guide(author, category.id, "LM confocal", tags=["confocal"])
    save_guide(author, create_guide(author, other["id"], "EM confocal draft"), tags=["confocal"])

    assert titles(author.get("/api/guides", params={"tags": "confocal", "categoryId": other["id"]})) == ["EM confocal draft"]
    assert titles(author.get("/api/guides", params={"tags": "confocal", "status": "published"})) == ["LM confocal"]
    assert titles(author.get("/api/guides", params={"tags": "confocal", "q": "em"})) == ["EM confocal draft"]


def test_the_free_text_filter_matches_tag_names(author, category):
    save_guide(author, create_guide(author, category.id, "Tile Scan"), tags=["LAS X"])
    create_guide(author, category.id, "Unrelated")

    assert titles(author.get("/api/guides", params={"q": "las x"})) == ["Tile Scan"]
    assert titles(author.get("/api/guides", params={"q": "las-x"})) == ["Tile Scan"]


class QueryCounter:
    """Counts the SQL statements a block issues on the test database."""

    def __init__(self, session) -> None:
        self.engine = session.get_bind()
        self.count = 0

    def _on_execute(self, *args) -> None:
        self.count += 1

    def __enter__(self) -> "QueryCounter":
        event.listen(self.engine, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *exc) -> None:
        event.remove(self.engine, "before_cursor_execute", self._on_execute)


def _statements(db_session, call) -> int:
    with QueryCounter(db_session) as counter:
        response = call()
    assert response.status_code == 200, response.text
    assert counter.count > 0, "the counter is not attached to the engine the request used"
    return counter.count


def test_listing_many_guides_costs_no_more_queries_than_listing_a_few(author, viewer, category, db_session):
    """A landing page can embed a list of eighty-odd guides. The number of
    statements must not grow with the number of guides, tags or authors."""
    def populate(count: int, prefix: str) -> None:
        for index in range(count):
            published_guide(author, category.id, f"{prefix} {index}", tags=["confocal", f"{prefix}-{index}"])

    populate(3, "few")
    few = _statements(db_session, lambda: viewer.get("/api/guides", params={"tags": "confocal"}))

    populate(30, "many")
    many = _statements(db_session, lambda: viewer.get("/api/guides", params={"tags": "confocal"}))

    assert len(viewer.get("/api/guides", params={"tags": "confocal"}).json()) == 33
    assert many == few


def test_the_other_listings_do_not_grow_their_query_count_either(author, viewer, category, db_session):
    def populate(count: int, prefix: str) -> None:
        for index in range(count):
            published_guide(author, category.id, f"{prefix} guide {index}", tags=[f"{prefix}-{index}", "shared"])
            published_page(author, f"{prefix} page {index}", body="Shared body text.")

    calls = {
        "tags": lambda: viewer.get("/api/tags"),
        "pages": lambda: viewer.get("/api/pages"),
        "search": lambda: viewer.get("/api/search", params={"q": "shared"}),
        "categories": lambda: viewer.get("/api/categories"),
    }

    populate(2, "few")
    few = {name: _statements(db_session, call) for name, call in calls.items()}
    populate(12, "many")
    many = {name: _statements(db_session, call) for name, call in calls.items()}

    assert many == few


def test_reading_one_guide_costs_the_same_whatever_its_length(author, category, db_session):
    short = published_guide(author, category.id, "Short", steps=[step("One", bullets=[bullet("a")])])
    long = published_guide(
        author,
        category.id,
        "Long",
        steps=[step(f"Step {index}", bullets=[bullet("a"), bullet("b"), bullet("c")]) for index in range(25)],
    )

    assert _statements(db_session, lambda: author.get(f"/api/guides/{long['id']}")) == _statements(
        db_session, lambda: author.get(f"/api/guides/{short['id']}")
    )


# -------------------------------------------------------------------- search


def test_an_empty_or_blank_term_returns_nothing(author, category):
    published_guide(author, category.id)

    assert author.get("/api/search").json() == []
    assert author.get("/api/search", params={"q": ""}).json() == []
    assert author.get("/api/search", params={"q": "   "}).json() == []


def test_results_say_which_kind_they_are(author, category):
    guide = published_guide(author, category.id, "Stellaris Start-up")
    page = published_page(author, "Stellaris Systems")

    results = author.get("/api/search", params={"q": "stellaris"}).json()

    by_kind = {result["kind"]: result for result in results}
    assert set(by_kind) == {"guide", "page"}
    assert set(by_kind["guide"]) == {"kind", "guide"}
    assert set(by_kind["page"]) == {"kind", "page"}
    assert by_kind["guide"]["guide"]["id"] == guide["id"]
    assert by_kind["guide"]["guide"]["stepCount"] == 1
    assert "steps" not in by_kind["guide"]["guide"]
    assert by_kind["page"]["page"]["id"] == page["id"]
    assert "body" not in by_kind["page"]["page"]


@pytest.mark.parametrize(
    "term,where",
    [
        ("alignment", "title"),
        ("pinhole", "summary"),
        ("lightsheet", "tag"),
        ("turret", "step title"),
        ("immersion", "bullet text"),
    ],
)
def test_guides_match_on_every_field_the_contract_names(author, category, term, where):
    created = create_guide(author, category.id, "Confocal Alignment")
    save_guide(
        author,
        created,
        summary="Centre the pinhole.",
        tags=["Lightsheet"],
        steps=[step("Rotate the turret", bullets=[bullet("Add IMMERSION oil.")])],
    )
    create_guide(author, category.id, "Unrelated")

    results = author.get("/api/search", params={"q": term}).json()

    assert [r["guide"]["title"] for r in results] == ["Confocal Alignment"], where


@pytest.mark.parametrize("term", ["booking", "fair use", "no-shows"])
def test_pages_match_on_title_summary_and_body(author, term):
    created = create_page(author, "Booking Rules")
    save_page(author, created, summary="Fair use of instrument time.", body="## No-shows\n\nReleased after 30 minutes.")
    create_page(author, "Unrelated")

    results = author.get("/api/search", params={"q": term}).json()

    assert [r["page"]["title"] for r in results] == ["Booking Rules"]


def test_title_matches_rank_ahead_of_everything_else(author, category):
    in_body = create_guide(author, category.id, "Start-up Routine")
    in_body = save_guide(author, in_body, steps=[step("Lasers", bullets=[bullet("Switch on the confocal last.")])])
    page_body = create_page(author, "Rooms")
    save_page(author, page_body, body="The confocal suite is in room 12.")
    page_title = create_page(author, "Confocal Systems")
    guide_title = create_guide(author, category.id, "Confocal Alignment")
    save_guide(author, in_body, summary="Touched most recently, but only a body match.")

    results = author.get("/api/search", params={"q": "confocal"}).json()
    found = [(r["kind"], r[r["kind"]]["title"]) for r in results]

    assert set(found[:2]) == {("guide", "Confocal Alignment"), ("page", "Confocal Systems")}
    assert set(found[2:]) == {("guide", "Start-up Routine"), ("page", "Rooms")}
    assert found[0] == ("guide", guide_title["title"]) and found[1] == ("page", page_title["title"])


def test_search_obeys_visibility_for_both_kinds(author, admin, viewer, category):
    published_guide(author, category.id, "Stellaris Live Guide")
    save_guide(author, create_guide(author, category.id, "Stellaris Draft Guide"), tags=["x"])
    gone = published_guide(author, category.id, "Stellaris Archived Guide")
    admin.delete(f"/api/guides/{gone['id']}")
    published_page(author, "Stellaris Live Page")
    create_page(author, "Stellaris Draft Page")

    def found(client) -> set[str]:
        return {r[r["kind"]]["title"] for r in client.get("/api/search", params={"q": "stellaris"}).json()}

    assert found(viewer) == {"Stellaris Live Guide", "Stellaris Live Page"}
    assert found(author) == {
        "Stellaris Live Guide", "Stellaris Draft Guide", "Stellaris Live Page", "Stellaris Draft Page",
    }
    assert found(admin) == found(author)


def test_a_draft_is_not_findable_through_text_only_it_contains(author, viewer, category):
    """The leak to guard against is not the title: it is a bullet in a draft
    answering a viewer's search and so confirming what the draft is about."""
    created = create_guide(author, category.id, "Innocuous Title")
    save_guide(author, created, steps=[step("Step", bullets=[bullet("Unannounced instrument: Elyra 9.")])])

    assert viewer.get("/api/search", params={"q": "Elyra"}).json() == []
    assert len(author.get("/api/search", params={"q": "Elyra"}).json()) == 1


def test_search_wildcards_are_literal(author, category):
    published_guide(author, category.id, "Plain")
    special = published_guide(author, category.id, "Dilute to 4% PFA")

    assert [r["guide"]["id"] for r in author.get("/api/search", params={"q": "4%"}).json()] == [special["id"]]
    assert author.get("/api/search", params={"q": "%"}).json().__len__() == 1
    assert author.get("/api/search", params={"q": "_"}).json() == []


def test_search_returns_at_most_fifty_results(author, category):
    for index in range(30):
        create_guide(author, category.id, f"Needle guide {index}")
        create_page(author, f"Needle page {index}")

    results = author.get("/api/search", params={"q": "needle"}).json()

    assert len(results) == 50
    assert {r["kind"] for r in results} == {"guide", "page"}


def test_an_overlong_search_term_is_rejected(author):
    assert author.get("/api/search", params={"q": "x" * 201}).status_code == 422


def test_search_requires_a_session(anon):
    assert anon.get("/api/search", params={"q": "anything"}).status_code == 401
