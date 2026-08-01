"""How often a document is actually read.

Two things can go wrong here and neither announces itself. The first is
counting the wrong reads: an author refreshing their own draft forty times while
writing it would make the busiest guide in the institute the one nobody has
read, so only published content counts.

The second is the expensive one. ``updatedAt`` is the optimistic-concurrency
token, so if incrementing the counter moved it, every reader opening a guide
would invalidate the copy held by whoever was editing it — their next autosave
would come back 409 and they would be told to reload and lose their work,
apparently at random. A read is not an edit, and this file exists to keep it
that way.
"""

from __future__ import annotations

from .conftest import create_guide, create_page, document_from, page_document_from


def published_guide(client, category_id: str, title: str = "Public Guide") -> dict:
    created = create_guide(client, category_id, title)
    response = client.post(f"/api/guides/{created['id']}/publish")
    assert response.status_code == 200, response.text
    return response.json()


def published_page(client, title: str = "Public Page") -> dict:
    created = create_page(client, title)
    response = client.post(f"/api/pages/{created['id']}/publish")
    assert response.status_code == 200, response.text
    return response.json()


def test_a_new_guide_starts_at_zero(author, category):
    assert create_guide(author, category.id)["viewCount"] == 0


def test_each_read_of_a_published_guide_counts_once(author, viewer, category):
    created = published_guide(author, category.id)

    first = viewer.get(f"/api/guides/{created['slug']}").json()
    second = viewer.get(f"/api/guides/{created['slug']}").json()
    third = viewer.get(f"/api/guides/{created['id']}").json()

    assert [first["viewCount"], second["viewCount"], third["viewCount"]] == [1, 2, 3]


def test_each_read_of_a_published_page_counts_once(author, viewer):
    created = published_page(author)

    first = viewer.get(f"/api/pages/{created['slug']}").json()
    second = viewer.get(f"/api/pages/{created['id']}").json()

    assert [first["viewCount"], second["viewCount"]] == [1, 2]


def test_reading_a_draft_guide_counts_nothing(author, category):
    created = create_guide(author, category.id)

    for _ in range(3):
        author.get(f"/api/guides/{created['id']}")

    assert author.get(f"/api/guides/{created['id']}").json()["viewCount"] == 0


def test_reading_a_draft_page_counts_nothing(author, category):
    created = create_page(author, category_id=category.id)

    for _ in range(3):
        author.get(f"/api/pages/{created['id']}")

    assert author.get(f"/api/pages/{created['id']}").json()["viewCount"] == 0


def test_unpublishing_stops_the_counter_without_resetting_it(author, viewer, category):
    created = published_guide(author, category.id)
    viewer.get(f"/api/guides/{created['slug']}")

    author.post(f"/api/guides/{created['id']}/unpublish")
    author.get(f"/api/guides/{created['id']}")

    assert author.get(f"/api/guides/{created['id']}").json()["viewCount"] == 1


def test_an_archived_guide_stops_counting_too(author, admin, category):
    created = published_guide(author, category.id)
    admin.get(f"/api/guides/{created['id']}")

    admin.delete(f"/api/guides/{created['id']}")
    admin.get(f"/api/guides/{created['id']}")

    assert admin.get(f"/api/guides/{created['id']}").json()["viewCount"] == 1


def test_counting_a_read_does_not_move_the_guides_updated_at(author, viewer, category):
    created = published_guide(author, category.id)

    read = viewer.get(f"/api/guides/{created['slug']}").json()

    assert read["viewCount"] == 1
    assert read["updatedAt"] == created["updatedAt"]


def test_counting_a_read_does_not_move_the_pages_updated_at(author, viewer):
    created = published_page(author)

    read = viewer.get(f"/api/pages/{created['slug']}").json()

    assert read["viewCount"] == 1
    assert read["updatedAt"] == created["updatedAt"]


def test_readers_arriving_do_not_eject_an_author_who_has_the_guide_open(author, viewer, category):
    """The concrete failure: an editor holds a copy, readers open the guide, and
    the autosave that follows must still be accepted rather than told its copy
    is stale."""
    created = published_guide(author, category.id)
    held_by_the_editor = author.get(f"/api/guides/{created['id']}").json()

    for _ in range(5):
        viewer.get(f"/api/guides/{created['slug']}")

    saved = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(held_by_the_editor, title="Saved after the readers arrived"),
    )

    assert saved.status_code == 200, saved.text
    assert saved.json()["title"] == "Saved after the readers arrived"


def test_readers_arriving_do_not_eject_an_author_who_has_the_page_open(author, viewer):
    created = published_page(author)
    held_by_the_editor = author.get(f"/api/pages/{created['id']}").json()

    for _ in range(5):
        viewer.get(f"/api/pages/{created['slug']}")

    saved = author.put(
        f"/api/pages/{created['id']}",
        json=page_document_from(held_by_the_editor, body="Saved after the readers arrived"),
    )

    assert saved.status_code == 200, saved.text


def test_a_read_that_counts_does_not_count_as_an_edit(author, viewer, category):
    created = published_guide(author, category.id)
    before = author.get(f"/api/guides/{created['id']}").json()

    viewer.get(f"/api/guides/{created['slug']}")
    after = author.get(f"/api/guides/{created['id']}").json()

    assert after["viewCount"] > before["viewCount"]
    assert after["lastEditedBy"] == before["lastEditedBy"]
    assert after["version"] == before["version"]
    assert after["contributors"] == before["contributors"]


def test_the_count_is_carried_on_the_summary_projection_as_well(author, viewer, category):
    created = published_guide(author, category.id)
    viewer.get(f"/api/guides/{created['slug']}")
    viewer.get(f"/api/guides/{created['slug']}")

    entry = viewer.get("/api/guides").json()[0]

    assert entry["id"] == created["id"]
    assert entry["viewCount"] == 2


def test_the_count_is_carried_into_search_results(author, viewer, category):
    created = published_guide(author, category.id, "Immersion Oil Guide")
    viewer.get(f"/api/guides/{created['slug']}")

    hit = viewer.get("/api/search", params={"q": "immersion"}).json()[0]

    assert hit["guide"]["viewCount"] == 1


def test_editing_a_guide_leaves_its_readership_alone(author, viewer, category):
    created = published_guide(author, category.id)
    viewer.get(f"/api/guides/{created['slug']}")

    fresh = author.get(f"/api/guides/{created['id']}").json()
    saved = author.put(f"/api/guides/{created['id']}", json=document_from(fresh, title="Renamed")).json()

    assert saved["viewCount"] == 2


def test_every_reader_counts_not_just_the_first(author, viewer, as_role, category):
    created = published_guide(author, category.id)
    second_reader = as_role("viewer", "second.reader@zmb.uzh.ch")

    viewer.get(f"/api/guides/{created['slug']}")
    second_reader.get(f"/api/guides/{created['slug']}")

    assert author.get(f"/api/guides/{created['id']}").json()["viewCount"] == 3
