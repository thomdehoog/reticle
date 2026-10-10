"""Readers are served the published snapshot, never the working copy.

The promise on the first page of the README is that editing a published guide
never breaks the version people are reading. What used to happen is that the
editor autosaved into the very rows a reader was shown: half a sentence was
live as it was typed, a screenshot dropped into a step was fetchable by every
viewer, and a guide whose title an author had cleared to retype it was
"published" with no title.

Every test here is about one of the ways content reaches a reader, and each
asserts the same thing twice: an unpublished edit does not get through it, and
a published one does.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfReader
from sqlalchemy import event, select

from app import published
from app.models import (
    Guide,
    GuideRevision,
    Page,
    PublishedGuide,
    PublishedGuideMedia,
    PublishedGuideTag,
    PublishedPage,
    PublishedPageMedia,
)

from .conftest import (
    annotation,
    bullet,
    create_guide,
    create_page,
    image_bytes,
    instant,
    publish_guide,
    published_guide,
    published_page,
    save_guide,
    save_page,
    step,
    upload_media,
)

OLD_TEXT = "Switch on the mercury lamp and wait."
NEW_TEXT = "Unpublished: the lamp was replaced by an LED."


def pdf_text(client, key: str, **params) -> str:
    response = client.get(f"/api/guides/{key}/pdf", params=params)
    assert response.status_code == 200, response.text
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)


def guide_titles(client, **params) -> list[str]:
    return [entry["title"] for entry in client.get("/api/guides", params=params).json()]


def search_hits(client, term: str) -> list[str]:
    hits = client.get("/api/search", params={"q": term}).json()
    return [hit[hit["kind"]]["title"] for hit in hits]


def tag_counts(client) -> dict[str, int]:
    return {tag["slug"]: tag["guideCount"] for tag in client.get("/api/tags").json()}


@pytest.fixture()
def edited(author, category):
    """A published guide with an unpublished edit to every part of it.

    This is the reviewer's scenario: publish; then, as an author, save new
    text, a new title, summary, tags and a newly uploaded image — and do not
    publish.
    """
    old_image = upload_media(author, image_bytes(40, 30, color="#112233"))
    created = create_guide(author, category.id, "Starting the Widefield")
    saved = save_guide(
        author,
        created,
        summary="The published summary.",
        tags=["widefield", "lamp"],
        difficulty="easy",
        timeRequiredMinMinutes=5,
        timeRequiredMaxMinutes=10,
        steps=[step("Lamp", bullets=[bullet(OLD_TEXT)], media=[old_image])],
    )
    first = author.post(f"/api/guides/{created['id']}/publish").json()

    new_image = upload_media(author, image_bytes(50, 50, color="#aa0000"))
    working = save_guide(
        author,
        first,
        title="Starting the LED Widefield",
        summary="An unpublished summary.",
        tags=["widefield", "led"],
        difficulty="difficult",
        timeRequiredMinMinutes=1,
        timeRequiredMaxMinutes=2,
        steps=[
            {**first["steps"][0], "title": "Light source", "bullets": [bullet(NEW_TEXT)], "media": [new_image]},
            step("A second step", bullets=[bullet("Also unpublished.")]),
        ],
    )
    return {
        "id": created["id"],
        "slug": created["slug"],
        "first": first,
        "working": working,
        "old_image": old_image,
        "new_image": new_image,
        "saved": saved,
    }


# ------------------------------------------------- the reviewer's exact scenario


def test_an_unpublished_edit_reaches_a_viewer_by_no_route_at_all(edited, viewer, author):
    """Publish; edit text and add an upload as an author; look as a viewer."""
    for key in (edited["id"], edited["slug"]):
        seen = viewer.get(f"/api/guides/{key}")
        assert seen.status_code == 200
        body = seen.json()
        assert body["title"] == "Starting the Widefield"
        assert body["summary"] == "The published summary."
        assert body["tags"] == ["lamp", "widefield"]
        assert [s["title"] for s in body["steps"]] == ["Lamp"]
        assert body["steps"][0]["bullets"][0]["text"] == OLD_TEXT
        assert [m["id"] for m in body["steps"][0]["media"]] == [edited["old_image"]["id"]]
        assert body["version"] == 1 and body["status"] == "published"
        assert NEW_TEXT not in seen.text and "An unpublished summary" not in seen.text and "LED" not in seen.text

    listing = viewer.get("/api/guides").json()
    assert len(listing) == 1
    entry = listing[0]
    assert (entry["title"], entry["summary"]) == ("Starting the Widefield", "The published summary.")
    assert (entry["tags"], entry["difficulty"], entry["stepCount"]) == (["lamp", "widefield"], "easy", 1)
    assert (entry["timeRequiredMinMinutes"], entry["timeRequiredMaxMinutes"]) == (5, 10)

    assert search_hits(viewer, "LED") == []
    assert search_hits(viewer, "replaced by an LED") == []
    assert search_hits(viewer, "An unpublished summary") == []
    assert search_hits(viewer, "mercury") == ["Starting the Widefield"]

    assert tag_counts(viewer) == {"lamp": 1, "widefield": 1}
    assert guide_titles(viewer, tags="led") == []
    assert guide_titles(viewer, tags="lamp") == ["Starting the Widefield"]
    assert guide_titles(viewer, q="LED") == []

    text = pdf_text(viewer, edited["slug"])
    assert OLD_TEXT in text and "Starting the Widefield" in text
    assert "LED" not in text and "second step" not in text

    assert viewer.get(f"/api/media/{edited['old_image']['id']}").status_code == 200
    assert viewer.get(f"/api/media/{edited['new_image']['id']}").status_code == 404
    assert viewer.get(f"/api/media/{edited['new_image']['id']}", params={"size": "display"}).status_code == 404


def test_publishing_the_edit_moves_every_route_to_the_new_version(edited, viewer, author):
    assert author.post(f"/api/guides/{edited['id']}/publish").status_code == 200

    for key in (edited["id"], edited["slug"]):
        body = viewer.get(f"/api/guides/{key}").json()
        assert body["title"] == "Starting the LED Widefield"
        assert body["steps"][0]["bullets"][0]["text"] == NEW_TEXT
        assert [m["id"] for m in body["steps"][0]["media"]] == [edited["new_image"]["id"]]
        assert body["version"] == 2

    entry = viewer.get("/api/guides").json()[0]
    assert (entry["title"], entry["tags"], entry["difficulty"], entry["stepCount"]) == (
        "Starting the LED Widefield", ["led", "widefield"], "difficult", 2,
    )
    assert search_hits(viewer, "replaced by an LED") == ["Starting the LED Widefield"]
    assert search_hits(viewer, "mercury") == []
    assert tag_counts(viewer) == {"led": 1, "widefield": 1}
    assert guide_titles(viewer, tags="lamp") == []
    assert guide_titles(viewer, tags="led") == ["Starting the LED Widefield"]

    text = pdf_text(viewer, edited["slug"])
    assert "replaced by an LED" in text and "mercury" not in text

    assert viewer.get(f"/api/media/{edited['new_image']['id']}").status_code == 200
    assert viewer.get(f"/api/media/{edited['old_image']['id']}").status_code == 404, "no published version shows it now"


def test_an_emptied_working_copy_does_not_empty_the_published_guide(author, viewer, category):
    """A whole-document save with no title and no steps is a legitimate
    autosave. It used to be what readers were then served, as "published"."""
    guide = published_guide(author, category.id, "Laser Safety", steps=[step("Goggles", bullets=[bullet("On.")])])

    save_guide(author, guide, title="", steps=[])

    seen = viewer.get(f"/api/guides/{guide['slug']}").json()
    assert seen["title"] == "Laser Safety"
    assert [s["title"] for s in seen["steps"]] == ["Goggles"]
    refused = author.post(f"/api/guides/{guide['id']}/publish")
    assert refused.status_code == 422, "and it cannot be published in that state either"
    assert viewer.get(f"/api/guides/{guide['slug']}").json()["title"] == "Laser Safety"


# ------------------------------------------------------- what an author is given


def test_an_author_reads_the_working_copy_and_is_told_it_is_ahead(edited, author, admin):
    for client in (author, admin):
        body = client.get(f"/api/guides/{edited['id']}").json()
        assert body["title"] == "Starting the LED Widefield"
        assert body["steps"][0]["bullets"][0]["text"] == NEW_TEXT
        assert body["hasUnpublishedChanges"] is True
        assert body["version"] == 1, "the version counts publishes, and nothing was published"
        assert body["status"] == "published"


def test_an_author_can_ask_for_exactly_what_readers_see(edited, author, viewer):
    as_reader = author.get(f"/api/guides/{edited['slug']}", params={"view": "published"})
    assert as_reader.status_code == 200
    mine, theirs = as_reader.json(), viewer.get(f"/api/guides/{edited['slug']}").json()

    assert mine["hasUnpublishedChanges"] is True, "an author is told there is newer work"
    assert theirs["hasUnpublishedChanges"] is False, "a viewer is not: that would disclose it"
    assert {**mine, "hasUnpublishedChanges": False} == theirs
    assert author.get(f"/api/guides/{edited['id']}", params={"view": "working"}).json()["title"] == "Starting the LED Widefield"


def test_a_viewer_cannot_ask_for_the_working_copy(edited, viewer):
    body = viewer.get(f"/api/guides/{edited['slug']}", params={"view": "working"}).json()

    assert body["title"] == "Starting the Widefield"
    assert viewer.get(f"/api/guides/{edited['slug']}", params={"view": "draft"}).status_code == 422


def test_the_published_view_of_something_never_published_is_not_found(author, category):
    draft = create_guide(author, category.id, "Never Published")

    assert author.get(f"/api/guides/{draft['id']}", params={"view": "published"}).status_code == 404
    assert author.get(f"/api/guides/{draft['id']}").status_code == 200
    assert author.get(f"/api/guides/{draft['id']}").json()["hasUnpublishedChanges"] is False


def test_the_published_view_of_something_withdrawn_is_not_found(author, viewer, category):
    """Unpublished, readers see nothing — so that is what "as readers see it" is."""
    guide = published_guide(author, category.id)
    assert author.post(f"/api/guides/{guide['id']}/unpublish").status_code == 200

    assert author.get(f"/api/guides/{guide['id']}", params={"view": "published"}).status_code == 404
    assert viewer.get(f"/api/guides/{guide['id']}").status_code == 404
    assert viewer.get("/api/guides").json() == []
    assert author.get(f"/api/guides/{guide['id']}/revisions/1").status_code == 200, "the history is still there"


def test_an_authors_listings_search_and_tags_follow_the_working_copy(edited, author):
    """Documented choice: an author looks for a guide by what they have been
    typing into it, so everything author-facing reads the working copy."""
    entry = author.get("/api/guides").json()[0]
    assert (entry["title"], entry["tags"], entry["stepCount"]) == ("Starting the LED Widefield", ["led", "widefield"], 2)
    assert entry["hasUnpublishedChanges"] is True

    assert guide_titles(author, tags="led") == ["Starting the LED Widefield"]
    assert guide_titles(author, tags="lamp") == []
    assert tag_counts(author) == {"led": 1, "widefield": 1}
    assert search_hits(author, "replaced by an LED") == ["Starting the LED Widefield"]
    assert search_hits(author, "mercury") == []


def test_a_viewers_listing_never_says_that_unpublished_changes_exist(edited, viewer):
    assert [entry["hasUnpublishedChanges"] for entry in viewer.get("/api/guides").json()] == [False]
    hits = viewer.get("/api/search", params={"q": "Widefield"}).json()
    assert [hit["guide"]["hasUnpublishedChanges"] for hit in hits] == [False]


def test_the_pdf_follows_the_view(edited, author):
    assert NEW_TEXT in pdf_text(author, edited["slug"]) or "replaced by an LED" in pdf_text(author, edited["slug"])
    as_reader = pdf_text(author, edited["slug"], view="published")
    assert OLD_TEXT in as_reader and "LED" not in as_reader


# ------------------------------------------------------- hasUnpublishedChanges


def test_a_freshly_published_guide_has_no_unpublished_changes(author, category):
    guide = published_guide(author, category.id)

    assert guide["hasUnpublishedChanges"] is False
    assert author.get(f"/api/guides/{guide['id']}").json()["hasUnpublishedChanges"] is False
    assert author.get("/api/guides").json()[0]["hasUnpublishedChanges"] is False


def test_a_draft_never_has_unpublished_changes_however_often_it_is_saved(author, category):
    draft = create_guide(author, category.id)

    saved = save_guide(author, draft, steps=[step("One")])

    assert saved["hasUnpublishedChanges"] is False


def test_saving_marks_a_published_guide_and_publishing_clears_it(author, category):
    guide = published_guide(author, category.id)

    saved = save_guide(author, guide, summary="Something new.")
    assert saved["hasUnpublishedChanges"] is True

    again = author.post(f"/api/guides/{guide['id']}/publish").json()
    assert again["hasUnpublishedChanges"] is False and again["version"] == 2


def test_a_save_that_changes_nothing_a_reader_could_see_is_not_a_change(author, category):
    """The editor autosaves. A save that leaves the text as published — or
    that puts back a word typed and deleted — must not leave the guide flagged."""
    guide = published_guide(author, category.id, steps=[step("One", bullets=[bullet("Text.")])])

    untouched = save_guide(author, guide)
    assert untouched["hasUnpublishedChanges"] is False
    assert instant(untouched["updatedAt"]) > instant(guide["updatedAt"]), "it was still a save"

    typed = save_guide(author, untouched, summary="oops")
    assert typed["hasUnpublishedChanges"] is True
    undone = save_guide(author, typed, summary=guide["summary"])
    assert undone["hasUnpublishedChanges"] is False


def test_retyping_a_step_identically_is_not_a_change(author, category):
    """Identifiers are not content: a step deleted and typed again reads the same."""
    guide = published_guide(author, category.id, steps=[step("One", bullets=[bullet("Text.")])])

    retyped = save_guide(author, guide, steps=[step("One", bullets=[bullet("Text.")])])

    assert retyped["steps"][0]["id"] != guide["steps"][0]["id"]
    assert retyped["hasUnpublishedChanges"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"title": "Another title"},
        {"summary": "Another summary"},
        {"tags": ["new-tag"]},
        {"difficulty": "very_difficult"},
        {"timeRequiredMaxMinutes": 99},
        {"introduction": "Changed."},
        {"conclusion": "Changed."},
        {"steps": []},
    ],
)
def test_every_kind_of_content_change_counts(author, category, change):
    guide = published_guide(author, category.id, steps=[step("One", bullets=[bullet("Text.")])])

    assert save_guide(author, guide, **change)["hasUnpublishedChanges"] is True


def test_changing_only_an_annotation_or_an_alt_text_counts(author, category):
    image = upload_media(author)
    guide = published_guide(author, category.id, steps=[step("One", media=[image])])

    with_alt = save_guide(author, guide, steps=[{**guide["steps"][0], "media": [{**image, "alt": "The turret"}]}])
    assert with_alt["hasUnpublishedChanges"] is True

    author.post(f"/api/guides/{guide['id']}/publish")
    current = author.get(f"/api/guides/{guide['id']}").json()
    annotated = save_guide(
        author,
        current,
        steps=[{**current["steps"][0], "media": [{**current["steps"][0]["media"][0], "annotations": [annotation()]}]}],
    )
    assert annotated["hasUnpublishedChanges"] is True


def test_reading_a_guide_does_not_flag_it_or_move_its_concurrency_token(author, viewer, category):
    """A view is counted with one UPDATE that leaves ``updatedAt`` alone. If it
    did not, every reader would mark the guide as changed and make the next
    autosave of whoever has it open fail as stale."""
    guide = published_guide(author, category.id)

    for _ in range(3):
        assert viewer.post(f"/api/guides/{guide['id']}/view").status_code == 204

    after = author.get(f"/api/guides/{guide['id']}").json()
    assert after["viewCount"] == 3
    assert after["updatedAt"] == guide["updatedAt"]
    assert after["hasUnpublishedChanges"] is False
    assert viewer.get(f"/api/guides/{guide['id']}").json()["viewCount"] == 3, "the count is live, not the snapshot's"
    assert save_guide(author, after, summary="Still saveable.")["summary"] == "Still saveable."


def test_views_are_counted_on_a_guide_with_unpublished_changes_too(edited, viewer, author):
    assert viewer.post(f"/api/guides/{edited['id']}/view").status_code == 204

    assert viewer.get(f"/api/guides/{edited['id']}").json()["viewCount"] == 1
    assert author.get(f"/api/guides/{edited['id']}").json()["updatedAt"] == edited["working"]["updatedAt"]


# ------------------------------------------------------------------------ slug


def test_the_slug_never_follows_the_title(author, viewer, category):
    """A slug is given when the item is created and is its address from then
    on: not on save, not on publish. Readers' links and the wiki's own links to
    a guide keep resolving however often it is renamed."""
    guide = create_guide(author, category.id, "Aligning the Confocal")
    assert guide["slug"] == "aligning-the-confocal"

    renamed_draft = save_guide(author, guide, title="Koehler Illumination", steps=[step("One", bullets=[bullet("x")])])
    assert renamed_draft["slug"] == "aligning-the-confocal"

    published_once = author.post(f"/api/guides/{guide['id']}/publish").json()
    assert published_once["slug"] == "aligning-the-confocal"

    save_guide(author, published_once, title="Something Else Entirely")
    republished = author.post(f"/api/guides/{guide['id']}/publish").json()
    assert republished["slug"] == "aligning-the-confocal"
    assert viewer.get("/api/guides/aligning-the-confocal").json()["title"] == "Something Else Entirely"
    assert viewer.get("/api/guides/something-else-entirely").status_code == 404


def test_a_pages_slug_is_fixed_the_same_way(author, viewer):
    page = published_page(author, "Booking Rules")

    save_page(author, page, title="Reservation Policy")
    author.post(f"/api/pages/{page['id']}/publish")

    assert viewer.get("/api/pages/booking-rules").json()["title"] == "Reservation Policy"


# ----------------------------------------------------------- unpublish, archive


def test_unpublishing_withdraws_the_snapshot_from_every_route(edited, viewer, author):
    assert author.post(f"/api/guides/{edited['id']}/unpublish").status_code == 200

    assert viewer.get(f"/api/guides/{edited['slug']}").status_code == 404
    assert viewer.get("/api/guides").json() == []
    assert search_hits(viewer, "mercury") == []
    assert tag_counts(viewer) == {}
    assert viewer.get(f"/api/guides/{edited['slug']}/pdf").status_code == 404
    assert viewer.get(f"/api/media/{edited['old_image']['id']}").status_code == 404
    assert author.get(f"/api/guides/{edited['id']}").json()["hasUnpublishedChanges"] is False, "a draft is all working copy"


def test_archiving_withdraws_it_too(edited, viewer, admin, db_session):
    assert admin.delete(f"/api/guides/{edited['id']}").status_code == 204

    assert viewer.get(f"/api/guides/{edited['slug']}").status_code == 404
    assert viewer.get(f"/api/media/{edited['old_image']['id']}").status_code == 404
    assert db_session.scalars(select(PublishedGuide)).all() == []
    assert db_session.scalars(select(PublishedGuideTag)).all() == []
    assert db_session.scalars(select(PublishedGuideMedia)).all() == []


def test_republishing_after_unpublishing_serves_the_working_copy_as_a_new_version(edited, viewer, author):
    author.post(f"/api/guides/{edited['id']}/unpublish")

    again = author.post(f"/api/guides/{edited['id']}/publish").json()

    assert again["version"] == 2
    assert viewer.get(f"/api/guides/{edited['slug']}").json()["title"] == "Starting the LED Widefield"


def test_a_status_changed_behind_the_lifecycles_back_still_hides_the_guide(edited, viewer, db_session):
    """The importer sets a status directly to keep vendor dates. A projection
    row it leaves behind must not keep a withdrawn guide visible: every
    reader-facing query tests the status as well as the projection."""
    guide = db_session.get(Guide, edited["id"])
    guide.status = "draft"
    db_session.commit()
    assert db_session.get(PublishedGuide, edited["id"]) is not None, "the leftover this test is about"

    assert viewer.get(f"/api/guides/{edited['slug']}").status_code == 404
    assert viewer.get("/api/guides").json() == []
    assert search_hits(viewer, "mercury") == []
    assert tag_counts(viewer) == {}
    assert viewer.get(f"/api/media/{edited['old_image']['id']}").status_code == 404
    assert viewer.get(f"/api/guides/{edited['slug']}/pdf").status_code == 404

    assert published.withdraw_stale(db_session) == 1
    db_session.commit()
    assert db_session.get(PublishedGuide, edited["id"]) is None


# ------------------------------------------------------------- discard changes


def test_discarding_changes_puts_the_published_version_back_in_the_editor(edited, author, viewer):
    reverted = author.post(f"/api/guides/{edited['id']}/revert")

    assert reverted.status_code == 200, reverted.text
    body = reverted.json()
    assert body["title"] == "Starting the Widefield"
    assert body["summary"] == "The published summary."
    assert body["tags"] == ["lamp", "widefield"]
    assert (body["difficulty"], body["timeRequiredMinMinutes"], body["timeRequiredMaxMinutes"]) == ("easy", 5, 10)
    assert [s["title"] for s in body["steps"]] == ["Lamp"]
    assert body["steps"][0]["bullets"][0]["text"] == OLD_TEXT
    assert [m["id"] for m in body["steps"][0]["media"]] == [edited["old_image"]["id"]]
    assert body["hasUnpublishedChanges"] is False
    assert body["version"] == 1 and body["status"] == "published"
    assert instant(body["updatedAt"]) > instant(edited["working"]["updatedAt"]), "an open editor's copy is now stale"

    assert author.get(f"/api/guides/{edited['id']}").json() == body
    assert viewer.get(f"/api/guides/{edited['slug']}").json()["title"] == "Starting the Widefield"
    assert save_guide(author, body, summary="Editable again.")["hasUnpublishedChanges"] is True


def test_the_restored_steps_keep_the_identifiers_the_snapshot_had(edited, author):
    body = author.post(f"/api/guides/{edited['id']}/revert").json()

    assert body["steps"][0]["id"] == edited["first"]["steps"][0]["id"]
    assert body["steps"][0]["bullets"][0]["id"] == edited["first"]["steps"][0]["bullets"][0]["id"]


def test_discarding_works_when_the_edit_moved_a_bullet_between_steps(author, category):
    """The snapshot wants the bullet back in its first step. Reconciling step by
    step would refuse it as belonging to something else."""
    guide = published_guide(
        author, category.id, steps=[step("One", bullets=[bullet("Mine")]), step("Two", bullets=[bullet("Other")])]
    )
    one, two = guide["steps"]
    save_guide(author, guide, steps=[{**two, "bullets": two["bullets"]}, step("Fresh", bullets=[bullet("New")])])

    body = author.post(f"/api/guides/{guide['id']}/revert").json()

    assert [(s["title"], [b["text"] for b in s["bullets"]]) for s in body["steps"]] == [("One", ["Mine"]), ("Two", ["Other"])]
    assert [s["id"] for s in body["steps"]] == [one["id"], two["id"]]


def test_discarding_is_refused_when_there_is_no_published_version(author, category):
    draft = create_guide(author, category.id)
    assert author.post(f"/api/guides/{draft['id']}/revert").status_code == 409

    guide = published_guide(author, category.id, "Withdrawn")
    author.post(f"/api/guides/{guide['id']}/unpublish")
    refused = author.post(f"/api/guides/{guide['id']}/revert")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "conflict"

    assert author.post("/api/guides/01JQNOTAREALULID0000000000/revert").status_code == 404


def test_discarding_is_an_authors_action_and_is_audited(edited, viewer, author, db_session):
    from app.models import AuditLog

    assert viewer.post(f"/api/guides/{edited['id']}/revert").status_code == 403

    author.post(f"/api/guides/{edited['id']}/revert")

    entry = db_session.scalars(select(AuditLog).where(AuditLog.action == "guide.revert")).one()
    assert entry.entity_id == edited["id"] and entry.detail == {"version": 1}


def test_discarding_with_nothing_to_discard_is_harmless(author, category):
    guide = published_guide(author, category.id)

    body = author.post(f"/api/guides/{guide['id']}/revert").json()

    assert body["hasUnpublishedChanges"] is False and body["title"] == guide["title"]


# ---------------------------------------------------------------------- pages


@pytest.fixture()
def edited_page(author, category):
    old_hero = upload_media(author, image_bytes(30, 30, color="#001122"))
    old_inline = upload_media(author, image_bytes(31, 31, color="#002244"))
    created = create_page(author, "Booking Rules", categoryId=category.id, isLanding=True)
    save_page(
        author,
        created,
        summary="The published summary.",
        body=f"Book the confocal in advance. ![plan](/api/media/{old_inline['id']})",
        heroMediaId=old_hero["id"],
        heroAlt="The booking desk",
        categoryId=category.id,
        isLanding=True,
    )
    first = author.post(f"/api/pages/{created['id']}/publish").json()

    new_hero = upload_media(author, image_bytes(32, 32, color="#aa0000"))
    new_inline = upload_media(author, image_bytes(33, 33, color="#bb0000"))
    working = save_page(
        author,
        first,
        title="Reservation Policy",
        summary="An unpublished summary.",
        body=f"Unpublished: walk-ins are welcome. ![new](/api/media/{new_inline['id']})",
        heroMediaId=new_hero["id"],
        heroAlt="A new desk",
    )
    return {
        "id": created["id"],
        "slug": created["slug"],
        "first": first,
        "working": working,
        "old": (old_hero, old_inline),
        "new": (new_hero, new_inline),
        "category_id": category.id,
    }


def test_a_pages_unpublished_edit_reaches_a_viewer_by_no_route(edited_page, viewer):
    for key in (edited_page["id"], edited_page["slug"]):
        body = viewer.get(f"/api/pages/{key}").json()
        assert body["title"] == "Booking Rules"
        assert body["body"].startswith("Book the confocal in advance.")
        assert body["heroMediaId"] == edited_page["old"][0]["id"]
        assert body["heroAlt"] == "The booking desk"
        assert body["hasUnpublishedChanges"] is False
        assert "walk-ins" not in body["body"]

    listing = viewer.get("/api/pages").json()
    assert [(p["title"], p["summary"]) for p in listing] == [("Booking Rules", "The published summary.")]
    assert viewer.get("/api/pages", params={"q": "Reservation"}).json() == []
    assert search_hits(viewer, "walk-ins") == []
    assert search_hits(viewer, "in advance") == ["Booking Rules"]

    landing = viewer.get(f"/api/categories/{edited_page['category_id']}/page").json()
    assert landing["title"] == "Booking Rules" and "walk-ins" not in landing["body"]

    for old in edited_page["old"]:
        assert viewer.get(f"/api/media/{old['id']}").status_code == 200
    for new in edited_page["new"]:
        assert viewer.get(f"/api/media/{new['id']}").status_code == 404


def test_publishing_a_pages_edit_moves_every_route(edited_page, viewer, author):
    assert author.post(f"/api/pages/{edited_page['id']}/publish").status_code == 200

    body = viewer.get(f"/api/pages/{edited_page['slug']}").json()
    assert (body["title"], body["heroAlt"], body["version"]) == ("Reservation Policy", "A new desk", 2)
    assert [p["title"] for p in viewer.get("/api/pages").json()] == ["Reservation Policy"]
    assert search_hits(viewer, "walk-ins") == ["Reservation Policy"]
    assert search_hits(viewer, "in advance") == []
    assert viewer.get(f"/api/categories/{edited_page['category_id']}/page").json()["title"] == "Reservation Policy"
    for new in edited_page["new"]:
        assert viewer.get(f"/api/media/{new['id']}").status_code == 200
    for old in edited_page["old"]:
        assert viewer.get(f"/api/media/{old['id']}").status_code == 404


def test_an_author_gets_a_pages_working_copy_and_can_ask_for_the_published_one(edited_page, author, viewer):
    working = author.get(f"/api/pages/{edited_page['slug']}").json()
    assert working["title"] == "Reservation Policy" and working["hasUnpublishedChanges"] is True

    as_reader = author.get(f"/api/pages/{edited_page['slug']}", params={"view": "published"}).json()
    assert as_reader["title"] == "Booking Rules" and as_reader["hasUnpublishedChanges"] is True
    assert {**as_reader, "hasUnpublishedChanges": False} == viewer.get(f"/api/pages/{edited_page['slug']}").json()

    listing = author.get("/api/pages").json()
    assert [(p["title"], p["hasUnpublishedChanges"]) for p in listing] == [("Reservation Policy", True)]
    assert search_hits(author, "walk-ins") == ["Reservation Policy"]

    category = edited_page["category_id"]
    assert author.get(f"/api/categories/{category}/page").json()["title"] == "Reservation Policy"
    published_landing = author.get(f"/api/categories/{category}/page", params={"view": "published"}).json()
    assert published_landing["title"] == "Booking Rules" and published_landing["hasUnpublishedChanges"] is True


def test_a_page_save_that_changes_nothing_is_not_a_change(author):
    page = published_page(author, "Rules", body="Text.")

    assert save_page(author, page)["hasUnpublishedChanges"] is False
    changed = save_page(author, author.get(f"/api/pages/{page['id']}").json(), body="Other text.")
    assert changed["hasUnpublishedChanges"] is True
    assert save_page(author, changed, body="Text.")["hasUnpublishedChanges"] is False


def test_discarding_a_pages_changes_restores_everything(edited_page, author, viewer):
    body = author.post(f"/api/pages/{edited_page['id']}/revert").json()

    assert body["title"] == "Booking Rules"
    assert body["body"].startswith("Book the confocal in advance.")
    assert (body["heroMediaId"], body["heroAlt"]) == (edited_page["old"][0]["id"], "The booking desk")
    assert (body["isLanding"], body["categoryId"]) == (True, edited_page["category_id"])
    assert body["hasUnpublishedChanges"] is False
    assert viewer.get(f"/api/pages/{edited_page['slug']}").json()["title"] == "Booking Rules"
    assert author.post(f"/api/pages/{create_page(author, 'Draft only')['id']}/revert").status_code == 409


def test_unpublishing_a_page_withdraws_it_and_its_images(edited_page, viewer, author, db_session):
    assert author.post(f"/api/pages/{edited_page['id']}/unpublish").status_code == 200

    assert viewer.get(f"/api/pages/{edited_page['slug']}").status_code == 404
    assert viewer.get(f"/api/categories/{edited_page['category_id']}/page").json() is None
    for old in edited_page["old"]:
        assert viewer.get(f"/api/media/{old['id']}").status_code == 404
    assert db_session.scalars(select(PublishedPage)).all() == []
    assert db_session.scalars(select(PublishedPageMedia)).all() == []


def test_a_landing_page_moved_in_an_unpublished_edit_stays_put_for_readers(author, viewer, db_session, category):
    """Which page is a category's landing page is content like the rest of it."""
    from app.models import Category

    other = Category(slug="electron-microscopy", name="Electron Microscopy", order_index=1)
    db_session.add(other)
    db_session.commit()
    page = published_page(author, "Light Microscopy", body="Welcome.", categoryId=category.id, isLanding=True)

    save_page(author, page, categoryId=other.id)

    assert viewer.get(f"/api/categories/{category.id}/page").json()["title"] == "Light Microscopy"
    assert viewer.get(f"/api/categories/{other.id}/page").json() is None
    assert viewer.get("/api/pages", params={"categoryId": category.id}).json()[0]["id"] == page["id"]
    assert viewer.get("/api/pages", params={"categoryId": other.id}).json() == []
    assert author.get(f"/api/categories/{other.id}/page").json()["title"] == "Light Microscopy"


