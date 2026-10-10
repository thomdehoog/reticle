"""Wiki pages: the same lifecycle as a guide, plus landing pages and media references."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ulid import ULID

from app.models import Page, PageMedia

from .conftest import (
    create_page,
    document_from,
    instant,
    published_page,
    save_page,
    upload_media,
    upload_video,
)

PAGE_FIELDS = {
    "id", "slug", "title", "summary", "categoryId", "isLanding", "body", "heroMediaId",
    "status", "author", "lastEditedBy", "contributors", "viewCount", "createdAt",
    "updatedAt", "publishedAt", "version",
}

SUMMARY_FIELDS = {
    "id", "slug", "title", "summary", "categoryId", "isLanding", "status", "updatedAt", "publishedAt",
}


def test_an_author_creates_a_standalone_draft(author):
    body = create_page(author, "Booking Rules and Fair Use")

    assert set(body) == PAGE_FIELDS
    assert body["slug"] == "booking-rules-and-fair-use"
    assert body["status"] == "draft"
    assert body["version"] == 0
    assert body["categoryId"] is None
    assert body["isLanding"] is False
    assert body["body"] == ""
    assert body["summary"] == ""
    assert body["heroMediaId"] is None
    assert body["viewCount"] == 0
    assert body["publishedAt"] is None
    assert body["author"] == body["lastEditedBy"] == {"id": body["author"]["id"], "displayName": "Author"}
    assert body["contributors"] == [body["author"]]


def test_a_page_can_be_filed_in_a_category(author, category):
    body = create_page(author, "Objectives", categoryId=category.id)

    assert body["categoryId"] == category.id
    assert body["isLanding"] is False


def test_viewers_cannot_create_pages(viewer):
    response = viewer.post("/api/pages", json={"title": "Nope"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_a_page_needs_a_title_to_be_created(author):
    assert author.post("/api/pages", json={}).status_code == 422
    assert author.post("/api/pages", json={"title": "   "}).status_code == 422


def test_a_page_in_an_unknown_category_is_rejected(author):
    response = author.post("/api/pages", json={"title": "Orphan", "categoryId": str(ULID())})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_duplicate_page_titles_get_distinct_slugs(author):
    assert create_page(author, "Safety")["slug"] == "safety"
    assert create_page(author, "Safety")["slug"] == "safety-2"


def test_a_page_and_a_guide_may_share_a_slug(author, category):
    """They live at different URLs, so one must not push the other to ``-2``."""
    from .conftest import create_guide

    guide = create_guide(author, category.id, "Light Microscopy")
    page = create_page(author, "Light Microscopy")

    assert guide["slug"] == page["slug"] == "light-microscopy"


def test_a_page_resolves_by_id_and_by_slug(author):
    created = create_page(author)

    assert author.get(f"/api/pages/{created['id']}").json() == created
    assert author.get(f"/api/pages/{created['slug']}").json() == created


def test_an_unknown_page_is_not_found(author):
    response = author.get("/api/pages/no-such-page")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# ---------------------------------------------------------------------- save


def test_put_saves_the_whole_page(author, category):
    created = create_page(author)
    hero = upload_media(author)

    saved = save_page(
        author,
        created,
        title="Booking Rules",
        summary="How instrument time is shared.",
        body="## Booking\n\n1. Two weeks ahead.\n",
        categoryId=category.id,
        heroMediaId=hero["id"],
    )

    assert saved["title"] == "Booking Rules"
    assert saved["summary"] == "How instrument time is shared."
    assert saved["body"] == "## Booking\n\n1. Two weeks ahead.\n"
    assert saved["categoryId"] == category.id
    assert saved["heroMediaId"] == hero["id"]
    assert instant(saved["updatedAt"]) > instant(created["updatedAt"])
    assert saved["createdAt"] == created["createdAt"]
    assert author.get(f"/api/pages/{created['id']}").json() == saved


def test_the_body_is_stored_and_returned_verbatim(author):
    """The server does not interpret Markdown. Raw HTML, a guide-list block and
    odd whitespace all come back exactly as typed; neutralising the HTML is the
    renderer's job and it does it by never emitting HTML at all."""
    created = create_page(author)
    body = (
        "<script>alert(1)</script>\n\n"
        "```guidelist\ntags: stellaris, confocal\nheading: Start here\n```\n\n"
        "  trailing spaces  \n\ttab\n"
    )

    assert save_page(author, created, body=body)["body"] == body


