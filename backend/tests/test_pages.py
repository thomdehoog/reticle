"""Wiki pages: the other half of what the institute actually publishes.

Navigation on the live site does not run on the category tree. Category pages
are wiki pages whose body embeds tag-filtered guide lists, and the guides
themselves sit in hidden holding categories. So a page is not a secondary
feature that can afford to be looser than a guide: it carries the same drafts,
the same optimistic-concurrency token and the same reader visibility, and each
of those failing here has the same consequence it has for a guide — a
half-written procedure served to the institute, or one editor's work silently
overwritten by another's stale copy.

The landing rules are their own class of failure. Two landing pages for one
category means the category page a reader gets depends on row order, and a
landing that belongs to no category is a page nothing can ever navigate to.
"""

from __future__ import annotations

from ulid import ULID

from .conftest import TEST_PASSWORD, create_page, instant, page_document_from, upload_media


def published_page(client, title: str = "Immersion Oil", **kwargs) -> dict:
    page = create_page(client, title, **kwargs)
    response = client.post(f"/api/pages/{page['id']}/publish")
    assert response.status_code == 200, response.text
    return response.json()


def test_author_creates_a_draft_page_with_sane_defaults(author, category):
    body = create_page(author, "Immersion Oil", category_id=category.id)

    assert body["status"] == "draft"
    assert body["version"] == 0
    assert body["slug"] == "immersion-oil"
    assert body["body"] == ""
    assert body["summary"] == ""
    assert body["isLanding"] is False
    assert body["heroMediaId"] is None
    assert body["viewCount"] == 0
    assert body["publishedAt"] is None
    assert body["categoryId"] == category.id
    assert body["author"] == {"id": body["lastEditedBy"]["id"], "displayName": "Author"}
    assert body["contributors"] == [body["author"]]
    assert body["createdAt"].endswith("Z")


def test_page_response_matches_the_domain_model_exactly(author, category):
    body = create_page(author, category_id=category.id)

    assert set(body) == {
        "id",
        "slug",
        "title",
        "summary",
        "categoryId",
        "isLanding",
        "tags",
        "body",
        "heroMediaId",
        "status",
        "author",
        "lastEditedBy",
        "contributors",
        "viewCount",
        "createdAt",
        "updatedAt",
        "publishedAt",
        "version",
    }


def test_page_summary_projection_matches_the_domain_model(author, category):
    create_page(author, category_id=category.id)

    entry = author.get("/api/pages").json()[0]

    assert set(entry) == {
        "id",
        "slug",
        "title",
        "summary",
        "categoryId",
        "isLanding",
        "tags",
        "status",
        "heroImageUrl",
        "updatedAt",
        "publishedAt",
    }


def test_a_standalone_page_needs_no_category(author):
    body = create_page(author, "Booking and Access")

    assert body["categoryId"] is None
    assert body["isLanding"] is False


