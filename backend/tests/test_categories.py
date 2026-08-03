"""Category tree: listing for everyone, mutation for admins only."""

from __future__ import annotations

from .conftest import create_guide, upload_media, upload_video


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
            "heroMediaId": None,
            "imageUrl": None,
        }
    ]


def test_the_sections_are_listed_to_anybody(anon):
    """Browsing is public. The login decides who may change a section, not who
    may see that one exists."""
    assert anon.get("/api/categories").status_code == 200


def test_admin_creates_a_category_and_the_slug_is_derived(admin):
    response = admin.post(
        "/api/categories", json={"name": "Electron Microscopy", "description": "TEM and SEM."}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "electron-microscopy"
    assert body["parentId"] is None
    assert body["orderIndex"] == 0
    assert body["isHidden"] is False


def test_a_holding_category_can_be_created_hidden(admin):
    """ZMB's largest section is a hidden pen of confocal guides that readers only
    ever reach through tags, so hiding has to be settable at creation."""
    body = admin.post(
        "/api/categories",
        json={"name": "Confocal - hidden guides", "isHidden": True},
    ).json()

    assert body["isHidden"] is True
    assert [c["isHidden"] for c in admin.get("/api/categories").json()] == [True]


def test_hiding_and_revealing_a_category_is_a_patch(admin, category):
    hidden = admin.patch(f"/api/categories/{category.id}", json={"isHidden": True}).json()
    revealed = admin.patch(f"/api/categories/{category.id}", json={"isHidden": False}).json()

    assert hidden["isHidden"] is True
    assert revealed["isHidden"] is False


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
    assert (
        admin.patch(f"/api/categories/{category.id}", json={"parentId": category.id}).status_code
        == 422
    )


def test_reparenting_to_an_unknown_category_is_rejected(admin, category):
    response = admin.patch(
        f"/api/categories/{category.id}", json={"parentId": "01JQNOTAREALULID00000000"}
    )

    assert response.status_code == 422


def test_creating_a_category_under_an_unknown_parent_is_rejected(admin):
    response = admin.post(
        "/api/categories", json={"name": "Orphan", "parentId": "01JQNOTAREALULID00000000"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_category_can_be_moved_back_to_the_root(admin, category):
    child = admin.post("/api/categories", json={"name": "Child", "parentId": category.id}).json()

    detached = admin.patch(f"/api/categories/{child['id']}", json={"parentId": None}).json()

    assert detached["parentId"] is None


def test_the_description_is_editable_on_its_own(admin, category):
    body = admin.patch(
        f"/api/categories/{category.id}",
        json={"description": "Widefield, confocal and superresolution."},
    ).json()

    assert body["description"] == "Widefield, confocal and superresolution."
    assert body["name"] == "Light Microscopy"


def test_renaming_a_category_to_nothing_is_rejected(admin, category):
    response = admin.patch(f"/api/categories/{category.id}", json={"name": "   "})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert admin.get("/api/categories").json()[0]["name"] == "Light Microscopy"


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


def test_a_section_can_be_given_the_picture_it_is_browsed_by(admin, category):
    """Browsing is done by eye, so the picture is part of the category."""
    image = upload_media(admin)

    body = admin.patch(f"/api/categories/{category.id}", json={"heroMediaId": image["id"]}).json()

    assert body["heroMediaId"] == image["id"]
    assert body["imageUrl"] == f"/api/media/{image['id']}"


def test_a_section_picture_can_be_taken_away_again(admin, category):
    image = upload_media(admin)
    admin.patch(f"/api/categories/{category.id}", json={"heroMediaId": image["id"]})

    body = admin.patch(f"/api/categories/{category.id}", json={"heroMediaId": None}).json()

    assert body["heroMediaId"] is None
    assert body["imageUrl"] is None


def test_a_picture_that_does_not_exist_is_refused(admin, category):
    """Storing it would leave every tile for the section showing a broken image."""
    response = admin.patch(
        f"/api/categories/{category.id}", json={"heroMediaId": "01JQNOTAREALULID00000000"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_video_cannot_be_a_section_picture(admin, category):
    video = upload_video(admin)

    response = admin.patch(f"/api/categories/{category.id}", json={"heroMediaId": video["id"]})

    assert response.status_code == 422


def test_a_section_can_be_created_with_its_picture(admin):
    image = upload_media(admin)

    body = admin.post("/api/categories", json={"name": "CryoEM", "heroMediaId": image["id"]}).json()

    assert body["imageUrl"] == f"/api/media/{image['id']}"