def test_server_owned_fields_are_ignored_on_save(author):
    created = create_page(author)

    saved = save_page(author, created, status="published", slug="hijacked", version=9, viewCount=500)

    assert (saved["status"], saved["slug"], saved["version"], saved["viewCount"]) == ("draft", created["slug"], 0, 0)


def test_a_stale_save_conflicts_and_changes_nothing(author, as_role):
    created = create_page(author)
    colleague = as_role("author", "colleague@zmb.uzh.ch")
    save_page(colleague, created, body="The colleague's text.")

    response = author.put(f"/api/pages/{created['id']}", json=document_from(created, body="Mine."))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert "page" in response.json()["error"]["message"]
    assert author.get(f"/api/pages/{created['id']}").json()["body"] == "The colleague's text."


def test_a_save_without_the_concurrency_token_is_rejected(author):
    created = create_page(author)
    body = document_from(created)
    del body["expectedUpdatedAt"]

    response = author.put(f"/api/pages/{created['id']}", json=body)

    assert response.status_code == 422
    assert "expectedUpdatedAt" in response.json()["error"]["message"]


def test_consecutive_autosaves_chain(author):
    page = create_page(author)
    for index in range(4):
        page = save_page(author, page, body=f"Revision {index}")

    assert page["body"] == "Revision 3"


def test_the_body_is_capped_at_two_hundred_thousand_characters(author):
    created = create_page(author)

    at_the_limit = save_page(author, created, body="é" * 200_000)
    assert len(at_the_limit["body"]) == 200_000

    response = author.put(f"/api/pages/{created['id']}", json=document_from(at_the_limit, body="x" * 200_001))
    assert response.status_code == 422


def test_contributors_accumulate_and_the_last_editor_is_recorded(author, as_role):
    created = create_page(author)
    colleague = as_role("author", "colleague@zmb.uzh.ch", display_name="Colleague Editor")

    saved = save_page(colleague, created, body="Edited.")
    saved = save_page(colleague, saved, body="Edited again.")

    assert [c["displayName"] for c in saved["contributors"]] == ["Author", "Colleague Editor"]
    assert saved["lastEditedBy"]["displayName"] == "Colleague Editor"
    assert saved["author"]["displayName"] == "Author"


def test_viewers_cannot_save_a_page(author, viewer):
    created = create_page(author)

    assert viewer.put(f"/api/pages/{created['id']}", json=document_from(created, body="x")).status_code == 403


def test_saving_an_unknown_page_is_not_found(author):
    created = create_page(author)

    assert author.put(f"/api/pages/{ULID()}", json=document_from(created)).status_code == 404


def test_moving_a_page_to_an_unknown_category_is_rejected(author):
    created = create_page(author)

    response = author.put(f"/api/pages/{created['id']}", json=document_from(created, categoryId=str(ULID())))

    assert response.status_code == 422


# ---------------------------------------------------------------------- hero


def test_the_hero_must_be_an_existing_image(author):
    created = create_page(author)
    clip = upload_video(author)

    missing = author.put(f"/api/pages/{created['id']}", json=document_from(created, heroMediaId=str(ULID())))
    video = author.put(f"/api/pages/{created['id']}", json=document_from(created, heroMediaId=clip["id"]))

    assert missing.status_code == 422
    assert video.status_code == 422
    assert "image" in video.json()["error"]["message"]
    assert author.get(f"/api/pages/{created['id']}").json()["heroMediaId"] is None


def test_the_hero_can_be_cleared(author):
    created = create_page(author)
    saved = save_page(author, created, heroMediaId=upload_media(author)["id"])

    assert save_page(author, saved, heroMediaId=None)["heroMediaId"] is None


# ------------------------------------------------------------- landing pages


def test_a_landing_page_needs_a_category(author):
    response = author.post("/api/pages", json={"title": "Homeless", "isLanding": True})

    assert response.status_code == 422
    assert "category" in response.json()["error"]["message"]

    standalone = create_page(author)
    promoted = author.put(f"/api/pages/{standalone['id']}", json=document_from(standalone, isLanding=True))
    assert promoted.status_code == 422