def test_a_category_cannot_be_deleted_from_under_a_published_version(author, admin, viewer, db_session, category):
    from app.models import Category

    other = Category(slug="electron-microscopy", name="Electron Microscopy", order_index=1)
    db_session.add(other)
    db_session.commit()
    guide = published_guide(author, other.id, "Filed under EM")
    save_guide(author, guide, categoryId=category.id)

    refused = admin.delete(f"/api/categories/{other.id}")
    assert refused.status_code == 409
    assert "still published" in refused.json()["error"]["message"]
    assert viewer.get(f"/api/guides/{guide['slug']}").json()["categoryId"] == other.id

    author.post(f"/api/guides/{guide['id']}/publish")
    assert admin.delete(f"/api/categories/{other.id}").status_code == 204


def test_a_viewers_category_filter_uses_the_published_category(author, viewer, db_session, category):
    from app.models import Category

    other = Category(slug="electron-microscopy", name="Electron Microscopy", order_index=1)
    db_session.add(other)
    db_session.commit()
    guide = published_guide(author, category.id, "Moves Later")

    save_guide(author, guide, categoryId=other.id)

    assert guide_titles(viewer, categoryId=category.id) == ["Moves Later"]
    assert guide_titles(viewer, categoryId=other.id) == []
    assert guide_titles(author, categoryId=other.id) == ["Moves Later"]


