"""Validation failures, as the person at the editor reads them.

The editors show ``error.message`` as it stands. Its reader is writing a
microscopy protocol, so "request: Value error, …" and "steps.0.bullets.2.text"
are noise at best; these pin the sentences they get instead.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from app import errors

from .conftest import create_guide, create_page, document_from


def message_of(response) -> str:
    assert response.status_code == 422, response.text
    body = response.json()["error"]
    assert body["code"] == "validation_failed"
    return body["message"]


def put_guide(author, category, **changes) -> str:
    created = create_guide(author, category.id)
    return message_of(author.put(f"/api/guides/{created['id']}", json={**document_from(created), **changes}))


def test_a_backwards_time_range_reads_as_a_sentence(author, category):
    message = put_guide(author, category, timeRequiredMinMinutes=90, timeRequiredMaxMinutes=30)

    assert message == "The minimum time required must not exceed the maximum."


def test_an_overlong_title_names_the_field_and_the_limit(author, category):
    assert put_guide(author, category, title="x" * 241) == "Title: must be at most 240 characters."


def test_a_nested_field_is_located_the_way_an_author_counts(author, category):
    steps = [
        {"title": "One", "bullets": []},
        {"title": "Two", "bullets": [{"text": "a"}, {"text": "b"}, {"text": "x" * 4001}]},
    ]

    assert put_guide(author, category, steps=steps) == "Step 2, bullet 3, text: must be at most 4000 characters."


def test_a_field_with_an_awkward_wire_name_gets_a_proper_label(author, category):
    assert put_guide(author, category, timeRequiredMinMinutes=-5) == "Minimum time required: must be at least 0."


def test_a_choice_lists_what_is_allowed_without_repeating_what_was_sent(author, category):
    message = put_guide(author, category, difficulty="impossible-sentinel")

    assert message.startswith("Difficulty: must be 'very_easy', 'easy'")
    assert "impossible-sentinel" not in message


def test_several_problems_are_several_sentences(author, category):
    message = put_guide(author, category, title="x" * 241, summary="y" * 4001)

    assert message == "Title: must be at most 240 characters. Summary: must be at most 4000 characters."


def test_no_message_carries_pydantic_or_transport_vocabulary(author, category, admin):
    created = create_page(author)
    messages = [
        put_guide(author, category, timeRequiredMinMinutes=90, timeRequiredMaxMinutes=30),
        put_guide(author, category, tags=["t" * 61]),
        put_guide(author, category, steps="not a list"),
        message_of(author.put(f"/api/pages/{created['id']}", json={**document_from(created), "heroAlt": "a" * 1001})),
        message_of(admin.post("/api/categories", json={"name": ""})),
        message_of(admin.post("/api/users", json={"email": "not-an-address", "password": "irrelevant"})),
        message_of(author.post("/api/guides", json={})),
    ]

    for message in messages:
        for noise in ("Value error", "request:", "body", "Input should", "String should", "Field required"):
            assert noise not in message, message
        assert message.endswith(".")


def test_the_remaining_messages_read_as_expected(author, category, admin):
    created = create_page(author)

    assert put_guide(author, category, tags=["t" * 61]) == "Tag 1: must be at most 60 characters."
    assert put_guide(author, category, steps="not a list") == "Steps: must be a list."
    assert message_of(admin.post("/api/categories", json={"name": ""})) == "Name: must not be empty."
    assert (
        message_of(admin.post("/api/users", json={"email": "not-an-address", "password": "irrelevant"}))
        == "Email: must be a valid email address."
    )
    assert message_of(author.post("/api/guides", json={})) == "Title: is required. Category: is required."
    assert (
        message_of(author.put(f"/api/pages/{created['id']}", json={**document_from(created), "heroAlt": "a" * 1001}))
        == "Hero image description: must be at most 1000 characters."
    )


def test_the_concurrency_token_keeps_its_wire_name(author, category):
    """Only a client program can omit it, and its author needs the real name."""
    created = create_guide(author, category.id)
    body = document_from(created)
    del body["expectedUpdatedAt"]

    assert message_of(author.put(f"/api/guides/{created['id']}", json=body)) == "expectedUpdatedAt: is required."


def test_a_submitted_password_is_never_reflected(anon):
    response = anon.post("/api/auth/login", json={"email": "nobody", "password": "hunter2-sentinel"})

    assert "hunter2-sentinel" not in response.text
    assert message_of(response) == "Email: must be a valid email address."


def test_a_body_that_is_not_json_says_so(author):
    response = author.post("/api/guides", content=b"{not json", headers={"Content-Type": "application/json"})

    assert message_of(response).endswith("is not valid JSON.")


def test_the_describer_copes_with_shapes_it_has_no_rule_for():
    describe = errors.describe_validation

    assert describe([]) == "The request could not be understood."
    assert describe([{"type": "novel_kind", "loc": ("body", "orderIndex"), "msg": "Something odd"}]) == "Position: is not valid."
    assert describe([{"type": "novel_kind", "loc": ("query", "limit"), "msg": "Input should be a multiple of 5"}]) == (
        "Limit: must be a multiple of 5."
    )
    assert describe([{"type": "value_error", "loc": ("body",), "msg": "Value error, "}]) == "Is not valid."
    assert describe([{"type": "string_too_short", "loc": ("body", "displayName"), "ctx": {"min_length": 3}}]) == (
        "Display name: must be at least 3 characters."
    )
    assert describe([{"type": "too_long", "loc": ("body", "tags"), "ctx": {"max_length": 30}}]) == (
        "Tags: must have at most 30 items."
    )
    assert describe([{"type": "too_short", "loc": ("body", "steps"), "ctx": {"min_length": 1}}]) == (
        "Steps: must have at least 1 item."
    )
    assert describe([{"type": "greater_than", "loc": ("body", "x"), "ctx": {"gt": 0}}]) == "X: must be more than 0."
    assert describe([{"type": "missing", "loc": ("body", "parent_id")}]) == "Parent: is required."
    assert describe([{"type": "missing", "loc": ("body", "media", 0, "id")}]) == "Media 1, id: is required."
