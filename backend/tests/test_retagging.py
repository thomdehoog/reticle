"""Moving a document between the groups on a section's page.

A section's page is arranged by dragging a row from one group into another, and
the tags are what a group is. That drag is a statement about the section rather
than about the document, which is what this route exists to keep true: it
reaches the same tags the document editor reaches, and touches nothing else —
not the prose, not the steps, and not the byline.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from .conftest import create_guide, document_from


def guide_with(client, category_id: str, tags: list[str], title: str = "Talos start-up") -> dict:
    guide = create_guide(client, category_id, title)
    response = client.put(f"/api/guides/{guide['id']}", json=document_from(guide, tags=tags))
    assert response.status_code == 200, response.text
    return response.json()


def page_with(client, category_id: str, tags: list[str], title: str = "Immersion oil") -> dict:
    created = client.post("/api/pages", json={"title": title, "categoryId": category_id}).json()
    response = client.put(
        f"/api/pages/{created['id']}",
        json={
            "title": created["title"],
            "summary": "",
            "body": "",
            "categoryId": category_id,
            "isLanding": False,
            "heroMediaId": None,
            "tags": tags,
            "updatedAt": created["updatedAt"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_a_guide_can_be_moved_from_one_group_to_another(author, category):
    guide = guide_with(author, category.id, ["talos"])

    moved = author.put(
        f"/api/guides/{guide['id']}/tags",
        json={"tags": ["nikon"], "updatedAt": guide["updatedAt"]},
    )

    assert moved.status_code == 200, moved.text
    assert moved.json()["tags"] == ["nikon"]
    assert author.get(f"/api/guides/{guide['id']}").json()["tags"] == ["nikon"]


def test_a_wiki_can_be_moved_the_same_way(author, category):
    """The whole point of the drag: the article about the Nikon goes under
    `nikon`, beside the procedures for it."""
    page = page_with(author, category.id, [])

    moved = author.put(
        f"/api/pages/{page['id']}/tags",
        json={"tags": ["nikon"], "updatedAt": page["updatedAt"]},
    )

    assert moved.status_code == 200, moved.text
    assert moved.json()["tags"] == ["nikon"]


def test_moving_a_guide_out_of_one_group_leaves_its_other_groups_alone(author, category):
    """A guide belongs under every instrument it applies to — a fifth of ZMB's
    corpus is in more than one group. Dragging a row out of one heading must not
    take it out of the nine others it appears under."""
    guide = guide_with(author, category.id, ["talos", "lasx", "sem"])

    moved = author.put(
        f"/api/guides/{guide['id']}/tags",
        json={"tags": ["lasx", "sem", "nikon"], "updatedAt": guide["updatedAt"]},
    )

    # The order sent is the order kept, as on a whole-document save.
    assert moved.json()["tags"] == ["lasx", "sem", "nikon"]


def test_the_document_itself_is_untouched(author, category):
    guide = guide_with(author, category.id, ["talos"])

    author.put(
        f"/api/guides/{guide['id']}/tags",
        json={"tags": ["nikon"], "updatedAt": guide["updatedAt"]},
    )

    after = author.get(f"/api/guides/{guide['id']}").json()
    assert after["title"] == guide["title"]
    assert after["introduction"] == guide["introduction"]
    assert after["steps"] == guide["steps"]


def test_arranging_a_section_does_not_put_a_name_on_a_guides_byline(author, admin, category):
    """Whoever dragged the row did not write the guide. A contributor list that
    grows every time somebody tidies a section stops being the answer to "who do
    I ask about this procedure", which is the only reason it is kept."""
    guide = guide_with(author, category.id, ["talos"])
    before = {contributor["id"] for contributor in guide["contributors"]}

    admin.put(
        f"/api/guides/{guide['id']}/tags",
        json={"tags": ["nikon"], "updatedAt": guide["updatedAt"]},
    )

    after = author.get(f"/api/guides/{guide['id']}").json()
    assert {contributor["id"] for contributor in after["contributors"]} == before
    assert after["lastEditedBy"]["id"] == guide["lastEditedBy"]["id"]


def test_the_timestamp_moves_so_the_next_drag_is_measured_against_this_one(author, category):
    guide = guide_with(author, category.id, ["talos"])

    moved = author.put(
        f"/api/guides/{guide['id']}/tags",
        json={"tags": ["nikon"], "updatedAt": guide["updatedAt"]},
    ).json()

    assert moved["updatedAt"] > guide["updatedAt"]


def test_a_drag_against_a_stale_row_is_refused(author, category):
    """The row carries the tags the reader could see. If the guide changed
    underneath them, the move they meant is not the move this would make."""
    guide = guide_with(author, category.id, ["talos"])
    author.put(f"/api/guides/{guide['id']}", json=document_from(guide, tags=["talos", "lasx"]))

    refused = author.put(
        f"/api/guides/{guide['id']}/tags",
        json={"tags": ["nikon"], "updatedAt": guide["updatedAt"]},
    )

    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "conflict"


def test_a_tag_invented_by_a_drag_is_minted(author, category):
    guide = guide_with(author, category.id, [])

    author.put(
        f"/api/guides/{guide['id']}/tags",
        json={"tags": ["brand-new-group"], "updatedAt": guide["updatedAt"]},
    )

    assert "brand-new-group" in {tag["slug"] for tag in author.get("/api/tags").json()}


def test_a_drag_is_held_to_the_same_spelling_as_the_editor(author, category):
    guide = guide_with(author, category.id, [])

    refused = author.put(
        f"/api/guides/{guide['id']}/tags",
        json={"tags": ["Not A Slug"], "updatedAt": guide["updatedAt"]},
    )

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "validation_failed"


def test_a_reader_cannot_rearrange_a_section(viewer, author, category):
    """The same right the tag field in the editor needs, by a shorter route —
    which means it is still a right, and a reader does not have it."""
    guide = guide_with(author, category.id, ["talos"])

    refused = viewer.put(
        f"/api/guides/{guide['id']}/tags",
        json={"tags": ["nikon"], "updatedAt": guide["updatedAt"]},
    )

    assert refused.status_code == 403
    assert author.get(f"/api/guides/{guide['id']}").json()["tags"] == ["talos"]


def test_a_signed_out_visitor_cannot_rearrange_a_section(anon, author, category):
    guide = guide_with(author, category.id, ["talos"])

    refused = anon.put(
        f"/api/guides/{guide['id']}/tags",
        json={"tags": ["nikon"], "updatedAt": guide["updatedAt"]},
    )

    # 403 rather than 401, as every other write in the API answers a visitor.
    assert refused.status_code == 403


def test_dragging_a_row_that_no_longer_exists_says_so(author, category):
    guide = guide_with(author, category.id, ["talos"])

    missing = author.put(
        "/api/guides/01ARZ3NDEKTSV4RRFFQ69G5FAV/tags",
        json={"tags": ["nikon"], "updatedAt": guide["updatedAt"]},
    )

    assert missing.status_code == 404