# ------------------------------------------------------ the projection itself


def test_the_projection_is_written_with_the_snapshot_and_points_at_it(edited, db_session):
    row = db_session.get(PublishedGuide, edited["id"])
    revision = db_session.get(GuideRevision, row.revision_id)

    assert revision.version == 1
    assert (row.title, row.summary, row.difficulty, row.step_count) == (
        "Starting the Widefield", "The published summary.", "easy", 1,
    )
    assert row.search_text == f"Lamp\n{OLD_TEXT}"
    assert row.tag_slugs == ["lamp", "widefield"]
    media = db_session.scalars(select(PublishedGuideMedia.media_id)).all()
    assert media == [edited["old_image"]["id"]]


def test_a_rebuilt_projection_equals_the_stored_one(edited, edited_page, db_session):
    """``project_*`` reads only the snapshot, so running it again must be a
    no-op. This is also what makes the migration's backfill trustworthy: it is
    the same derivation."""
    def state() -> tuple:
        db_session.expire_all()
        guide = db_session.get(PublishedGuide, edited["id"])
        page = db_session.get(PublishedPage, edited_page["id"])
        return (
            (guide.revision_id, guide.title, guide.summary, guide.category_id, guide.search_text, guide.tag_slugs),
            sorted(db_session.scalars(select(PublishedGuideMedia.media_id))),
            (page.revision_id, page.title, page.summary, page.category_id, page.is_landing, page.body),
            sorted(db_session.scalars(select(PublishedPageMedia.media_id))),
        )

    before = state()
    guide_row, page_row = db_session.get(PublishedGuide, edited["id"]), db_session.get(PublishedPage, edited_page["id"])
    published.project_guide(db_session, db_session.get(Guide, edited["id"]), guide_row.revision)
    published.project_page(db_session, db_session.get(Page, edited_page["id"]), page_row.revision)
    db_session.commit()

    assert state() == before
    assert sorted(before[3]) == sorted(media["id"] for media in edited_page["old"])