def test_a_category_has_at_most_one_landing_page(author, category):
    first = create_page(author, "Light Microscopy", categoryId=category.id, isLanding=True)

    second = author.post("/api/pages", json={"title": "Another", "categoryId": category.id, "isLanding": True})

    assert first["isLanding"] is True
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "conflict"


def test_an_ordinary_page_cannot_be_promoted_into_a_taken_slot(author, category):
    create_page(author, "Landing", categoryId=category.id, isLanding=True)
    ordinary = create_page(author, "Ordinary", categoryId=category.id)

    response = author.put(f"/api/pages/{ordinary['id']}", json=document_from(ordinary, isLanding=True))

    assert response.status_code == 409
    assert author.get(f"/api/pages/{ordinary['id']}").json()["isLanding"] is False


def test_a_landing_page_can_be_saved_again_without_colliding_with_itself(author, category):
    landing = create_page(author, "Landing", categoryId=category.id, isLanding=True)

    assert save_page(author, landing, body="Still the landing page.")["isLanding"] is True


def test_two_categories_each_have_their_own_landing_page(author, admin, category):
    other = admin.post("/api/categories", json={"name": "Electron Microscopy"}).json()

    create_page(author, "LM", categoryId=category.id, isLanding=True)
    assert create_page(author, "EM", categoryId=other["id"], isLanding=True)["isLanding"] is True


def test_any_number_of_ordinary_pages_share_a_category(author, category):
    create_page(author, "Landing", categoryId=category.id, isLanding=True)

    assert create_page(author, "One", categoryId=category.id)["categoryId"] == category.id
    assert create_page(author, "Two", categoryId=category.id)["categoryId"] == category.id


def test_archiving_the_landing_page_frees_the_slot(author, admin, category):
    old = create_page(author, "Old landing", categoryId=category.id, isLanding=True)
    assert admin.delete(f"/api/pages/{old['id']}").status_code == 204

    replacement = create_page(author, "New landing", categoryId=category.id, isLanding=True)

    assert replacement["isLanding"] is True


def test_the_database_itself_refuses_a_second_landing_page(author, category, db_session):
    """The router's check can be passed by two requests at once; the partial
    unique index is what holds then, so it has to exist and has to exempt
    archived and ordinary pages."""
    landing = create_page(author, "Landing", categoryId=category.id, isLanding=True)
    author_id = landing["author"]["id"]

    def page(slug: str, **fields) -> Page:
        return Page(slug=slug, title=slug, category_id=category.id, author_id=author_id, last_edited_by_id=author_id, **fields)

    db_session.add_all([page("ordinary"), page("archived-landing", is_landing=True, status="archived")])
    db_session.commit()

    db_session.add(page("rival-landing", is_landing=True))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_losing_the_race_for_a_landing_slot_is_a_conflict_not_a_crash(author, category, monkeypatch):
    """Simulate both requests passing the check: with the check disabled, the
    index's verdict has to come back as the ordinary 409."""
    from app import pages as page_rules

    create_page(author, "Landing", categoryId=category.id, isLanding=True)
    ordinary = create_page(author, "Ordinary", categoryId=category.id)
    monkeypatch.setattr(page_rules, "assert_landing_slot_free", lambda *args, **kwargs: None)

    created = author.post("/api/pages", json={"title": "Rival", "categoryId": category.id, "isLanding": True})
    promoted = author.put(f"/api/pages/{ordinary['id']}", json=document_from(ordinary, isLanding=True))

    assert created.status_code == 409
    assert promoted.status_code == 409
    assert promoted.json()["error"]["code"] == "conflict"


def test_an_unrelated_integrity_error_is_not_dressed_up_as_a_landing_conflict(db_session):
    from app.routers.pages import landing_race_is_a_conflict

    with pytest.raises(IntegrityError):
        with landing_race_is_a_conflict(db_session):
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed: pages.slug"))


# ----------------------------------------------------------- media references


def test_media_referenced_in_the_body_is_recorded_on_save(author, db_session):
    first, second = upload_media(author), upload_media(author)
    clip = upload_video(author)
    created = create_page(author)
    body = (
        f"![One](/api/media/{first['id']})\n\n"
        f"| a | b |\n| - | - |\n| ![Two](/api/media/{second['id']} \"title\") | x |\n\n"
        f"[Watch the clip](/api/media/{clip['id']})\n\n"
        f"Again: ![One](/api/media/{first['id']})\n"
    )

    save_page(author, created, body=body)

    recorded = set(db_session.scalars(select(PageMedia.media_id).where(PageMedia.page_id == created["id"])))
    assert recorded == {first["id"], second["id"], clip["id"]}


