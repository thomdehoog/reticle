"""Small guarantees that sit between modules and are easy to lose in a refactor."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from starlette.requests import Request
from ulid import ULID

from app import audit, errors
from app.auth import client_address
from app.main import RequestSizeLimitMiddleware
from app.models import PageMedia, User
from app.security import hash_password
from app.settings import get_settings
from app.slugs import unique_slug

from .conftest import bullet, create_guide, create_page, document_from, save_page, step, upload_media


# ------------------------------------------------------- the size middleware


def run_middleware(application, body_chunks: list[bytes], limit: int = 10, path: str = "/api/x", method: str = "POST"):
    """Drive the raw ASGI middleware with a scripted request body."""
    sent: list[dict] = []
    pending = [
        {"type": "http.request", "body": chunk, "more_body": index < len(body_chunks) - 1}
        for index, chunk in enumerate(body_chunks)
    ]

    async def receive():
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": method, "path": path, "headers": [], "query_string": b""}
    middleware = RequestSizeLimitMiddleware(application, max_bytes=limit, max_upload_bytes=1000)
    asyncio.run(middleware(scope, receive, send))
    return sent


async def _drain(receive) -> list[dict]:
    messages = []
    while True:
        message = await receive()
        messages.append(message)
        if message["type"] == "http.disconnect" or not message.get("more_body"):
            return messages


def test_a_body_within_the_limit_passes_through_untouched():
    seen = []

    async def application(scope, receive, send):
        seen.extend(await _drain(receive))
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    sent = run_middleware(application, [b"12345", b"67890"])

    assert [message["body"] for message in seen] == [b"12345", b"67890"]
    assert [message["type"] for message in sent] == ["http.response.start", "http.response.body"]
    assert sent[0]["status"] == 204


def test_an_overrunning_body_is_cut_off_and_answered_with_413_whatever_the_app_says():
    """The application sees a disconnect — repeatedly, if it keeps asking — and
    whatever it tries to answer is replaced by the refusal."""
    seen = []

    async def application(scope, receive, send):
        seen.extend(await _drain(receive))
        seen.append(await receive())
        await send({"type": "http.response.start", "status": 400, "headers": []})
        await send({"type": "http.response.body", "body": b"could not parse"})

    sent = run_middleware(application, [b"12345", b"67890", b"X", b"never delivered"])

    assert [message["type"] for message in seen] == ["http.request", "http.request", "http.disconnect", "http.disconnect"]
    assert sent[0]["status"] == 413
    assert b"payload_too_large" in sent[1]["body"]
    assert len(sent) == 2


def test_an_app_that_crashes_on_the_cut_off_still_yields_413():
    async def application(scope, receive, send):
        await _drain(receive)
        raise RuntimeError("client went away mid-body")

    sent = run_middleware(application, [b"x" * 11])

    assert sent[0]["status"] == 413


def test_an_unrelated_crash_is_not_swallowed():
    async def application(scope, receive, send):
        await _drain(receive)
        raise RuntimeError("a genuine bug")

    with pytest.raises(RuntimeError, match="genuine bug"):
        run_middleware(application, [b"small"])


def test_a_response_already_under_way_is_left_alone_when_the_body_overruns():
    async def application(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await _drain(receive)
        await send({"type": "http.response.body", "body": b"partial"})
        raise RuntimeError("after the fact")

    with pytest.raises(RuntimeError, match="after the fact"):
        run_middleware(application, [b"x" * 11])


def test_only_the_upload_route_and_verb_get_the_larger_limit():
    middleware = RequestSizeLimitMiddleware(None, max_bytes=10, max_upload_bytes=1000)

    def limit(method: str, path: str) -> int:
        return middleware.limit_for({"method": method, "path": path})

    assert limit("POST", "/api/media") == 1000
    assert limit("POST", "/api/media/") == 1000
    assert limit("GET", "/api/media") == 10
    assert limit("PUT", "/api/media") == 10
    assert limit("POST", "/api/media/01ABC") == 10
    assert limit("POST", "/api/mediaX") == 10
    assert limit("POST", "/api/auth/login") == 10


def test_non_http_traffic_is_passed_straight_through():
    seen = []

    async def application(scope, receive, send):
        seen.append(scope["type"])

    middleware = RequestSizeLimitMiddleware(application, max_bytes=1, max_upload_bytes=1)
    asyncio.run(middleware({"type": "lifespan"}, None, None))

    assert seen == ["lifespan"]


# ------------------------------------------------------------ client address


def request_from(client: tuple[str, int] | None, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "client": client})


def test_a_connection_with_no_peer_address_has_no_client_address(monkeypatch):
    """A Unix-socket deployment reports no peer. The header is not believed
    then either: there is nothing to establish that a trusted proxy sent it."""
    monkeypatch.setenv("RETICLE_TRUSTED_PROXIES", "127.0.0.1")
    get_settings.cache_clear()
    try:
        assert client_address(request_from(None)) is None
        assert client_address(request_from(None, "198.51.100.7")) is None
    finally:
        get_settings.cache_clear()


def test_a_peer_that_is_not_an_address_is_never_a_trusted_proxy():
    assert client_address(request_from(("testclient", 1), "198.51.100.7")) == "testclient"


# ------------------------------------------------------------------ documents


def test_the_same_step_twice_in_one_document_is_rejected(author, category):
    created = create_guide(author, category.id)
    step_id = str(ULID())

    response = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(created, steps=[step("A", step_id=step_id), step("B", step_id=step_id)]),
    )

    assert response.status_code == 422


def test_the_same_bullet_twice_in_one_step_is_rejected(author, category):
    created = create_guide(author, category.id)
    bullet_id = str(ULID())

    response = author.put(
        f"/api/guides/{created['id']}",
        json=document_from(
            created, steps=[step("A", bullets=[bullet("x", bullet_id=bullet_id), bullet("y", bullet_id=bullet_id)])]
        ),
    )

    assert response.status_code == 422


def test_a_media_reference_that_survives_an_edit_is_kept_not_recreated(author, db_session):
    kept, dropped, added = upload_media(author), upload_media(author), upload_media(author)
    page = create_page(author)
    page = save_page(author, page, body=f"/api/media/{kept['id']} /api/media/{dropped['id']}")

    save_page(author, page, body=f"/api/media/{kept['id']} /api/media/{added['id']}")

    assert set(db_session.scalars(select(PageMedia.media_id))) == {kept["id"], added["id"]}


def test_a_third_duplicate_title_counts_on(author, category):
    assert [create_guide(author, category.id, "Same")["slug"] for _ in range(3)] == ["same", "same-2", "same-3"]
    assert unique_slug("Same", lambda candidate: candidate in {"same", "same-2", "same-3"}) == "same-4"


# ----------------------------------------------------------------- passwords


def test_a_hash_made_with_weaker_parameters_is_upgraded_at_the_next_login(anon, db_session, monkeypatch):
    """Raising the Argon2 cost in the configuration has to reach existing
    accounts, and the only moment the plaintext is available is a login."""
    monkeypatch.setenv("RETICLE_ARGON2_TIME_COST", "2")
    get_settings.cache_clear()
    db_session.add(User(email="old@zmb.uzh.ch", display_name="Old", role="viewer", password_hash=hash_password("Old-Passphrase-123")))
    db_session.commit()
    before = db_session.scalars(select(User)).one().password_hash
    monkeypatch.setenv("RETICLE_ARGON2_TIME_COST", "1")
    get_settings.cache_clear()

    assert anon.login("old@zmb.uzh.ch", "Old-Passphrase-123").status_code == 200

    db_session.expire_all()
    after = db_session.scalars(select(User)).one().password_hash
    assert after != before
    assert "t=1" in after and "t=2" in before
    assert anon.login("old@zmb.uzh.ch", "Old-Passphrase-123").status_code == 200


def test_a_corrupt_stored_hash_fails_closed(anon, db_session):
    from app.security import needs_rehash

    db_session.add(User(email="broken@zmb.uzh.ch", display_name="Broken", role="viewer", password_hash="not-a-hash"))
    db_session.commit()

    assert anon.login("broken@zmb.uzh.ch", "anything-at-all").status_code == 401
    assert needs_rehash("not-a-hash") is True


# --------------------------------------------------------------- vocabulary


def test_an_error_code_outside_the_contract_cannot_be_raised():
    with pytest.raises(ValueError, match="unknown error code"):
        errors.ApiError("teapot", "I am a teapot.")


def test_the_audit_trail_refuses_anything_that_looks_like_a_secret(db_session):
    with pytest.raises(ValueError, match="secret-bearing"):
        audit.record(db_session, action="user.update", entity_type="user", detail={"newPassword": "hunter2"})


def test_the_meta_line_of_a_pdf_copes_without_a_category_name(author, category):
    from app import pdf
    from app.schemas import GuideOut

    guide = GuideOut.model_validate(create_guide(author, category.id))

    assert pdf.meta_line(guide, "").startswith("Difficulty: Moderate")
