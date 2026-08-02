"""Search across both content types.

A reader looking for "immersion oil" does not know or care whether the answer
was written as a guide or as a wiki page, and a search that covers only one of
them sends them to the single place the answer is not. That is the first failure
guarded here.

The second is quieter and worse. The query is a ``LIKE`` pattern built from
caller-supplied text, so a search for ``%`` that is not escaped matches every
row in both tables — which hands any account a one-character request that
serialises the institute's entire documentation, and hands a viewer nothing
extra only because the visibility clause happens to be separate. Both halves are
asserted here rather than assumed.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Guide, Page, User

from .conftest import bullet, create_guide, create_page, document_from, page_document_from, step


def publish_guide_with(client, category_id: str, title: str, **fields) -> dict:
    guide = create_guide(client, category_id, title)
    saved = client.put(f"/api/guides/{guide['id']}", json=document_from(guide, **fields))
    assert saved.status_code == 200, saved.text
    published = client.post(f"/api/guides/{guide['id']}/publish")
    assert published.status_code == 200, published.text
    return published.json()


def publish_page_with(client, title: str, **fields) -> dict:
    page = create_page(client, title)
    saved = client.put(f"/api/pages/{page['id']}", json=page_document_from(page, **fields))
    assert saved.status_code == 200, saved.text
    published = client.post(f"/api/pages/{page['id']}/publish")
    assert published.status_code == 200, published.text
    return published.json()


def titles(hits: list[dict]) -> list[str]:
    return [
        hit["guide"]["title"] if hit["kind"] == "guide" else hit["page"]["title"] for hit in hits
    ]


def test_one_query_spans_guides_and_wiki_pages(author, category):
    publish_guide_with(author, category.id, "Immersion Oil Guide")
    publish_page_with(author, "Immersion Oil Reference")

    hits = author.get("/api/search", params={"q": "immersion oil"}).json()

    assert sorted(titles(hits)) == ["Immersion Oil Guide", "Immersion Oil Reference"]
    assert sorted(hit["kind"] for hit in hits) == ["guide", "page"]


def test_a_guide_hit_carries_the_summary_projection(author, category):
    publish_guide_with(author, category.id, "Immersion Oil Guide")

    hit = author.get("/api/search", params={"q": "immersion"}).json()[0]

    assert set(hit) == {"kind", "guide"}
    assert hit["kind"] == "guide"
    assert set(hit["guide"]) == {
        "id",
        "slug",
        "title",
        "summary",
        "categoryId",
        "tags",
        "difficulty",
        "timeRequiredMinMinutes",
        "timeRequiredMaxMinutes",
        "status",
        "stepCount",
        "author",
        "viewCount",
        "thumbnailUrl",
        "updatedAt",
        "publishedAt",
    }


def test_a_page_hit_carries_the_page_summary_projection(author):
    publish_page_with(author, "Immersion Oil Reference")

    hit = author.get("/api/search", params={"q": "immersion"}).json()[0]

    assert set(hit) == {"kind", "page"}
    assert hit["kind"] == "page"
    assert set(hit["page"]) == {
        "id",
        "slug",
        "title",
        "summary",
        "categoryId",
        "isLanding",
        "status",
        "heroImageUrl",
        "updatedAt",
        "publishedAt",
    }


def test_a_guide_matches_on_all_of_its_front_matter(author, category):
    publish_guide_with(author, category.id, "Objective Care")
    publish_guide_with(author, category.id, "Second Guide", summary="Handling the cryostat safely.")
    publish_guide_with(
        author, category.id, "Third Guide", introduction="Read the xylene sheet first."
    )
    publish_guide_with(
        author, category.id, "Fourth Guide", conclusion="Log any drift in the booking system."
    )

    assert titles(author.get("/api/search", params={"q": "objective"}).json()) == ["Objective Care"]
    assert titles(author.get("/api/search", params={"q": "cryostat"}).json()) == ["Second Guide"]
    assert titles(author.get("/api/search", params={"q": "xylene"}).json()) == ["Third Guide"]
    assert titles(author.get("/api/search", params={"q": "drift"}).json()) == ["Fourth Guide"]


def test_a_guide_matches_on_the_text_inside_its_steps(author, category):
    """A reader searching for "immersion oil" wants the step that says it, and
    at ZMB that phrase is usually in a bullet rather than in the front matter.
    A search that covered only titles and summaries would answer "nothing found"
    about a procedure that explains it in detail."""
    publish_guide_with(
        author,
        category.id,
        "Mounting",
        steps=[step("Add the immersion medium", bullets=[bullet("One drop of oil, no more.")])],
    )
    publish_guide_with(author, category.id, "Unrelated Guide")

    assert titles(author.get("/api/search", params={"q": "immersion medium"}).json()) == [
        "Mounting"
    ]
    assert titles(author.get("/api/search", params={"q": "one drop"}).json()) == ["Mounting"]


def test_a_title_match_outranks_a_mention_buried_in_a_step(author, category):
    """Otherwise the ordering is "most recently edited", which puts the guide
    that merely mentions the term above the one named after it."""
    publish_guide_with(
        author,
        category.id,
        "Passing Mention",
        steps=[step("Setup", bullets=[bullet("Check the cryostat before starting.")])],
    )
    publish_guide_with(author, category.id, "Cryostat Maintenance")

    assert titles(author.get("/api/search", params={"q": "cryostat"}).json()) == [
        "Cryostat Maintenance",
        "Passing Mention",
    ]


def test_a_page_whose_title_matches_comes_before_one_whose_body_does(author):
    publish_page_with(author, "Buffers", body="Keep the cryostat at minus twenty.")
    publish_page_with(author, "Cryostat Notes")

    assert titles(author.get("/api/search", params={"q": "cryostat"}).json()) == [
        "Cryostat Notes",
        "Buffers",
    ]


def test_a_page_matches_on_its_title_summary_and_body(author):
    publish_page_with(author, "Objective Care")
    publish_page_with(author, "Second Page", summary="Handling the cryostat safely.")
    publish_page_with(author, "Third Page", body="## Solvents\n\nRead the xylene sheet first.")

    assert titles(author.get("/api/search", params={"q": "objective"}).json()) == ["Objective Care"]
    assert titles(author.get("/api/search", params={"q": "cryostat"}).json()) == ["Second Page"]
    assert titles(author.get("/api/search", params={"q": "xylene"}).json()) == ["Third Page"]


def test_matching_ignores_case(author, category):
    publish_guide_with(author, category.id, "Immersion Oil Guide")

    assert titles(author.get("/api/search", params={"q": "IMMERSION"}).json()) == [
        "Immersion Oil Guide"
    ]


def test_an_empty_query_returns_nothing_rather_than_everything(author, category):
    publish_guide_with(author, category.id, "Immersion Oil Guide")
    publish_page_with(author, "Immersion Oil Reference")

    assert author.get("/api/search").json() == []
    assert author.get("/api/search", params={"q": ""}).json() == []
    assert author.get("/api/search", params={"q": "    "}).json() == []


def test_a_percent_sign_is_matched_literally_and_not_as_a_wildcard(author, category):
    """Unescaped, one character would return the whole corpus in both tables."""
    publish_guide_with(author, category.id, "Fixation", summary="Use 4% PFA for 10 minutes.")
    publish_guide_with(author, category.id, "Alignment", summary="No percent sign in this one.")
    publish_page_with(author, "Buffers", body="Dilute to 70% ethanol.")
    publish_page_with(author, "Booking", body="Nothing of the sort here.")

    assert sorted(titles(author.get("/api/search", params={"q": "%"}).json())) == [
        "Buffers",
        "Fixation",
    ]


def test_an_underscore_is_matched_literally_and_not_as_a_single_character_wildcard(
    author, category
):
    publish_guide_with(author, category.id, "Batch Export", summary="Files land as run_01.tif.")
    publish_guide_with(author, category.id, "Manual Export", summary="Files land as run01 tif.")
    publish_page_with(author, "Naming", body="Use frame_index in the macro.")

    assert sorted(titles(author.get("/api/search", params={"q": "_"}).json())) == [
        "Batch Export",
        "Naming",
    ]


def test_a_backslash_in_the_query_matches_itself(author, category):
    publish_guide_with(author, category.id, "Windows Paths", summary=r"Save to D:\data\zmb.")
    publish_guide_with(author, category.id, "Posix Paths", summary="Save to /data/zmb.")

    assert titles(author.get("/api/search", params={"q": "\\"}).json()) == ["Windows Paths"]


def test_a_viewer_never_sees_a_draft_guide_in_the_results(author, viewer, category):
    publish_guide_with(author, category.id, "Published Guide", summary="immersion oil")
    create_guide(author, category.id, "Draft Guide About Immersion Oil")

    assert sorted(titles(author.get("/api/search", params={"q": "immersion"}).json())) == [
        "Draft Guide About Immersion Oil",
        "Published Guide",
    ]
    assert titles(viewer.get("/api/search", params={"q": "immersion"}).json()) == [
        "Published Guide"
    ]


def test_a_viewer_never_sees_a_draft_page_in_the_results(author, viewer):
    publish_page_with(author, "Published Page", body="immersion oil")
    create_page(author, "Draft Page About Immersion Oil")

    assert titles(viewer.get("/api/search", params={"q": "immersion"}).json()) == ["Published Page"]


def test_archived_content_is_hidden_from_authors_as_well(author, admin, category):
    guide = publish_guide_with(author, category.id, "Retired Guide")
    page = publish_page_with(author, "Retired Page")

    admin.delete(f"/api/guides/{guide['id']}")
    admin.delete(f"/api/pages/{page['id']}")

    assert author.get("/api/search", params={"q": "retired"}).json() == []


def test_a_query_matching_nothing_returns_an_empty_list(author, category):
    publish_guide_with(author, category.id, "Immersion Oil Guide")

    assert author.get("/api/search", params={"q": "electron tomography"}).json() == []


def test_an_overlong_query_is_refused_rather_than_scanned(author):
    assert author.get("/api/search", params={"q": "x" * 201}).status_code == 422


def test_each_content_type_is_capped_so_one_query_cannot_dump_the_corpus(
    author, db_session, category
):
    """The corpus is small today, but the endpoint is reachable by every account
    and a search for "e" that returns everything is a cheap way to make the
    server serialise the whole institute's documentation on demand."""
    person = db_session.scalars(select(User).where(User.email == "author@zmb.uzh.ch")).one()
    for index in range(105):
        db_session.add(
            Guide(
                slug=f"bulk-guide-{index}",
                title=f"Bulk Widget Guide {index}",
                category_id=category.id,
                status="published",
                author_id=person.id,
                last_edited_by_id=person.id,
            )
        )
        db_session.add(
            Page(
                slug=f"bulk-page-{index}",
                title=f"Bulk Widget Page {index}",
                status="published",
                author_id=person.id,
                last_edited_by_id=person.id,
            )
        )
    db_session.commit()

    hits = author.get("/api/search", params={"q": "widget"}).json()

    assert sum(1 for hit in hits if hit["kind"] == "guide") == 100
    assert sum(1 for hit in hits if hit["kind"] == "page") == 100


