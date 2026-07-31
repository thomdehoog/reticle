"""Category tree: listing for everyone, mutation for admins only."""

from __future__ import annotations

from .conftest import create_guide


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