def test_references_are_replaced_not_accumulated(author, db_session):
    first, second = upload_media(author), upload_media(author)
    created = create_page(author)
    saved = save_page(author, created, body=f"![x](/api/media/{first['id']})")

    save_page(author, saved, body=f"![y](/api/media/{second['id']})")

    assert db_session.scalars(select(PageMedia.media_id)).all() == [second["id"]]


def test_references_to_media_that_does_not_exist_are_ignored(author, db_session):
    """The body is prose; a half-pasted link must not fail the save."""
    created = create_page(author)
    body = (
        f"![ghost](/api/media/{ULID()})\n"
        "![short](/api/media/01ABC)\n"
        "![not-a-ulid](/api/media/ILOU0000000000000000000000)\n"
        f"![too-long](/api/media/{ULID()}EXTRA)\n"
        "![elsewhere](https://example.org/api/mediaX/whatever)\n"
    )

    saved = save_page(author, created, body=body)

    assert saved["body"] == body
    assert db_session.scalars(select(PageMedia)).all() == []


# ---------------------------------------------------------------- visibility


def test_viewers_see_only_published_pages(author, viewer):
    draft = create_page(author, "Draft")
    live = published_page(author, "Live")

    assert [p["id"] for p in viewer.get("/api/pages").json()] == [live["id"]]
    assert viewer.get(f"/api/pages/{live['slug']}").status_code == 200
    assert viewer.get(f"/api/pages/{draft['slug']}").status_code == 404
    assert viewer.get(f"/api/pages/{draft['id']}").json()["error"]["code"] == "not_found"
    assert viewer.get("/api/pages", params={"status": "draft"}).json() == []


def test_authors_see_drafts_and_nobody_sees_the_archive(author, admin, viewer):
    draft = create_page(author, "Draft")
    gone = published_page(author, "Gone")
    assert admin.delete(f"/api/pages/{gone['id']}").status_code == 204

    for client in (author, admin):
        assert [p["id"] for p in client.get("/api/pages").json()] == [draft["id"]]
        assert client.get("/api/pages", params={"status": "archived"}).json() == []
        assert client.get(f"/api/pages/{gone['slug']}").status_code == 404
    assert viewer.get("/api/pages").json() == []
    assert author.put(f"/api/pages/{gone['id']}", json=document_from(gone)).status_code == 404
    assert author.post(f"/api/pages/{gone['id']}/publish").status_code == 404
    assert admin.delete(f"/api/pages/{gone['id']}").status_code == 404


def test_only_an_admin_archives_a_page(author, admin, db_session):
    created = published_page(author)

    assert author.delete(f"/api/pages/{created['id']}").status_code == 403
    assert admin.delete(f"/api/pages/{created['id']}").status_code == 204
    assert db_session.get(Page, created["id"]).body == "Some content."


# ------------------------------------------------------------------- listing


def test_the_listing_is_a_summary_sorted_by_title(author, category):
    create_page(author, "zebrafish mounting")
    create_page(author, "Booking")
    create_page(author, "alignment", categoryId=category.id)

    listing = author.get("/api/pages").json()

    assert [p["title"] for p in listing] == ["alignment", "Booking", "zebrafish mounting"]
    assert set(listing[0]) == SUMMARY_FIELDS
    assert "body" not in listing[0]


def test_the_listing_filters_by_category_status_and_text(author, category):
    filed = create_page(author, "Objectives", categoryId=category.id)
    live = published_page(author, "Booking Rules", summary="Fair use of instrument time.")

    assert [p["id"] for p in author.get("/api/pages", params={"categoryId": category.id}).json()] == [filed["id"]]
    assert [p["id"] for p in author.get("/api/pages", params={"status": "published"}).json()] == [live["id"]]
    assert [p["id"] for p in author.get("/api/pages", params={"q": "BOOKING"}).json()] == [live["id"]]
    assert [p["id"] for p in author.get("/api/pages", params={"q": "fair use"}).json()] == [live["id"]]
    assert author.get("/api/pages", params={"q": "   "}).json().__len__() == 2
    assert author.get("/api/pages", params={"status": "nonsense"}).status_code == 422


# ------------------------------------------------------- publish and history


