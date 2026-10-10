"""Category tree: listing for everyone, mutation for admins only."""

from __future__ import annotations

from .conftest import create_guide, create_page, published_page, save_page


def test_any_authenticated_role_can_list_categories(viewer, category):
    response = viewer.get("/api/categories")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": category.id,
            "slug": "light-microscopy",
            "name": "Light Microscopy",
            "description": "Confocal, widefield and superresolution systems.",
            "parentId": None,
            "orderIndex": 0,
            "isHidden": False,
        }
    ]


def test_listing_categories_requires_a_session(anon):
    assert anon.get("/api/categories").status_code == 401


def test_admin_creates_a_category_and_the_slug_is_derived(admin):
    response = admin.post("/api/categories", json={"name": "Electron Microscopy", "description": "TEM and SEM."})

    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "electron-microscopy"
    assert body["parentId"] is None
    assert body["orderIndex"] == 0


def test_slugs_transliterate_rather_than_dropping_accents(admin):
    body = admin.post("/api/categories", json={"name": "Zürich Präparation"}).json()

    assert body["slug"] == "zurich-praparation"


def test_new_categories_append_within_their_parent(admin):
    first = admin.post("/api/categories", json={"name": "Basics"}).json()
    second = admin.post("/api/categories", json={"name": "Advanced"}).json()
    child = admin.post("/api/categories", json={"name": "Sub", "parentId": first["id"]}).json()

    assert (first["orderIndex"], second["orderIndex"]) == (0, 1)
    assert child["orderIndex"] == 0
    assert child["parentId"] == first["id"]


def test_duplicate_category_names_get_distinct_slugs(admin):
    first = admin.post("/api/categories", json={"name": "Imaging"}).json()
    second = admin.post("/api/categories", json={"name": "Imaging"}).json()

    assert first["slug"] == "imaging"
    assert second["slug"] == "imaging-2"