def test_search_requires_a_session(anon):
    assert anon.get("/api/search", params={"q": "anything"}).status_code == 401


def test_a_term_written_only_in_a_bullet_is_found(author, category):
    """The answer to "immersion oil" is in a step, not in the front matter.

    A search restricted to titles and summaries answers "nothing found" about a
    procedure that explains the thing in detail three steps in, which is the
    single most likely way for this endpoint to look broken to a reader.
    """
    publish_guide_with(
        author,
        category.id,
        "Aligning the Confocal",
        steps=[
            {
                "title": "Mount the sample",
                "bullets": [
                    {
                        "text": "Use the immersion oil printed on the objective.",
                        "color": "black",
                        "icon": None,
                        "level": 0,
                    }
                ],
                "media": [],
            }
        ],
    )

    assert titles(author.get("/api/search?q=immersion oil").json()) == ["Aligning the Confocal"]


def test_a_term_written_only_in_a_step_title_is_found(author, category):
    publish_guide_with(
        author,
        category.id,
        "Shutting Down",
        steps=[{"title": "Purge the objective turret", "bullets": [], "media": []}],
    )

    assert titles(author.get("/api/search?q=turret").json()) == ["Shutting Down"]


def test_a_term_in_the_conclusion_is_found(author, category):
    publish_guide_with(
        author,
        category.id,
        "Booking a Session",
        conclusion="Report any fault in the booking system the same day.",
    )

    assert titles(author.get("/api/search?q=booking system").json()) == ["Booking a Session"]


