"""Guide lifecycle: creation, listing visibility, publish, revisions, archive."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Guide, Step

from .conftest import bullet, create_guide, document_from, publish_guide, save_guide, step

GUIDE_FIELDS = {
    "id", "slug", "title", "summary", "categoryId", "tags", "difficulty",
    "timeRequiredMinMinutes", "timeRequiredMaxMinutes", "introduction", "conclusion",
    "status", "steps", "author", "lastEditedBy", "contributors", "viewCount",
    "createdAt", "updatedAt", "publishedAt", "version",
}

SUMMARY_FIELDS = {
    "id", "slug", "title", "summary", "categoryId", "tags", "difficulty",
    "timeRequiredMinMinutes", "timeRequiredMaxMinutes", "status", "stepCount",
    "author", "viewCount", "updatedAt", "publishedAt",
}


def test_author_creates_a_draft_with_sane_defaults(author, category):
    body = create_guide(author, category.id, title="Aligning the Confocal")

    assert body["status"] == "draft"
    assert body["version"] == 0
    assert body["slug"] == "aligning-the-confocal"
    assert body["steps"] == []
    assert body["tags"] == []
    assert body["summary"] == ""
    assert body["introduction"] == ""
    assert body["conclusion"] == ""
    assert body["difficulty"] == "moderate"
    assert body["timeRequiredMinMinutes"] is None
    assert body["timeRequiredMaxMinutes"] is None
    assert body["viewCount"] == 0
    assert body["publishedAt"] is None
    assert body["categoryId"] == category.id
    assert body["author"] == {"id": body["lastEditedBy"]["id"], "displayName": "Author"}
    assert body["contributors"] == [body["author"]]
    assert set(body["author"]) == {"id", "displayName"}
    assert body["createdAt"].endswith("Z")


def test_guide_response_matches_the_domain_model_exactly(author, category):
    """Field for field what ``Guide`` in ``types.ts`` declares — and no
    ``prerequisiteIds``, which the measured model dropped."""
    body = create_guide(author, category.id)

    assert set(body) == GUIDE_FIELDS


def test_creating_a_guide_in_an_unknown_category_is_rejected(author):
    response = author.post("/api/guides", json={"title": "Orphan", "categoryId": "01JQNOTAREALULID00000000"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_creating_a_guide_with_a_blank_title_is_rejected(author, category):
    response = author.post("/api/guides", json={"title": "   ", "categoryId": category.id})

    assert response.status_code == 422


def test_viewers_cannot_create_guides(viewer, category):
    response = viewer.post("/api/guides", json={"title": "Nope", "categoryId": category.id})

    assert response.status_code == 403


def test_duplicate_titles_get_distinct_slugs(author, category):
    first = create_guide(author, category.id, "Cleaning the Objective")
    second = create_guide(author, category.id, "Cleaning the Objective")

    assert first["slug"] == "cleaning-the-objective"
    assert second["slug"] == "cleaning-the-objective-2"


def test_a_guide_resolves_by_id_and_by_slug(author, category):
    created = create_guide(author, category.id)

    by_id = author.get(f"/api/guides/{created['id']}").json()
    by_slug = author.get(f"/api/guides/{created['slug']}").json()

    assert by_id == by_slug == created


def test_an_unknown_guide_is_not_found(author):
    response = author.get("/api/guides/no-such-guide")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_viewers_never_receive_drafts_in_a_listing(author, viewer, category):
    create_guide(author, category.id, "Unfinished Draft")

    assert viewer.get("/api/guides").json() == []


def test_a_viewer_asking_for_drafts_explicitly_still_gets_nothing(author, viewer, category):
    create_guide(author, category.id, "Unfinished Draft")

    assert viewer.get("/api/guides", params={"status": "draft"}).json() == []
    assert viewer.get("/api/guides", params={"status": "in_review"}).json() == []
    assert viewer.get("/api/guides", params={"status": "archived"}).json() == []


def test_an_unknown_status_filter_is_rejected(author):
    response = author.get("/api/guides", params={"status": "deleted"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_viewer_cannot_open_a_draft_by_slug(author, viewer, category):
    created = create_guide(author, category.id, "Secret Draft")

    response = viewer.get(f"/api/guides/{created['slug']}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_authors_see_their_drafts_in_the_listing(author, category):
    created = create_guide(author, category.id, "Work In Progress")

    listing = author.get("/api/guides").json()

    assert len(listing) == 1
    assert listing[0]["id"] == created["id"]
    assert listing[0]["status"] == "draft"


def test_summary_projection_matches_the_domain_model(author, category):
    created = create_guide(author, category.id)
    save_guide(author, created, steps=[step("One"), step("Two")], tags=["LAS X", "confocal"])

    entry = author.get("/api/guides").json()[0]

    assert set(entry) == SUMMARY_FIELDS
    assert entry["stepCount"] == 2
    assert entry["tags"] == ["confocal", "las-x"]


def test_the_listing_is_newest_update_first(author, category):
    first = create_guide(author, category.id, "First")
    create_guide(author, category.id, "Second")
    save_guide(author, first, summary="Touched last.")

    assert [g["title"] for g in author.get("/api/guides").json()] == ["First", "Second"]


def test_listing_filters_by_category_author_and_free_text(author, admin, category, db_session):
    other = admin.post("/api/categories", json={"name": "Electron Microscopy"}).json()
    create_guide(author, category.id, "Confocal Alignment")
    create_guide(author, other["id"], "Cryo Sectioning")
    admin_guide = create_guide(admin, category.id, "Vacuum Maintenance")

    assert [g["title"] for g in author.get("/api/guides", params={"categoryId": other["id"]}).json()] == ["Cryo Sectioning"]
    assert [g["title"] for g in author.get("/api/guides", params={"q": "confocal"}).json()] == ["Confocal Alignment"]
    assert [g["title"] for g in author.get("/api/guides", params={"authorId": admin_guide["author"]["id"]}).json()] == [
        "Vacuum Maintenance"
    ]


def test_free_text_search_also_covers_the_summary(author, category):
    created = create_guide(author, category.id, "Nothing Matching Here")
    save_guide(author, created, summary="Uses the cryostat daily.")

    assert [g["title"] for g in author.get("/api/guides", params={"q": "cryostat"}).json()] == ["Nothing Matching Here"]


def test_free_text_wildcards_are_literal(author, category):
    """A ``%`` typed into the search box is a percent sign, not "match everything"."""
    create_guide(author, category.id, "Plain Title")
    created = create_guide(author, category.id, "Dilute to 4% PFA")

    assert [g["id"] for g in author.get("/api/guides", params={"q": "4%"}).json()] == [created["id"]]
    assert author.get("/api/guides", params={"q": "_"}).json() == []


def test_archived_guides_disappear_for_everyone(author, admin, viewer, category):
    """One visibility rule: an author or admin sees everything *except* the
    archive, so asking for it by name returns nothing rather than a back door."""
    created = publish_guide(author, create_guide(author, category.id))
    assert admin.delete(f"/api/guides/{created['id']}").status_code == 204

    for client in (author, admin, viewer):
        assert client.get("/api/guides").json() == []
        assert client.get("/api/guides", params={"status": "archived"}).json() == []
        assert client.get(f"/api/guides/{created['slug']}").status_code == 404
        assert client.get(f"/api/guides/{created['id']}").status_code == 404


def test_an_archived_guide_can_no_longer_be_written_to(author, admin, category):
    created = create_guide(author, category.id)
    admin.delete(f"/api/guides/{created['id']}")

    assert author.put(f"/api/guides/{created['id']}", json=document_from(created)).status_code == 404
    assert author.post(f"/api/guides/{created['id']}/publish").status_code == 404
    assert author.post(f"/api/guides/{created['id']}/unpublish").status_code == 404
    assert author.get(f"/api/guides/{created['id']}/revisions").status_code == 404
    assert admin.delete(f"/api/guides/{created['id']}").status_code == 404


def test_publishing_increments_the_version_and_stamps_the_time(author, category):
    created = create_guide(author, category.id)
    save_guide(author, created, steps=[step("Only step", bullets=[bullet("Do it.")])])

    response = author.post(f"/api/guides/{created['id']}/publish")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "published"
    assert body["version"] == 1
    assert body["publishedAt"] is not None and body["publishedAt"].endswith("Z")


def test_publishing_needs_at_least_one_step(author, category):
    created = create_guide(author, category.id)

    response = author.post(f"/api/guides/{created['id']}/publish")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert "step" in response.json()["error"]["message"].lower()
    assert author.get(f"/api/guides/{created['id']}").json()["status"] == "draft"


def test_publishing_needs_a_title(author, category):
    created = create_guide(author, category.id)
    save_guide(author, created, title="   ", steps=[step("One", bullets=[bullet("Text")])])

    response = author.post(f"/api/guides/{created['id']}/publish")

    assert response.status_code == 422
    assert "title" in response.json()["error"]["message"].lower()


def test_publishing_names_the_step_that_is_empty(author, category):
    created = create_guide(author, category.id)
    save_guide(
        author,
        created,
        steps=[
            step("Has text", bullets=[bullet("Fine")]),
            step("Mount the sample", bullets=[bullet("   ")]),
            step("", bullets=[]),
        ],
    )

    message = author.post(f"/api/guides/{created['id']}/publish").json()["error"]["message"]

    assert "Step 2" in message
    assert "Mount the sample" in message


def test_an_untitled_empty_step_is_named_by_number_alone(author, category):
    created = create_guide(author, category.id)
    save_guide(author, created, steps=[step("", bullets=[])])

    message = author.post(f"/api/guides/{created['id']}/publish").json()["error"]["message"]

    assert message.startswith("Step 1 has neither")


def test_a_step_with_only_media_is_publishable(author, category):
    from .conftest import upload_media

    created = create_guide(author, category.id)
    save_guide(author, created, steps=[step("Just a picture", media=[upload_media(author)])])

    assert author.post(f"/api/guides/{created['id']}/publish").status_code == 200


def test_publishing_writes_an_immutable_snapshot(author, category):
    created = create_guide(author, category.id, "Snapshot Guide")
    save_guide(author, created, steps=[step("Original title", bullets=[bullet("Original bullet")])])
    published = author.post(f"/api/guides/{created['id']}/publish").json()

    save_guide(author, published, steps=[step("Rewritten", bullets=[bullet("New")])])

    snapshot = author.get(f"/api/guides/{created['id']}/revisions/1").json()

    assert set(snapshot) == GUIDE_FIELDS
    assert snapshot["version"] == 1
    assert [s["title"] for s in snapshot["steps"]] == ["Original title"]
    assert snapshot["steps"][0]["bullets"][0]["text"] == "Original bullet"
    assert snapshot["title"] == published["title"]


def test_republishing_adds_a_second_revision(author, category):
    created = create_guide(author, category.id)
    first = publish_guide(author, created)
    save_guide(author, first, title="Renamed")
    second = author.post(f"/api/guides/{created['id']}/publish").json()

    revisions = author.get(f"/api/guides/{created['id']}/revisions").json()

    assert second["version"] == 2
    assert [r["version"] for r in revisions] == [2, 1]
    assert set(revisions[0]) == {"version", "publishedAt", "publishedBy"}
    assert revisions[0]["publishedBy"]["displayName"] == "Author"
    assert author.get(f"/api/guides/{created['id']}/revisions/2").json()["title"] == "Renamed"
    assert author.get(f"/api/guides/{created['id']}/revisions/1").json()["title"] != "Renamed"


def test_an_unknown_revision_is_not_found(author, category):
    created = create_guide(author, category.id)

    assert author.get(f"/api/guides/{created['id']}/revisions/7").status_code == 404


def test_viewers_may_not_read_publish_history(author, viewer, category):
    created = publish_guide(author, create_guide(author, category.id))

    assert viewer.get(f"/api/guides/{created['id']}/revisions").status_code == 403
    assert viewer.get(f"/api/guides/{created['id']}/revisions/1").status_code == 403


def test_a_published_guide_becomes_visible_to_viewers(author, viewer, category):
    created = publish_guide(author, create_guide(author, category.id, "Public Guide"))

    assert [g["title"] for g in viewer.get("/api/guides").json()] == ["Public Guide"]
    assert viewer.get(f"/api/guides/{created['slug']}").json()["version"] == 1


def test_unpublishing_hides_the_guide_again(author, viewer, category):
    created = publish_guide(author, create_guide(author, category.id))

    response = author.post(f"/api/guides/{created['id']}/unpublish")

    assert response.status_code == 200
    assert response.json()["status"] == "draft"
    assert viewer.get("/api/guides").json() == []
    assert viewer.get(f"/api/guides/{created['slug']}").status_code == 404


def test_unpublishing_keeps_the_version_and_the_history(author, category):
    created = publish_guide(author, create_guide(author, category.id))
    unpublished = author.post(f"/api/guides/{created['id']}/unpublish").json()

    assert unpublished["version"] == 1
    assert len(author.get(f"/api/guides/{created['id']}/revisions").json()) == 1


def test_unpublishing_a_draft_conflicts(author, category):
    created = create_guide(author, category.id)

    response = author.post(f"/api/guides/{created['id']}/unpublish")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_viewers_cannot_publish(author, viewer, category):
    created = create_guide(author, category.id)

    assert viewer.post(f"/api/guides/{created['id']}/publish").status_code == 403
    assert viewer.post(f"/api/guides/{created['id']}/unpublish").status_code == 403


def test_only_an_admin_archives_and_the_content_survives(author, admin, category, db_session):
    created = create_guide(author, category.id)
    save_guide(author, created, steps=[step("Keep me", bullets=[bullet("Still here")])])

    assert author.delete(f"/api/guides/{created['id']}").status_code == 403

    assert admin.delete(f"/api/guides/{created['id']}").status_code == 204

    stored = db_session.get(Guide, created["id"])
    db_session.refresh(stored)
    assert stored.status == "archived"
    assert db_session.scalars(select(Step).where(Step.guide_id == created["id"])).all()


def test_recording_a_view_counts_once_per_call_and_is_not_an_edit(author, viewer, category):
    """The reader page calls this once. It must not move ``updatedAt``, or every
    reader would make the open editor's next autosave conflict."""
    created = publish_guide(author, create_guide(author, category.id))

    assert viewer.post(f"/api/guides/{created['id']}/view").status_code == 204
    assert viewer.post(f"/api/guides/{created['slug']}/view").status_code == 204
    assert author.post(f"/api/guides/{created['id']}/view").status_code == 204

    after = author.get(f"/api/guides/{created['id']}").json()
    assert after["viewCount"] == 3
    assert after["updatedAt"] == created["updatedAt"]
    assert author.get("/api/guides").json()[0]["viewCount"] == 3
    assert save_guide(author, created, summary="Saved against the pre-view token.")["viewCount"] == 3