def test_admin_renames_reparents_and_reorders(admin, category):
    parent = admin.post("/api/categories", json={"name": "Parent"}).json()

    response = admin.patch(
        f"/api/categories/{category.id}",
        json={"name": "Light Microscopy (LM)", "parentId": parent["id"], "orderIndex": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Light Microscopy (LM)"
    assert body["parentId"] == parent["id"]
    assert body["orderIndex"] == 3
    assert body["slug"] == "light-microscopy"


def test_a_category_cannot_become_its_own_ancestor(admin, category):
    child = admin.post("/api/categories", json={"name": "Child", "parentId": category.id}).json()

    response = admin.patch(f"/api/categories/{category.id}", json={"parentId": child["id"]})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_category_cannot_be_its_own_parent(admin, category):
    assert admin.patch(f"/api/categories/{category.id}", json={"parentId": category.id}).status_code == 422


def test_reparenting_to_an_unknown_category_is_rejected(admin, category):
    response = admin.patch(f"/api/categories/{category.id}", json={"parentId": "01JQNOTAREALULID00000000"})

    assert response.status_code == 422


def test_deleting_an_empty_category_succeeds(admin):
    created = admin.post("/api/categories", json={"name": "Temporary"}).json()

    assert admin.delete(f"/api/categories/{created['id']}").status_code == 204
    assert admin.get("/api/categories").json() == []


def test_deleting_a_category_that_still_has_children_conflicts(admin, category):
    admin.post("/api/categories", json={"name": "Child", "parentId": category.id})

    response = admin.delete(f"/api/categories/{category.id}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_deleting_a_category_that_still_holds_guides_conflicts(admin, category):
    create_guide(admin, category.id)

    response = admin.delete(f"/api/categories/{category.id}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_deleting_an_unknown_category_is_not_found(admin):
    response = admin.delete("/api/categories/01JQNOTAREALULID00000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_viewers_cannot_create_categories(viewer):
    response = viewer.post("/api/categories", json={"name": "Sneaky"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_authors_cannot_manage_categories(author, category):
    assert author.post("/api/categories", json={"name": "Sneaky"}).status_code == 403
    assert author.patch(f"/api/categories/{category.id}", json={"name": "x"}).status_code == 403
    assert author.delete(f"/api/categories/{category.id}").status_code == 403


def test_creating_a_category_without_a_name_is_rejected(admin):
    assert admin.post("/api/categories", json={"description": "orphan"}).status_code == 422


def test_a_blank_name_is_rejected(admin):
    assert admin.post("/api/categories", json={"name": "   "}).status_code == 422


def test_a_holding_category_can_be_created_hidden_and_toggled(admin):
    created = admin.post("/api/categories", json={"name": "Confocal - hidden guides", "isHidden": True}).json()
    assert created["isHidden"] is True

    shown = admin.patch(f"/api/categories/{created['id']}", json={"isHidden": False}).json()
    assert shown["isHidden"] is False
    assert admin.patch(f"/api/categories/{created['id']}", json={"name": "Renamed"}).json()["isHidden"] is False


def test_hiding_a_category_is_navigation_not_access_control(admin, author, viewer):
    """Its guides are still listed, searched and read like any others."""
    hidden = admin.post("/api/categories", json={"name": "Holding", "isHidden": True}).json()
    from .conftest import published_guide

    guide = published_guide(author, hidden["id"], "Tile Scan", tags=["confocal"])

    assert [c["id"] for c in viewer.get("/api/categories").json()] == [hidden["id"]]
    assert [g["id"] for g in viewer.get("/api/guides", params={"tags": "confocal"}).json()] == [guide["id"]]
    assert [g["id"] for g in viewer.get("/api/guides", params={"categoryId": hidden["id"]}).json()] == [guide["id"]]
    assert viewer.get(f"/api/guides/{guide['slug']}").status_code == 200
    assert [r["guide"]["id"] for r in viewer.get("/api/search", params={"q": "tile"}).json()] == [guide["id"]]


def test_deleting_a_category_that_still_holds_a_page_conflicts(admin, category):
    create_page(admin, "Filed here", categoryId=category.id)

    response = admin.delete(f"/api/categories/{category.id}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert "page" in response.json()["error"]["message"].lower()


def test_an_archived_page_still_pins_its_category(admin, category):
    """Archiving is a soft delete; the row still points at the category."""
    page = create_page(admin, "Landing", categoryId=category.id, isLanding=True)
    admin.delete(f"/api/pages/{page['id']}")

    assert admin.delete(f"/api/categories/{category.id}").status_code == 409


def test_a_category_with_no_landing_page_answers_null_not_an_error(viewer, category):
    response = viewer.get(f"/api/categories/{category.id}/page")

    assert response.status_code == 200
    assert response.json() is None


def test_the_landing_page_of_a_category_is_returned_in_full(viewer, author, category):
    published = published_page(author, "Light Microscopy", body="# Welcome", categoryId=category.id, isLanding=True)
    published_page(author, "An ordinary page in the category", categoryId=category.id)

    body = viewer.get(f"/api/categories/{category.id}/page").json()

    assert body["id"] == published["id"]
    assert body["isLanding"] is True
    assert body["body"] == "# Welcome"


def test_a_draft_landing_page_is_null_for_a_viewer_and_visible_to_an_author(viewer, author, category):
    draft = create_page(author, "Being written", categoryId=category.id, isLanding=True)
    save_page(author, draft, body="Not ready.")

    assert viewer.get(f"/api/categories/{category.id}/page").json() is None
    assert author.get(f"/api/categories/{category.id}/page").json()["id"] == draft["id"]


def test_an_archived_landing_page_is_null_for_everyone(admin, author, category):
    page = published_page(author, "Old landing", categoryId=category.id, isLanding=True)
    admin.delete(f"/api/pages/{page['id']}")

    assert author.get(f"/api/categories/{category.id}/page").json() is None
    assert admin.get(f"/api/categories/{category.id}/page").json() is None


def test_the_landing_page_of_an_unknown_category_is_not_found(viewer):
    assert viewer.get("/api/categories/01JQNOTAREALULID00000000/page").status_code == 404


def test_the_landing_page_endpoint_requires_a_session(anon, category):
    assert anon.get(f"/api/categories/{category.id}/page").status_code == 401