def test_a_guide_named_for_the_term_outranks_one_that_merely_mentions_it(author, category):
    """Otherwise the ordering is "most recently edited", which buries the answer."""
    publish_guide_with(
        author,
        category.id,
        "Cleaning an Objective",
        steps=[{"title": "Wipe", "bullets": [], "media": []}],
    )
    publish_guide_with(
        author,
        category.id,
        "Starting the Stellaris",
        steps=[
            {
                "title": "Prepare",
                "bullets": [
                    {
                        "text": "Cleaning an objective is covered elsewhere.",
                        "color": "black",
                        "icon": None,
                        "level": 0,
                    }
                ],
                "media": [],
            }
        ],
    )

    found = titles(author.get("/api/search?q=Cleaning an Objective").json())
    assert found[0] == "Cleaning an Objective"


def test_a_bullet_inside_a_draft_is_not_searchable_by_a_viewer(author, viewer, category):
    guide = create_guide(author, category.id, "Unfinished Procedure")
    author.put(
        f"/api/guides/{guide['id']}",
        json=document_from(
            guide,
            steps=[
                {
                    "title": "Step",
                    "bullets": [
                        {
                            "text": "The spare key is taped under the bench.",
                            "color": "black",
                            "icon": None,
                            "level": 0,
                        }
                    ],
                    "media": [],
                }
            ],
        ),
    )

    assert viewer.get("/api/search?q=spare key").json() == []
    assert titles(author.get("/api/search?q=spare key").json()) == ["Unfinished Procedure"]


