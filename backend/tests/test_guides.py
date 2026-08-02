"""Guide lifecycle: creation, listing visibility, publish, revisions, archive."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Guide, Step

from .conftest import bullet, create_guide, document_from, step


def test_author_creates_a_draft_with_sane_defaults(author, category):
    body = create_guide(author, category.id, title="Aligning the Confocal")

    assert body["status"] == "draft"
    assert body["version"] == 0
    assert body["slug"] == "aligning-the-confocal"
    assert body["tags"] == []
    assert body["summary"] == ""
    assert body["introduction"] == ""
    assert body["conclusion"] == ""
    assert body["difficulty"] == "moderate"
    assert body["timeRequiredMinMinutes"] is None
    assert body["timeRequiredMaxMinutes"] is None
    assert body["viewCount"] == 0
    assert body["isQuickLink"] is False
    assert body["publishedAt"] is None
    assert body["categoryId"] == category.id
    assert body["author"] == {"id": body["lastEditedBy"]["id"], "displayName": "Author"}
    assert set(body["author"]) == {"id", "displayName"}
    assert body["contributors"] == [body["author"]]
    assert body["createdAt"].endswith("Z")


def test_a_new_draft_opens_with_one_empty_step_ready_to_type_into(author, category):
    """The button says "create and start writing", so there is something to write in.

    An editor whose only control is "Add step" makes an author perform one piece
    of ceremony before the first word of every guide they will ever write.
    """
    body = create_guide(author, category.id)

    assert len(body["steps"]) == 1
    step_one = body["steps"][0]
    assert step_one["orderIndex"] == 0
    assert step_one["title"] == ""
    assert step_one["media"] == [] and step_one["video"] is None
    # One empty bullet, matching what the editor's own "add step" produces.
    assert len(step_one["bullets"]) == 1
    assert step_one["bullets"][0]["text"] == ""
    assert step_one["bullets"][0]["color"] == "black"
    assert step_one["bullets"][0]["icon"] is None
    assert step_one["bullets"][0]["level"] == 0


def test_guide_response_matches_the_domain_model_exactly(author, category):
    body = create_guide(author, category.id)

    assert set(body) == {
        "id",
        "slug",
        "title",
        "summary",
        "categoryId",
        "tags",
        "difficulty",
        "timeRequiredMinMinutes",
        "timeRequiredMaxMinutes",
        "introduction",
        "conclusion",
        "status",
        "isQuickLink",
        "steps",
        "author",
        "lastEditedBy",
        "contributors",
        "viewCount",
        "createdAt",
        "updatedAt",
        "publishedAt",
        "version",
    }


def test_creating_a_guide_in_an_unknown_category_is_rejected(author):
    response = author.post(
        "/api/guides", json={"title": "Orphan", "categoryId": "01JQNOTAREALULID00000000"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_blank_guide_title_is_rejected(author, category):
    response = author.post("/api/guides", json={"title": "   ", "categoryId": category.id})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


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
    author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("One"), step("Two")]),
    )

    entry = author.get("/api/guides").json()[0]

    assert set(entry) == {
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
        "isQuickLink",
        "stepCount",
        "author",
        "viewCount",
        "thumbnailUrl",
        "updatedAt",
        "publishedAt",
    }
    assert entry["stepCount"] == 2


def test_listing_filters_by_category_author_and_free_text(author, admin, category, db_session):
    other = admin.post("/api/categories", json={"name": "Electron Microscopy"}).json()
    create_guide(author, category.id, "Confocal Alignment")
    create_guide(author, other["id"], "Cryo Sectioning")
    admin_guide = create_guide(admin, category.id, "Vacuum Maintenance")

    assert [
        g["title"] for g in author.get("/api/guides", params={"categoryId": other["id"]}).json()
    ] == ["Cryo Sectioning"]
    assert [g["title"] for g in author.get("/api/guides", params={"q": "confocal"}).json()] == [
        "Confocal Alignment"
    ]
    assert [
        g["title"]
        for g in author.get("/api/guides", params={"authorId": admin_guide["author"]["id"]}).json()
    ] == ["Vacuum Maintenance"]


def test_free_text_search_also_covers_the_summary(author, category):
    created = create_guide(author, category.id, "Nothing Matching Here")
    author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, summary="Uses the cryostat daily."),
    )

    assert [g["title"] for g in author.get("/api/guides", params={"q": "cryostat"}).json()] == [
        "Nothing Matching Here"
    ]


# --- quick links ----------------------------------------------------------


def test_an_author_marks_a_guide_as_a_quick_link(author, category):
    created = create_guide(author, category.id, "Book an Instrument")

    saved = author.put(
        f"/api/guides/{created['id']}", json=document_from(created, isQuickLink=True)
    )

    assert saved.status_code == 200
    assert saved.json()["isQuickLink"] is True
    assert author.get(f"/api/guides/{created['id']}").json()["isQuickLink"] is True


def test_a_quick_link_can_be_taken_back_off_the_front_page(author, category):
    created = create_guide(author, category.id, "Book an Instrument")
    author.put(f"/api/guides/{created['id']}", json=document_from(created, isQuickLink=True))

    reloaded = author.get(f"/api/guides/{created['id']}").json()
    saved = author.put(
        f"/api/guides/{created['id']}", json=document_from(reloaded, isQuickLink=False)
    )

    assert saved.json()["isQuickLink"] is False


def test_the_flag_reaches_the_summary_because_that_is_what_the_lists_render(author, category):
    """A quick link is drawn from a listing, not from a fetch of every guide."""
    created = create_guide(author, category.id, "Get Building Access")
    author.put(f"/api/guides/{created['id']}", json=document_from(created, isQuickLink=True))

    entry = author.get("/api/guides").json()[0]

    assert entry["isQuickLink"] is True


def test_asking_for_quick_links_returns_only_those(author, category):
    quick = create_guide(author, category.id, "Book an Instrument")
    create_guide(author, category.id, "Aligning the Confocal")
    author.put(f"/api/guides/{quick['id']}", json=document_from(quick, isQuickLink=True))

    listing = author.get("/api/guides", params={"quickLink": "true"}).json()

    assert [entry["title"] for entry in listing] == ["Book an Instrument"]
    assert [
        entry["title"] for entry in author.get("/api/guides", params={"quickLink": "false"}).json()
    ] == ["Aligning the Confocal"]


def test_a_quick_link_a_viewer_may_not_see_is_still_hidden_from_them(author, viewer, category):
    """Promotion is not publication: an unpublished quick link is still a draft."""
    created = create_guide(author, category.id, "Book an Instrument")
    author.put(f"/api/guides/{created['id']}", json=document_from(created, isQuickLink=True))

    assert viewer.get("/api/guides", params={"quickLink": "true"}).json() == []


def test_a_viewer_cannot_promote_a_guide(author, viewer, category):
    created = create_guide(author, category.id, "Book an Instrument")

    response = viewer.put(
        f"/api/guides/{created['id']}", json=document_from(created, isQuickLink=True)
    )

    assert response.status_code == 403
    assert author.get(f"/api/guides/{created['id']}").json()["isQuickLink"] is False


def test_the_flag_is_part_of_the_published_snapshot(author, category):
    created = create_guide(author, category.id, "Book an Instrument")
    author.put(f"/api/guides/{created['id']}", json=document_from(created, isQuickLink=True))

    author.post(f"/api/guides/{created['id']}/publish")

    assert author.get(f"/api/guides/{created['id']}/revisions/1").json()["isQuickLink"] is True


def test_archived_guides_are_excluded_unless_asked_for(author, admin, category):
    created = create_guide(author, category.id)
    admin.delete(f"/api/guides/{created['id']}")

    assert author.get("/api/guides").json() == []
    assert [g["id"] for g in author.get("/api/guides", params={"status": "archived"}).json()] == [
        created["id"]
    ]


def test_publishing_increments_the_version_and_stamps_the_time(author, category):
    created = create_guide(author, category.id)

    response = author.post(f"/api/guides/{created['id']}/publish")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "published"
    assert body["version"] == 1
    assert body["publishedAt"] is not None and body["publishedAt"].endswith("Z")


def test_publishing_writes_an_immutable_snapshot(author, category):
    created = create_guide(author, category.id, "Snapshot Guide")
    author.put(
        f"/api/guides/{created['id']}",
        json=document_from(
            created, steps=[step("Original title", bullets=[bullet("Original bullet")])]
        ),
    )
    published = author.post(f"/api/guides/{created['id']}/publish").json()

    reloaded = author.get(f"/api/guides/{created['id']}").json()
    author.put(
        f"/api/guides/{created['id']}", json=document_from(reloaded, steps=[step("Rewritten")])
    )

    snapshot = author.get(f"/api/guides/{created['id']}/revisions/1").json()

    assert snapshot["version"] == 1
    assert [s["title"] for s in snapshot["steps"]] == ["Original title"]
    assert snapshot["steps"][0]["bullets"][0]["text"] == "Original bullet"
    assert snapshot["title"] == published["title"]


def test_republishing_adds_a_second_revision(author, category):
    created = create_guide(author, category.id)
    author.post(f"/api/guides/{created['id']}/publish")
    reloaded = author.get(f"/api/guides/{created['id']}").json()
    author.put(f"/api/guides/{created['id']}", json=document_from(reloaded, title="Renamed"))
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
    created = create_guide(author, category.id)
    author.post(f"/api/guides/{created['id']}/publish")

    assert viewer.get(f"/api/guides/{created['id']}/revisions").status_code == 403
    assert viewer.get(f"/api/guides/{created['id']}/revisions/1").status_code == 403


def test_a_published_guide_becomes_visible_to_viewers(author, viewer, category):
    created = create_guide(author, category.id, "Public Guide")
    author.post(f"/api/guides/{created['id']}/publish")

    assert [g["title"] for g in viewer.get("/api/guides").json()] == ["Public Guide"]
    assert viewer.get(f"/api/guides/{created['slug']}").json()["version"] == 1


def test_unpublishing_hides_the_guide_again(author, viewer, category):
    created = create_guide(author, category.id)
    author.post(f"/api/guides/{created['id']}/publish")

    response = author.post(f"/api/guides/{created['id']}/unpublish")

    assert response.status_code == 200
    assert response.json()["status"] == "draft"
    assert viewer.get("/api/guides").json() == []
    assert viewer.get(f"/api/guides/{created['slug']}").status_code == 404


def test_unpublishing_keeps_the_version_and_the_history(author, category):
    created = create_guide(author, category.id)
    author.post(f"/api/guides/{created['id']}/publish")
    unpublished = author.post(f"/api/guides/{created['id']}/unpublish").json()

    assert unpublished["version"] == 1
    assert len(author.get(f"/api/guides/{created['id']}/revisions").json()) == 1


def test_unpublishing_a_draft_conflicts(author, category):
    created = create_guide(author, category.id)

    response = author.post(f"/api/guides/{created['id']}/unpublish")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_publishing_an_archived_guide_conflicts(author, admin, category):
    created = create_guide(author, category.id)
    admin.delete(f"/api/guides/{created['id']}")

    assert author.post(f"/api/guides/{created['id']}/publish").status_code == 409


def test_viewers_cannot_publish(author, viewer, category):
    created = create_guide(author, category.id)

    assert viewer.post(f"/api/guides/{created['id']}/publish").status_code == 403


def test_only_an_admin_archives_and_the_content_survives(author, admin, category, db_session):
    created = create_guide(author, category.id)
    author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("Keep me", bullets=[bullet("Still here")])]),
    )

    assert author.delete(f"/api/guides/{created['id']}").status_code == 403

    assert admin.delete(f"/api/guides/{created['id']}").status_code == 204

    stored = db_session.get(Guide, created["id"])
    db_session.refresh(stored)
    assert stored.status == "archived"
    assert db_session.scalars(select(Step).where(Step.guide_id == created["id"])).all()


def test_an_archived_guide_is_invisible_to_viewers(author, admin, viewer, category):
    created = create_guide(author, category.id)
    author.post(f"/api/guides/{created['id']}/publish")
    admin.delete(f"/api/guides/{created['id']}")

    assert viewer.get(f"/api/guides/{created['slug']}").status_code == 404


def test_guide_endpoints_require_a_session(anon, category):
    assert anon.get("/api/guides").status_code == 401
    assert anon.get("/api/guides/anything").status_code == 401