def test_reading_or_saving_a_guide_does_not_count_as_a_view(author, category):
    created = create_guide(author, category.id)
    author.get(f"/api/guides/{created['id']}")
    saved = save_guide(author, created, summary="Edited.")

    assert saved["viewCount"] == 0


def test_view_count_cannot_be_set_through_the_document(author, category):
    created = create_guide(author, category.id)

    assert save_guide(author, created, viewCount=6745)["viewCount"] == 0


def test_a_viewer_cannot_record_a_view_of_a_draft(author, viewer, category):
    created = create_guide(author, category.id)

    assert viewer.post(f"/api/guides/{created['id']}/view").status_code == 404
    assert author.get(f"/api/guides/{created['id']}").json()["viewCount"] == 0


def test_contributors_accumulate_in_order_without_repeats(author, as_role, category):
    created = create_guide(author, category.id)
    colleague = as_role("author", "colleague@zmb.uzh.ch", display_name="Colleague Editor")

    saved = save_guide(colleague, created, summary="First pass.")
    saved = save_guide(author, saved, summary="Second pass.")
    saved = save_guide(colleague, saved, summary="Third pass.")

    assert [c["displayName"] for c in saved["contributors"]] == ["Author", "Colleague Editor"]
    assert saved["author"]["displayName"] == "Author"


def test_contributors_cannot_be_set_through_the_document(author, category):
    created = create_guide(author, category.id)

    saved = save_guide(author, created, contributors=[{"id": "01JQNOTAREALULID00000000", "displayName": "Ghost"}])

    assert [c["displayName"] for c in saved["contributors"]] == ["Author"]


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/guides"),
        ("GET", "/api/guides/anything"),
        ("GET", "/api/guides/anything/pdf"),
        ("POST", "/api/guides/anything/view"),
        ("GET", "/api/guides/anything/revisions"),
    ],
)
def test_guide_endpoints_require_a_session(anon, method, path):
    """The CSRF pair is supplied so that the 401 is the session check speaking,
    not the CSRF middleware refusing a tokenless POST first."""
    anon.raw.cookies.set("reticle_csrf", "x")

    assert anon.raw.request(method, path, headers={"X-CSRF-Token": "x"}).status_code == 401