def test_publishing_needs_a_title_and_a_body(author):
    empty = create_page(author, "No content yet")
    untitled = create_page(author, "Will lose its title")
    save_page(author, untitled, title="", body="Content without a title.")

    no_body = author.post(f"/api/pages/{empty['id']}/publish")
    no_title = author.post(f"/api/pages/{untitled['id']}/publish")

    assert no_body.status_code == 422
    assert "content" in no_body.json()["error"]["message"]
    assert no_title.status_code == 422
    assert "title" in no_title.json()["error"]["message"]
    assert author.get(f"/api/pages/{empty['id']}").json()["status"] == "draft"


def test_a_whitespace_body_is_not_content(author):
    created = create_page(author)
    save_page(author, created, body="  \n\n\t")

    assert author.post(f"/api/pages/{created['id']}/publish").status_code == 422


def test_publishing_versions_the_page_and_writes_a_snapshot(author):
    created = create_page(author, "Booking Rules")
    saved = save_page(author, created, body="Version one.")

    first = author.post(f"/api/pages/{created['id']}/publish").json()
    assert (first["status"], first["version"]) == ("published", 1)
    assert first["publishedAt"] is not None
    assert instant(first["updatedAt"]) > instant(saved["updatedAt"])

    save_page(author, first, body="Version two.")
    second = author.post(f"/api/pages/{created['id']}/publish").json()

    revisions = author.get(f"/api/pages/{created['id']}/revisions").json()
    assert second["version"] == 2
    assert [r["version"] for r in revisions] == [2, 1]
    assert set(revisions[0]) == {"version", "publishedAt", "publishedBy"}
    assert revisions[0]["publishedBy"]["displayName"] == "Author"

    snapshot = author.get(f"/api/pages/{created['id']}/revisions/1").json()
    assert set(snapshot) == PAGE_FIELDS
    assert snapshot["body"] == "Version one."
    assert author.get(f"/api/pages/{created['id']}/revisions/2").json()["body"] == "Version two."
    assert author.get(f"/api/pages/{created['id']}/revisions/3").status_code == 404


def test_unpublishing_returns_a_page_to_draft_and_keeps_its_history(author, viewer):
    created = published_page(author)

    response = author.post(f"/api/pages/{created['id']}/unpublish")

    assert response.status_code == 200
    assert (response.json()["status"], response.json()["version"]) == ("draft", 1)
    assert viewer.get(f"/api/pages/{created['slug']}").status_code == 404
    assert len(author.get(f"/api/pages/{created['id']}/revisions").json()) == 1
    assert author.post(f"/api/pages/{created['id']}/unpublish").status_code == 409


def test_viewers_cannot_publish_or_read_history(author, viewer):
    created = published_page(author)

    assert viewer.post(f"/api/pages/{created['id']}/publish").status_code == 403
    assert viewer.post(f"/api/pages/{created['id']}/unpublish").status_code == 403
    assert viewer.get(f"/api/pages/{created['id']}/revisions").status_code == 403
    assert viewer.get(f"/api/pages/{created['id']}/revisions/1").status_code == 403


def test_recording_a_view_of_a_page(author, viewer):
    created = published_page(author)
    draft = create_page(author, "Draft")

    assert viewer.post(f"/api/pages/{created['id']}/view").status_code == 204
    assert viewer.post(f"/api/pages/{created['id']}/view").status_code == 204
    assert viewer.post(f"/api/pages/{draft['id']}/view").status_code == 404

    after = author.get(f"/api/pages/{created['id']}").json()
    assert after["viewCount"] == 2
    assert after["updatedAt"] == created["updatedAt"]


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/pages"),
        ("GET", "/api/pages/anything"),
        ("POST", "/api/pages"),
        ("PUT", "/api/pages/anything"),
        ("POST", "/api/pages/anything/publish"),
        ("POST", "/api/pages/anything/unpublish"),
        ("POST", "/api/pages/anything/view"),
        ("DELETE", "/api/pages/anything"),
        ("GET", "/api/pages/anything/revisions"),
        ("GET", "/api/pages/anything/revisions/1"),
    ],
)
def test_page_endpoints_require_a_session(anon, method, path):
    anon.raw.cookies.set("reticle_csrf", "x")

    assert anon.raw.request(method, path, json={}, headers={"X-CSRF-Token": "x"}).status_code == 401