def test_creating_a_page_in_an_unknown_category_is_rejected(author):
    response = author.post(
        "/api/pages",
        json={"title": "Orphan", "categoryId": "01JQNOTAREALULID00000000"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_blank_page_title_is_rejected(author):
    assert author.post("/api/pages", json={"title": "   "}).status_code == 422


def test_duplicate_page_titles_get_distinct_slugs(author):
    first = create_page(author, "Immersion Oil")
    second = create_page(author, "Immersion Oil")

    assert first["slug"] == "immersion-oil"
    assert second["slug"] == "immersion-oil-2"


def test_a_page_resolves_by_id_and_by_slug(author, category):
    created = create_page(author, category_id=category.id)

    by_id = author.get(f"/api/pages/{created['id']}").json()
    by_slug = author.get(f"/api/pages/{created['slug']}").json()

    assert by_id == by_slug == created


def test_an_unknown_page_is_not_found(author):
    response = author.get("/api/pages/no-such-page")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_the_whole_document_saves_in_one_put(author, category):
    created = create_page(author, category_id=category.id)

    body = author.put(
        f"/api/pages/{created['id']}",
        json=page_document_from(
            created,
            title="Immersion Media",
            summary="Which oil goes on which objective.",
            body="## Oils\n\nUse the medium printed on the objective.",
        ),
    ).json()

    assert body["title"] == "Immersion Media"
    assert body["summary"] == "Which oil goes on which objective."
    assert body["body"].startswith("## Oils")
    assert instant(body["updatedAt"]) > instant(created["updatedAt"])


def test_a_page_can_be_moved_between_categories_and_out_of_them(author, admin, category):
    other = admin.post("/api/categories", json={"name": "Electron Microscopy"}).json()
    created = create_page(author, category_id=category.id)

    moved = author.put(
        f"/api/pages/{created['id']}", json=page_document_from(created, categoryId=other["id"])
    ).json()
    detached = author.put(
        f"/api/pages/{created['id']}", json=page_document_from(moved, categoryId=None)
    ).json()

    assert moved["categoryId"] == other["id"]
    assert detached["categoryId"] is None


def test_moving_a_page_to_an_unknown_category_is_rejected(author, category):
    created = create_page(author, category_id=category.id)

    response = author.put(
        f"/api/pages/{created['id']}",
        json=page_document_from(created, categoryId=str(ULID())),
    )

    assert response.status_code == 422


def test_a_hero_image_is_saved_through_the_document(author, category):
    created = create_page(author, category_id=category.id)
    image = upload_media(author)

    body = author.put(
        f"/api/pages/{created['id']}",
        json=page_document_from(created, heroMediaId=image["id"]),
    ).json()

    assert body["heroMediaId"] == image["id"]


def test_a_hero_image_that_no_longer_exists_is_rejected(author, category):
    created = create_page(author, category_id=category.id)

    response = author.put(
        f"/api/pages/{created['id']}",
        json=page_document_from(created, heroMediaId=str(ULID())),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_hero_image_id_that_is_not_an_identifier_is_rejected(author, category):
    created = create_page(author, category_id=category.id)

    response = author.put(
        f"/api/pages/{created['id']}",
        json=page_document_from(created, heroMediaId="../../etc/passwd"),
    )

    assert response.status_code == 422


def test_status_slug_and_version_are_not_writable_through_the_document(author, category):
    created = create_page(author, category_id=category.id)

    saved = author.put(
        f"/api/pages/{created['id']}",
        json=page_document_from(created, status="published", slug="hijacked", version=99),
    ).json()

    assert saved["status"] == "draft"
    assert saved["slug"] == created["slug"]
    assert saved["version"] == 0


def test_a_missing_updated_at_is_rejected_rather_than_assumed_current(author, category):
    created = create_page(author, category_id=category.id)
    body = page_document_from(created)
    del body["updatedAt"]

    response = author.put(f"/api/pages/{created['id']}", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_stale_updated_at_conflicts_and_changes_nothing(author, as_role, category):
    created = create_page(author, category_id=category.id)
    colleague = as_role("author", "colleague@zmb.uzh.ch")

    fresh = author.get(f"/api/pages/{created['id']}").json()
    colleague.put(
        f"/api/pages/{created['id']}", json=page_document_from(fresh, title="Colleague's title")
    )

    response = author.put(
        f"/api/pages/{created['id']}", json=page_document_from(fresh, title="My title")
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert "page" in response.json()["error"]["message"].lower()
    assert author.get(f"/api/pages/{created['id']}").json()["title"] == "Colleague's title"


def test_consecutive_autosaves_chain_without_conflicting(author, category):
    document = create_page(author, category_id=category.id)

    for index in range(4):
        response = author.put(
            f"/api/pages/{document['id']}",
            json=page_document_from(document, body=f"Revision {index}"),
        )
        assert response.status_code == 200, response.text
        document = response.json()

    assert document["body"] == "Revision 3"


def test_saving_an_unknown_page_is_not_found(author, category):
    created = create_page(author, category_id=category.id)

    assert author.put(f"/api/pages/{ULID()}", json=page_document_from(created)).status_code == 404


def test_publishing_increments_the_version_and_stamps_the_time(author, category):
    created = create_page(author, category_id=category.id)

    body = author.post(f"/api/pages/{created['id']}/publish").json()

    assert body["status"] == "published"
    assert body["version"] == 1
    assert body["publishedAt"] is not None and body["publishedAt"].endswith("Z")


def test_publishing_writes_an_immutable_snapshot(author, category):
    created = create_page(author, category_id=category.id)
    author.put(
        f"/api/pages/{created['id']}", json=page_document_from(created, body="Original body")
    )
    author.post(f"/api/pages/{created['id']}/publish")

    reloaded = author.get(f"/api/pages/{created['id']}").json()
    author.put(f"/api/pages/{created['id']}", json=page_document_from(reloaded, body="Rewritten"))

    snapshot = author.get(f"/api/pages/{created['id']}/revisions/1").json()

    assert snapshot["version"] == 1
    assert snapshot["body"] == "Original body"


def test_republishing_adds_a_second_revision(author, category):
    created = create_page(author, category_id=category.id)
    author.post(f"/api/pages/{created['id']}/publish")
    reloaded = author.get(f"/api/pages/{created['id']}").json()
    author.put(f"/api/pages/{created['id']}", json=page_document_from(reloaded, title="Renamed"))
    second = author.post(f"/api/pages/{created['id']}/publish").json()

    revisions = author.get(f"/api/pages/{created['id']}/revisions").json()

    assert second["version"] == 2
    assert [r["version"] for r in revisions] == [2, 1]
    assert set(revisions[0]) == {"version", "publishedAt", "publishedBy"}
    assert revisions[0]["publishedBy"]["displayName"] == "Author"
    assert author.get(f"/api/pages/{created['id']}/revisions/2").json()["title"] == "Renamed"


def test_an_unknown_page_revision_is_not_found(author, category):
    created = create_page(author, category_id=category.id)

    assert author.get(f"/api/pages/{created['id']}/revisions/7").status_code == 404


def test_revisions_of_an_unknown_page_are_not_found(author):
    assert author.get(f"/api/pages/{ULID()}/revisions").status_code == 404
    assert author.get(f"/api/pages/{ULID()}/revisions/1").status_code == 404


def test_viewers_may_not_read_publish_history(author, viewer, category):
    created = published_page(author, category_id=category.id)

    assert viewer.get(f"/api/pages/{created['id']}/revisions").status_code == 403
    assert viewer.get(f"/api/pages/{created['id']}/revisions/1").status_code == 403


def test_unpublishing_hides_the_page_again(author, viewer, category):
    created = published_page(author, category_id=category.id)

    response = author.post(f"/api/pages/{created['id']}/unpublish")

    assert response.status_code == 200
    assert response.json()["status"] == "draft"
    assert response.json()["version"] == 1
    assert viewer.get("/api/pages").json() == []
    assert viewer.get(f"/api/pages/{created['slug']}").status_code == 404


def test_unpublishing_a_draft_conflicts(author, category):
    created = create_page(author, category_id=category.id)

    response = author.post(f"/api/pages/{created['id']}/unpublish")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_publishing_an_archived_page_conflicts(author, admin, category):
    created = create_page(author, category_id=category.id)
    admin.delete(f"/api/pages/{created['id']}")

    assert author.post(f"/api/pages/{created['id']}/publish").status_code == 409


def test_only_an_admin_archives_a_page(author, admin, viewer, category):
    created = create_page(author, category_id=category.id)

    assert viewer.delete(f"/api/pages/{created['id']}").status_code == 403
    assert author.delete(f"/api/pages/{created['id']}").status_code == 403
    assert admin.delete(f"/api/pages/{created['id']}").status_code == 204
    assert author.get("/api/pages").json() == []


def test_archiving_twice_is_harmless(admin, author, category):
    created = create_page(author, category_id=category.id)

    assert admin.delete(f"/api/pages/{created['id']}").status_code == 204
    assert admin.delete(f"/api/pages/{created['id']}").status_code == 204


def test_archiving_an_unknown_page_is_not_found(admin):
    assert admin.delete(f"/api/pages/{ULID()}").status_code == 404


def test_archived_pages_are_excluded_unless_asked_for(author, admin, category):
    created = create_page(author, category_id=category.id)
    admin.delete(f"/api/pages/{created['id']}")

    assert author.get("/api/pages").json() == []
    assert [p["id"] for p in author.get("/api/pages", params={"status": "archived"}).json()] == [
        created["id"]
    ]


def test_a_viewer_gets_not_found_rather_than_forbidden_for_a_draft(author, viewer, category):
    """Telling a reader the page exists but is off-limits leaks the editorial
    pipeline for no benefit."""
    created = create_page(author, "Unfinished Page", category_id=category.id)

    response = viewer.get(f"/api/pages/{created['slug']}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_viewers_never_receive_drafts_in_a_listing(author, viewer, category):
    create_page(author, "Unfinished Page", category_id=category.id)

    assert viewer.get("/api/pages").json() == []
    assert viewer.get("/api/pages", params={"status": "draft"}).json() == []


def test_a_published_page_becomes_visible_to_viewers(author, viewer, category):
    created = published_page(author, "Public Page", category_id=category.id)

    assert [p["title"] for p in viewer.get("/api/pages").json()] == ["Public Page"]
    assert viewer.get(f"/api/pages/{created['slug']}").json()["version"] == 1


def test_viewers_cannot_create_save_or_publish_a_page(author, viewer, category):
    created = create_page(author, category_id=category.id)

    assert viewer.post("/api/pages", json={"title": "Nope"}).status_code == 403
    assert (
        viewer.put(f"/api/pages/{created['id']}", json=page_document_from(created)).status_code
        == 403
    )
    assert viewer.post(f"/api/pages/{created['id']}/publish").status_code == 403
    assert viewer.post(f"/api/pages/{created['id']}/unpublish").status_code == 403


def test_the_listing_filters_by_category_and_free_text(author, admin, category):
    other = admin.post("/api/categories", json={"name": "Electron Microscopy"}).json()
    here = create_page(author, "Immersion Oil", category_id=category.id)
    create_page(author, "Cryo Sectioning", category_id=other["id"])
    author.put(
        f"/api/pages/{here['id']}",
        json=page_document_from(
            here, summary="Oils and their objectives.", body="Never mix the media."
        ),
    )

    assert [
        p["title"] for p in author.get("/api/pages", params={"categoryId": other["id"]}).json()
    ] == ["Cryo Sectioning"]
    assert [p["title"] for p in author.get("/api/pages", params={"q": "objectives"}).json()] == [
        "Immersion Oil"
    ]
    assert [p["title"] for p in author.get("/api/pages", params={"q": "never mix"}).json()] == [
        "Immersion Oil"
    ]


def test_a_landing_page_belongs_to_exactly_one_category(author, category):
    landing = create_page(author, "Light Microscopy", category_id=category.id, is_landing=True)

    response = author.post(
        "/api/pages",
        json={"title": "Second Landing", "categoryId": category.id, "isLanding": True},
    )

    assert landing["isLanding"] is True
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_a_second_landing_cannot_be_promoted_through_a_save_either(author, category):
    """The create path and the save path are two doors into the same rule, and
    the one nobody checks is the one that gets used."""
    create_page(author, "Light Microscopy", category_id=category.id, is_landing=True)
    other = create_page(author, "Immersion Oil", category_id=category.id)

    response = author.put(
        f"/api/pages/{other['id']}", json=page_document_from(other, isLanding=True)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_a_landing_page_can_be_saved_without_conflicting_with_itself(author, category):
    landing = create_page(author, "Light Microscopy", category_id=category.id, is_landing=True)

    saved = author.put(
        f"/api/pages/{landing['id']}", json=page_document_from(landing, body="Updated")
    )

    assert saved.status_code == 200
    assert saved.json()["isLanding"] is True


def test_a_landing_page_without_a_category_is_refused(author):
    """A landing that belongs to nothing is a page nothing can navigate to."""
    response = author.post("/api/pages", json={"title": "Nowhere", "isLanding": True})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_landing_page_cannot_have_its_category_removed_by_a_save(author, category):
    landing = create_page(author, "Light Microscopy", category_id=category.id, is_landing=True)

    response = author.put(
        f"/api/pages/{landing['id']}",
        json=page_document_from(landing, categoryId=None),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_two_categories_may_each_have_their_own_landing(author, admin, category):
    other = admin.post("/api/categories", json={"name": "Electron Microscopy"}).json()

    first = create_page(author, "Light Microscopy", category_id=category.id, is_landing=True)
    second = create_page(author, "Electron Microscopy", category_id=other["id"], is_landing=True)

    assert (first["isLanding"], second["isLanding"]) == (True, True)


def test_a_category_with_no_landing_page_yields_null_rather_than_an_error(author, category):
    """A fresh install has no landing pages at all; treating that as an error
    would put a red alert on every category page until somebody wrote one."""
    response = author.get(f"/api/categories/{category.id}/page")

    assert response.status_code == 200
    assert response.json() is None


def test_the_category_landing_endpoint_returns_the_landing_page(author, category):
    landing = create_page(author, "Light Microscopy", category_id=category.id, is_landing=True)

    body = author.get(f"/api/categories/{category.id}/page").json()

    assert body["id"] == landing["id"]
    assert body["isLanding"] is True


def test_the_category_landing_endpoint_ignores_ordinary_pages(author, category):
    create_page(author, "Immersion Oil", category_id=category.id)

    assert author.get(f"/api/categories/{category.id}/page").json() is None


def test_a_viewer_sees_no_landing_page_until_it_is_published(author, viewer, category):
    landing = create_page(author, "Light Microscopy", category_id=category.id, is_landing=True)

    assert viewer.get(f"/api/categories/{category.id}/page").json() is None

    author.post(f"/api/pages/{landing['id']}/publish")

    assert viewer.get(f"/api/categories/{category.id}/page").json()["id"] == landing["id"]


def test_an_archived_landing_page_stops_being_the_category_page(author, admin, category):
    landing = published_page(author, "Light Microscopy", category_id=category.id, is_landing=True)

    admin.delete(f"/api/pages/{landing['id']}")

    assert admin.get(f"/api/categories/{category.id}/page").json() is None


def test_the_landing_endpoint_of_an_unknown_category_is_not_found(author):
    assert author.get(f"/api/categories/{ULID()}/page").status_code == 404


def test_deleting_a_category_takes_its_wiki_pages_with_it(admin, author, category):
    """A page left behind would point at a category that no longer exists, which
    is a landing nothing renders and nothing can find.

    That used to be prevented by refusing the deletion. It is prevented by
    carrying out the whole of it instead: the section, its sub-sections, its
    guides and its pages. The administrator's password is what guards it.
    """
    page = create_page(author, "Immersion Oil", category_id=category.id)

    response = admin.delete(f"/api/categories/{category.id}", json={"password": TEST_PASSWORD})

    assert response.status_code == 204
    assert admin.get(f"/api/pages/{page['id']}").status_code == 404


def test_pages_read_without_a_session_and_are_not_writable_without_one(anon):
    """Wiki pages are the section front pages, so they are as public as a guide.

    Writing one is not: the POST is refused before it reaches the route, by the
    CSRF middleware, which is why this is 403 rather than 401.
    """
    assert anon.get("/api/pages").status_code == 200
    assert anon.get("/api/pages/anything").status_code == 404
    assert anon.post("/api/pages", json={"title": "Nope"}).status_code == 403


def test_an_unknown_page_status_is_refused_rather_than_answered_with_nothing(author):
    """The page listing takes the same three words the guide listing takes.

    Same reasoning as the guide test of the same name: a filter that silently
    matches nothing reports an empty library, and a caller acts on that.
    """
    for wrong in ("", "publshed", "PUBLISHED"):
        assert author.get("/api/pages", params={"status": wrong}).status_code == 422, wrong

    assert author.get("/api/pages", params={"status": "draft"}).status_code == 200


def test_a_page_carries_tags_the_way_a_guide_does(author, category):
    """A group on a section's page is rows pointing at an endpoint, and the
    endpoint is a guide or a wiki. Until a page could be tagged, every wiki in a
    section landed in one lump because there was nothing to group it by."""
    created = create_page(author, "Immersion Oil", category_id=category.id)

    saved = author.put(
        f"/api/pages/{created['id']}",
        json=page_document_from(created, tags=["thunder", "widefield"]),
    ).json()

    assert saved["tags"] == ["thunder", "widefield"]
    assert author.get(f"/api/pages/{created['id']}").json()["tags"] == ["thunder", "widefield"]


def test_a_page_tag_reaches_the_listing_a_section_is_built_from(author, category):
    created = create_page(author, "Immersion Oil", category_id=category.id)
    author.put(f"/api/pages/{created['id']}", json=page_document_from(created, tags=["thunder"]))

    entry = next(p for p in author.get("/api/pages").json() if p["id"] == created["id"])

    assert entry["tags"] == ["thunder"]


def test_a_tag_an_author_invents_on_a_page_is_minted(author, category):
    """The same rule as a guide's: an author is not the administrator of a
    taxonomy, and making them create a tag first is how a corpus ends up with
    none."""
    created = create_page(author, "Immersion Oil", category_id=category.id)

    saved = author.put(
        f"/api/pages/{created['id']}", json=page_document_from(created, tags=["brand-new-tag"])
    ).json()

    assert saved["tags"] == ["brand-new-tag"]
    assert "brand-new-tag" in {tag["slug"] for tag in author.get("/api/tags").json()}


def test_a_page_tag_is_held_to_the_same_spelling_as_a_guide_tag(author, category):
    created = create_page(author, "Immersion Oil", category_id=category.id)

    response = author.put(
        f"/api/pages/{created['id']}", json=page_document_from(created, tags=["Not A Slug"])
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_taking_a_tag_off_a_page_removes_it(author, category):
    created = create_page(author, "Immersion Oil", category_id=category.id)
    once = author.put(
        f"/api/pages/{created['id']}", json=page_document_from(created, tags=["thunder"])
    ).json()

    cleared = author.put(f"/api/pages/{once['id']}", json=page_document_from(once, tags=[])).json()

    assert cleared["tags"] == []


def test_a_page_can_be_asked_for_by_tag_as_a_guide_can(author, category):
    """A tag page asks both listings the same question. Without this filter the
    tag index could count a wiki and then send the reader to a screen that had no
    way of finding it."""
    tagged = create_page(author, "Immersion Oil", category_id=category.id)
    author.put(f"/api/pages/{tagged['id']}", json=page_document_from(tagged, tags=["thunder"]))
    create_page(author, "Something Else", category_id=category.id)

    listed = author.get("/api/pages", params={"tags": "thunder"}).json()

    assert [entry["title"] for entry in listed] == ["Immersion Oil"]


def test_asking_a_page_listing_for_two_tags_requires_both(author, category):
    """`all`, not `any` — the rule the guide listing follows, because one heading
    on a section's page asking for two tags means the documents that are both."""
    both = create_page(author, "Both", category_id=category.id)
    author.put(
        f"/api/pages/{both['id']}", json=page_document_from(both, tags=["thunder", "widefield"])
    )
    one = create_page(author, "Only One", category_id=category.id)
    author.put(f"/api/pages/{one['id']}", json=page_document_from(one, tags=["thunder"]))

    listed = author.get("/api/pages", params={"tags": "thunder,widefield"}).json()

    assert [entry["title"] for entry in listed] == ["Both"]
