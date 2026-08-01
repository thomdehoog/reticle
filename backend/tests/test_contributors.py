"""Who wrote this, and who do I ask about it.

At a facility the edit history is frequently the only surviving answer to why a
procedure says what it says. That is why the credit is kept as data rather than
derived from the audit log, which is rotated — and why the failures worth
guarding against are the ones that lose it quietly. A contributor recorded only
on creation drops everyone who maintained the document afterwards; one recorded
on every save without a uniqueness rule turns the by-line into the same name
forty times; and a list rebuilt in last-edited order loses the one fact people
actually use it for, which is who started it and who joined when.
"""

from __future__ import annotations

from .conftest import create_guide, create_page, document_from, page_document_from


def names(document: dict) -> list[str]:
    return [person["displayName"] for person in document["contributors"]]


def test_creating_a_guide_credits_its_author_immediately(author, category):
    created = create_guide(author, category.id)

    assert names(created) == ["Author"]
    assert created["contributors"] == [created["author"]]


def test_creating_a_page_credits_its_author_immediately(author, category):
    created = create_page(author, category_id=category.id)

    assert names(created) == ["Author"]
    assert created["contributors"] == [created["author"]]


def test_a_colleague_who_saves_a_guide_is_appended(author, as_role, category):
    created = create_guide(author, category.id)
    colleague = as_role("author", "colleague@zmb.uzh.ch", display_name="Colleague Editor")

    fresh = colleague.get(f"/api/guides/{created['id']}").json()
    saved = colleague.put(f"/api/guides/{created['id']}", json=document_from(fresh, title="Edited")).json()

    assert names(saved) == ["Author", "Colleague Editor"]


def test_a_colleague_who_saves_a_page_is_appended(author, as_role, category):
    created = create_page(author, category_id=category.id)
    colleague = as_role("author", "colleague@zmb.uzh.ch", display_name="Colleague Editor")

    fresh = colleague.get(f"/api/pages/{created['id']}").json()
    saved = colleague.put(f"/api/pages/{created['id']}", json=page_document_from(fresh, body="Edited")).json()

    assert names(saved) == ["Author", "Colleague Editor"]


def test_the_order_is_who_touched_it_first_not_who_touched_it_last(author, as_role, category):
    created = create_guide(author, category.id)
    second = as_role("author", "second@zmb.uzh.ch", display_name="Second Editor")
    third = as_role("author", "third@zmb.uzh.ch", display_name="Third Editor")

    document = second.put(
        f"/api/guides/{created['id']}",
        json=document_from(second.get(f"/api/guides/{created['id']}").json(), title="Second pass"),
    ).json()
    document = third.put(
        f"/api/guides/{created['id']}", json=document_from(document, title="Third pass")
    ).json()
    document = second.put(
        f"/api/guides/{created['id']}", json=document_from(document, title="Second again")
    ).json()

    assert names(document) == ["Author", "Second Editor", "Third Editor"]
    assert document["lastEditedBy"]["displayName"] == "Second Editor"


def test_saving_repeatedly_never_duplicates_a_contributor(author, category):
    document = create_guide(author, category.id)

    for index in range(5):
        document = author.put(
            f"/api/guides/{document['id']}", json=document_from(document, title=f"Pass {index}")
        ).json()

    assert names(document) == ["Author"]


def test_saving_a_page_repeatedly_never_duplicates_a_contributor(author, category):
    document = create_page(author, category_id=category.id)

    for index in range(5):
        document = author.put(
            f"/api/pages/{document['id']}", json=page_document_from(document, body=f"Pass {index}")
        ).json()

    assert names(document) == ["Author"]


def test_the_original_author_stays_credited_even_once_others_take_over(author, as_role, category):
    """The author field records who started it; the contributor list is not a
    replacement for it, and losing either loses a different question's answer."""
    created = create_guide(author, category.id)
    colleague = as_role("author", "colleague@zmb.uzh.ch", display_name="Colleague Editor")

    document = colleague.put(
        f"/api/guides/{created['id']}",
        json=document_from(colleague.get(f"/api/guides/{created['id']}").json(), title="Taken over"),
    ).json()

    assert document["author"]["displayName"] == "Author"
    assert names(document)[0] == "Author"
    assert document["author"] in document["contributors"]


def test_an_admin_who_edits_a_guide_is_credited_like_anyone_else(author, admin, category):
    created = create_guide(author, category.id)

    document = admin.put(
        f"/api/guides/{created['id']}",
        json=document_from(admin.get(f"/api/guides/{created['id']}").json(), title="Corrected"),
    ).json()

    assert names(document) == ["Author", "Admin"]


def test_a_rejected_save_credits_nobody(author, as_role, category):
    """A save that fails validation is not an edit, and crediting the attempt
    would put a name on a document that person never changed."""
    created = create_guide(author, category.id)
    colleague = as_role("author", "colleague@zmb.uzh.ch", display_name="Colleague Editor")

    refused = colleague.put(
        f"/api/guides/{created['id']}",
        json=document_from(
            colleague.get(f"/api/guides/{created['id']}").json(),
            timeRequiredMinMinutes=90,
            timeRequiredMaxMinutes=10,
        ),
    )

    assert refused.status_code == 422
    assert names(author.get(f"/api/guides/{created['id']}").json()) == ["Author"]


def test_contributors_are_carried_into_the_publish_snapshot(author, as_role, category):
    created = create_guide(author, category.id)
    colleague = as_role("author", "colleague@zmb.uzh.ch", display_name="Colleague Editor")
    colleague.put(
        f"/api/guides/{created['id']}",
        json=document_from(colleague.get(f"/api/guides/{created['id']}").json(), title="Edited"),
    )
    author.post(f"/api/guides/{created['id']}/publish")

    snapshot = author.get(f"/api/guides/{created['id']}/revisions/1").json()

    assert names(snapshot) == ["Author", "Colleague Editor"]


def test_a_reader_is_shown_the_credit_on_a_published_guide(author, viewer, category):
    created = create_guide(author, category.id)
    author.post(f"/api/guides/{created['id']}/publish")

    assert names(viewer.get(f"/api/guides/{created['slug']}").json()) == ["Author"]


def test_a_reader_is_shown_the_credit_on_a_published_page(author, viewer, category):
    created = create_page(author, category_id=category.id)
    author.post(f"/api/pages/{created['id']}/publish")

    assert names(viewer.get(f"/api/pages/{created['slug']}").json()) == ["Author"]


def test_a_contributor_reference_carries_nothing_beyond_a_name(author, category):
    """The list is rendered on a public page, so it must not become a way to
    read colleagues' email addresses out of the institute's directory."""
    created = create_guide(author, category.id)

    assert set(created["contributors"][0]) == {"id", "displayName"}
