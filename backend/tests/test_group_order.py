"""The order a section stacks its groups in.

Alphabetical is the fallback and it is nobody's running order: start-up,
acquisition, shutdown is the sequence somebody works in, and sorting it gives
`acquisition, shutdown, start-up`. So a section carries an order of tags — its
own, because `Talos` comes first in the electron-microscopy section and means
nothing in the light-microscopy one.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from .conftest import TEST_PASSWORD, create_guide, document_from


def tagged(client, category_id: str, tags: list[str], title: str = "A guide") -> dict:
    guide = create_guide(client, category_id, title)
    response = client.put(f"/api/guides/{guide['id']}", json=document_from(guide, tags=tags))
    assert response.status_code == 200, response.text
    return response.json()


def order_of(client, category_id: str) -> list[str]:
    listed = client.get("/api/categories").json()
    return next(entry for entry in listed if entry["id"] == category_id)["tagOrder"]


def test_a_section_starts_with_no_order_of_its_own(admin, category):
    """Nothing placed yet, and the page falls back to alphabetical. An empty
    list rather than every tag in some default arrangement: the difference is
    whether the page can tell a choice from the absence of one."""
    tagged(admin, category.id, ["shutdown", "startup"])

    assert order_of(admin, category.id) == []


def test_an_administrator_stacks_the_groups(admin, category):
    tagged(admin, category.id, ["startup", "shutdown", "acquisition"])

    placed = admin.put(
        f"/api/categories/{category.id}/tag-order",
        json={"tags": ["startup", "acquisition", "shutdown"]},
    )

    assert placed.status_code == 200, placed.text
    assert placed.json()["tagOrder"] == ["startup", "acquisition", "shutdown"]
    assert order_of(admin, category.id) == ["startup", "acquisition", "shutdown"]


def test_the_order_is_replaced_whole_rather_than_added_to(admin, category):
    """The index is a position, not a weight. Writing one group's new number and
    leaving the rest would put two on the same one and let the tie decide."""
    tagged(admin, category.id, ["startup", "shutdown", "acquisition"])
    admin.put(
        f"/api/categories/{category.id}/tag-order",
        json={"tags": ["startup", "acquisition", "shutdown"]},
    )

    again = admin.put(
        f"/api/categories/{category.id}/tag-order", json={"tags": ["shutdown", "startup"]}
    )

    assert again.json()["tagOrder"] == ["shutdown", "startup"]


def test_the_same_tag_twice_is_one_position(admin, category):
    tagged(admin, category.id, ["startup", "shutdown"])

    placed = admin.put(
        f"/api/categories/{category.id}/tag-order",
        json={"tags": ["startup", "shutdown", "startup"]},
    )

    assert placed.json()["tagOrder"] == ["startup", "shutdown"]


def test_an_order_naming_a_tag_that_does_not_exist_is_refused(admin, category):
    """This names groups, and a group with nothing in it is not one. An order
    that could mint them would let a typo add a heading no document is under."""
    tagged(admin, category.id, ["startup"])

    refused = admin.put(
        f"/api/categories/{category.id}/tag-order", json={"tags": ["startup", "stratup"]}
    )

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "validation_failed"
    assert order_of(admin, category.id) == []


def test_each_section_stacks_its_own_groups(admin, category, db_session):
    """`Talos` comes first in the electron-microscopy section and means nothing
    in the light-microscopy one, which is why this belongs to the section."""
    from app.models import Category

    other = Category(slug="other-room", name="Other Room")
    db_session.add(other)
    db_session.commit()

    tagged(admin, category.id, ["startup", "shutdown"])
    admin.put(f"/api/categories/{category.id}/tag-order", json={"tags": ["shutdown", "startup"]})

    assert order_of(admin, other.id) == []


def test_an_author_cannot_restack_a_section(author, admin, category):
    """A row's group is a fact about the document and is reachable from its own
    editor. The running order of a section's page is the section's, and every
    reader gets it."""
    tagged(admin, category.id, ["startup", "shutdown"])

    refused = author.put(
        f"/api/categories/{category.id}/tag-order", json={"tags": ["shutdown", "startup"]}
    )

    assert refused.status_code == 403
    assert order_of(admin, category.id) == []


def test_a_section_that_does_not_exist_says_so(admin, category):
    tagged(admin, category.id, ["startup"])

    missing = admin.put(
        "/api/categories/01ARZ3NDEKTSV4RRFFQ69G5FAV/tag-order", json={"tags": ["startup"]}
    )

    assert missing.status_code == 404


def test_deleting_a_section_takes_its_order_with_it(admin, category, db_session):
    """The cascade is why this is a table rather than a list of slugs on the
    category: nothing has to remember to tidy up after it."""
    from sqlalchemy import select

    from app.models import CategoryTagOrder

    tagged(admin, category.id, ["startup"])
    admin.put(f"/api/categories/{category.id}/tag-order", json={"tags": ["startup"]})
    assert db_session.scalars(select(CategoryTagOrder)).all()

    removed = admin.delete(f"/api/categories/{category.id}", json={"password": TEST_PASSWORD})

    assert removed.status_code == 204, removed.text
    db_session.expire_all()
    assert db_session.scalars(select(CategoryTagOrder)).all() == []