def test_a_readers_listing_costs_the_same_however_many_guides_it_returns(author, viewer, category, db_session):
    """A landing page embeds lists of eighty guides. One statement per guide, or
    one snapshot opened per guide, would make that page unusable."""
    def statements_for(count: int) -> int:
        for index in range(count):
            published_guide(author, category.id, f"Guide {index} of {count}", tags=["confocal", f"t{index}"])
        seen: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):
            seen.append(statement)

        engine = db_session.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            response = viewer.get("/api/guides", params={"tags": "confocal"})
            found = viewer.get("/api/search", params={"q": "Guide"})
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert response.status_code == 200 and found.status_code == 200
        assert not any("guide_revisions" in statement for statement in seen), "no snapshot is opened for a listing"
        return len(seen)

    few = statements_for(2)
    many = statements_for(12)

    assert many == few
    assert len(viewer.get("/api/guides", params={"tags": "confocal"}).json()) == 14


def test_old_snapshots_are_served_in_the_current_contract(author, viewer, category, db_session):
    """A snapshot written before ``displayUrl`` and ``hasUnpublishedChanges``
    existed is still a valid thing to serve."""
    image = upload_media(author)
    guide = published_guide(author, category.id, steps=[step("One", media=[image])])
    revision = db_session.scalars(select(GuideRevision)).one()
    document = dict(revision.document)
    document.pop("hasUnpublishedChanges")
    document["steps"] = [
        {**s, "media": [{k: v for k, v in m.items() if k != "displayUrl"} for m in s["media"]]} for s in document["steps"]
    ]
    revision.document = document
    db_session.commit()

    for body in (
        viewer.get(f"/api/guides/{guide['slug']}").json(),
        author.get(f"/api/guides/{guide['id']}/revisions/1").json(),
    ):
        assert body["hasUnpublishedChanges"] is False
        assert body["steps"][0]["media"][0]["displayUrl"] == f"/api/media/{image['id']}?size=display"