# --- searching a corpus that is not written in English ---------------------


def test_a_german_title_is_found_in_the_case_the_reader_types(author, category):
    """SQLite's ``lower()`` folds A–Z and stops, so before this was fixed the
    query below matched nothing: ``lower('Präparation')`` is ``'präparation'``
    but ``lower('PRÄPARATION')`` is ``'PRÄPARATION'``.

    Half of ZMB's corpus is German. A search that answers "nothing found" about
    a procedure that exists is worse than one that is slow, because the reader
    cannot tell it from "nobody has written this yet" and goes to ask a person.
    """
    publish_guide_with(author, category.id, "Präparation der Probe")

    for typed in ("Präparation", "präparation", "PRÄPARATION", "präp"):
        assert titles(author.get("/api/search", params={"q": typed}).json()) == [
            "Präparation der Probe"
        ], f"searching {typed!r} found nothing"


def test_folding_reaches_the_body_text_too(author, category):
    """The title is matched by one clause; steps and bullets by another."""
    publish_guide_with(
        author,
        category.id,
        "Sample Handling",
        steps=[step("Vorbereitung", bullets=[bullet("Objektträger säubern.")])],
    )

    assert titles(author.get("/api/search", params={"q": "VORBEREITUNG"}).json()) == [
        "Sample Handling"
    ]
    assert titles(author.get("/api/search", params={"q": "OBJEKTTRÄGER"}).json()) == [
        "Sample Handling"
    ]


def test_ascii_search_is_unchanged_by_the_override(author, category):
    """The override replaces a built-in used by every ``ilike`` in the
    application, so the ordinary case is worth pinning alongside it."""
    publish_guide_with(author, category.id, "Immersion Oil Guide")

    assert titles(author.get("/api/search", params={"q": "IMMERSION"}).json()) == [
        "Immersion Oil Guide"
    ]
