"""Text that is not English, all the way through.

Half of ZMB's corpus is German, and the rest is written by people from
everywhere. A system that handles ASCII and mangles the rest does not fail
loudly — it stores *something*, returns *something*, and the damage is found
months later in a guide nobody can search for.

Two failures have already been found here rather than reasoned about:

- SQLite's ``lower()`` folds A–Z and stops, so searching *PRÄPARATION* matched
  nothing (``app/db.py``).
- The login throttle joined two fields with a NUL byte, which PostgreSQL text
  columns cannot store at all (``app/security.py``).

Both were invisible on the engine they were written against. That is why this
file exists and why it runs on both.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import pytest

from .conftest import bullet, create_guide, create_page, document_from, page_document_from, step

# Umlauts and the sharp s; a decomposed form that looks identical but is a
# different byte sequence; Greek and Cyrillic, which microscopy notation uses;
# an emoji, which is outside the basic plane and is where a database configured
# for three-byte UTF-8 breaks.
SAMPLES = [
    ("german", "Präparation und Färbung der Objektträger"),
    ("sharp s", "Größe der Messblende"),
    ("decomposed", "Präparation"),  # a + combining diaeresis
    ("greek", "Immersionsöl με λ = 405 nm"),
    ("cyrillic", "Образец на предметном стекле"),
    ("outside the bmp", "Sample ready 🔬 for imaging"),
]


@pytest.mark.parametrize(("label", "text"), SAMPLES, ids=[name for name, _ in SAMPLES])
def test_a_title_survives_the_round_trip_byte_for_byte(author, category, label, text):
    """Not "looks right" — identical. A normalising round trip would silently
    rewrite what somebody typed, and the decomposed sample above is the case
    that catches it."""
    guide = create_guide(author, category.id, text)

    read_back = author.get(f"/api/guides/{guide['id']}").json()

    assert read_back["title"] == text


@pytest.mark.parametrize(("label", "text"), SAMPLES, ids=[name for name, _ in SAMPLES])
def test_body_text_survives_too(author, category, label, text):
    guide = create_guide(author, category.id, "Container")
    author.put(
        f"/api/guides/{guide['id']}",
        json=document_from(guide, summary=text, steps=[step(text, bullets=[bullet(text)])]),
    )

    read_back = author.get(f"/api/guides/{guide['id']}").json()

    assert read_back["summary"] == text
    assert read_back["steps"][0]["title"] == text
    assert read_back["steps"][0]["bullets"][0]["text"] == text


def test_a_german_guide_is_found_whatever_case_the_reader_types(author, category):
    """The bug this catches was live: on SQLite, searching in a different case
    from the one stored returned nothing at all for any German word."""
    guide = create_guide(author, category.id, "Präparation der Probe")
    author.put(f"/api/guides/{guide['id']}", json=document_from(guide))
    author.post(f"/api/guides/{guide['id']}/publish")

    for typed in ("Präparation", "präparation", "PRÄPARATION", "PRÄPAR"):
        hits = author.get("/api/search", params={"q": typed}).json()
        assert [h["guide"]["title"] for h in hits] == ["Präparation der Probe"], typed


def test_searching_inside_german_body_text_folds_case_too(author, category):
    guide = create_guide(author, category.id, "Sample Handling")
    author.put(
        f"/api/guides/{guide['id']}",
        json=document_from(
            guide, steps=[step("Vorbereitung", bullets=[bullet("Objektträger säubern.")])]
        ),
    )
    author.post(f"/api/guides/{guide['id']}/publish")

    for typed in ("OBJEKTTRÄGER", "objektträger", "SÄUBERN"):
        hits = author.get("/api/search", params={"q": typed}).json()
        assert len(hits) == 1, typed


def test_a_wiki_page_holds_german_body_text(author):
    page = create_page(author, title="Immersionsöl")
    author.put(
        f"/api/pages/{page['id']}",
        json=page_document_from(page, body="Welches Öl, und wann. Größe beachten."),
    )

    read_back = author.get(f"/api/pages/{page['id']}").json()

    assert read_back["title"] == "Immersionsöl"
    assert "Größe" in read_back["body"]


def test_an_account_with_an_umlaut_in_the_name_can_sign_in(anon, make_user):
    """Names are the field most likely to carry a character the developer did
    not think of, and the login path is the one where a failure locks somebody
    out rather than looking odd."""
    make_user("mueller@zmb.uzh.ch", display_name="Jürgen Müller")

    response = anon.login("mueller@zmb.uzh.ch")

    assert response.status_code == 200
    assert response.json()["displayName"] == "Jürgen Müller"


def test_a_failed_login_from_a_named_account_does_not_break_the_throttle(anon, make_user):
    """The throttle key joins the email with the client address, and the
    separator it used could not be stored by PostgreSQL at all — so every
    login attempt raised rather than being counted."""
    make_user("umlaut@zmb.uzh.ch", display_name="Jürgen Müller")

    for _ in range(3):
        assert anon.login("umlaut@zmb.uzh.ch", "wrong").status_code == 401

    assert anon.login("umlaut@zmb.uzh.ch").status_code == 200


def test_a_german_title_produces_a_usable_slug(author, category):
    """Slugs go into URLs, so they are ASCII — but they must still be distinct
    and non-empty. Folding umlauts away naively turns "Präparation" into
    "pr-paration", which was a real defect here."""
    guide = create_guide(author, category.id, "Präparation und Färbung")

    slug = author.get(f"/api/guides/{guide['id']}").json()["slug"]

    assert slug
    assert slug.isascii()
    assert "--" not in slug
    assert not slug.startswith("-") and not slug.endswith("-")
    assert "pr" in slug and "paration" in slug


def test_two_titles_differing_only_by_an_umlaut_do_not_collide(author, category):
    """Once umlauts are stripped for the slug, "Größe" and "Grosse" compete for
    the same one. Both guides must still be reachable."""
    first = create_guide(author, category.id, "Größe messen")
    second = create_guide(author, category.id, "Grosse messen")

    slugs = {
        author.get(f"/api/guides/{first['id']}").json()["slug"],
        author.get(f"/api/guides/{second['id']}").json()["slug"],
    }

    assert len(slugs) == 2


@pytest.mark.parametrize(
    ("typed", "slug"),
    [
        ("Präparation", "praparation"),
        ("Färbung", "farbung"),
        ("Objektträger", "objekttrager"),
        ("Größe", "grosse"),
        ("Immersionsöl", "immersionsol"),
    ],
)
def test_the_slug_the_editor_sends_for_a_german_tag_is_one_the_api_accepts(
    author, category, typed, slug
):
    """A contract across two languages, and the kind that breaks silently.

    The API accepts tags only as slugs; the editor folds what the author typed
    before sending it (``slugifyTag`` in ``TagInput.tsx``). Two independent
    implementations of the same folding is a standing invitation to drift, and
    the symptom would be a 422 on a tag the author can see in the box in front
    of them. This pins the backend half against the exact strings the frontend
    produces for the words this corpus actually uses.
    """
    from app.slugs import slugify

    assert slugify(typed) == slug

    guide = create_guide(author, category.id, f"Tagged {slug}")
    saved = author.put(f"/api/guides/{guide['id']}", json=document_from(guide, tags=[slug]))

    assert saved.status_code == 200, saved.text
    assert author.get(f"/api/guides/{guide['id']}").json()["tags"] == [slug]


def test_an_unfolded_german_tag_is_refused_rather_than_stored(author, category):
    """The other half of the contract. Accepting it would put a tag in the
    database that no URL can address, which is worse than a clear refusal."""
    guide = create_guide(author, category.id, "Tagged raw")

    refused = author.put(
        f"/api/guides/{guide['id']}", json=document_from(guide, tags=["Präparation"])
    )

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "validation_failed"
