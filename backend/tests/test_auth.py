"""Authentication, session handling, CSRF and login throttling."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Session as SessionRow
from app.models import User
from app.settings import get_settings

from .conftest import TEST_PASSWORD


def test_health_needs_no_session(anon):
    response = anon.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_reveals_nothing_beyond_liveness(anon):
    assert set(anon.get("/api/health").json()) == {"status"}


def test_login_returns_the_user_and_sets_both_cookies(anon, make_user):
    make_user("thom.dehoog@zmb.uzh.ch", role="author", display_name="Thom de Hoog")

    response = anon.login("thom.dehoog@zmb.uzh.ch")

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "thom.dehoog@zmb.uzh.ch"
    assert body["displayName"] == "Thom de Hoog"
    assert body["role"] == "author"
    assert body["createdAt"].endswith("Z")
    assert "password" not in body and "passwordHash" not in body
    assert anon.cookies.get("reticle_session")
    assert anon.cookies.get("reticle_csrf")


def test_login_is_case_insensitive_on_the_email(anon, make_user):
    make_user("mixed.case@zmb.uzh.ch", role="viewer")

    assert anon.login("Mixed.Case@ZMB.uzh.ch").status_code == 200


def test_session_cookie_is_httponly_lax_and_not_secure_in_dev(anon, make_user):
    make_user("flags@zmb.uzh.ch")

    response = anon.login("flags@zmb.uzh.ch")

    session_cookie = next(h for h in response.headers.get_list("set-cookie") if h.startswith("reticle_session="))
    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie.replace("SameSite=Lax", "SameSite=lax")
    assert "Path=/" in session_cookie
    assert "Secure" not in session_cookie

    csrf_cookie = next(h for h in response.headers.get_list("set-cookie") if h.startswith("reticle_csrf="))
    assert "HttpOnly" not in csrf_cookie


def test_secure_flag_is_emitted_when_configured(monkeypatch, client_factory, make_user):
    make_user("secure@zmb.uzh.ch")
    monkeypatch.setenv("RETICLE_COOKIE_SECURE", "true")
    get_settings.cache_clear()

    response = client_factory().login("secure@zmb.uzh.ch")

    assert response.status_code == 200
    assert all("Secure" in h for h in response.headers.get_list("set-cookie"))


def test_password_is_stored_as_an_argon2id_hash(db_session, make_user):
    user = make_user("hashed@zmb.uzh.ch")

    assert user.password_hash.startswith("$argon2id$")
    assert TEST_PASSWORD not in user.password_hash


def test_session_token_is_not_stored_verbatim(anon, db_session, make_user):
    make_user("opaque@zmb.uzh.ch")
    anon.login("opaque@zmb.uzh.ch")

    presented = anon.cookies.get("reticle_session")
    stored = db_session.scalars(select(SessionRow)).one()

    assert stored.token_hash != presented
    assert presented not in stored.token_hash
    assert len(stored.token_hash) == 64


def test_unknown_email_and_wrong_password_are_indistinguishable(anon, client_factory, make_user):
    make_user("real@zmb.uzh.ch")

    wrong_password = anon.login("real@zmb.uzh.ch", "not-the-password")
    unknown_email = client_factory("10.0.0.9").login("ghost@zmb.uzh.ch", "not-the-password")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert wrong_password.json()["error"]["code"] == "invalid_credentials"


def test_failed_login_sets_no_cookies(anon, make_user):
    make_user("nocookie@zmb.uzh.ch")

    anon.login("nocookie@zmb.uzh.ch", "wrong")

    assert anon.cookies.get("reticle_session") is None


def test_deactivated_user_cannot_log_in(anon, make_user):
    make_user("retired@zmb.uzh.ch", is_active=False)

    response = anon.login("retired@zmb.uzh.ch")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_me_requires_a_session(anon):
    response = anon.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_me_returns_the_logged_in_user(author):
    body = author.get("/api/auth/me").json()

    assert body["email"] == "author@zmb.uzh.ch"
    assert body["role"] == "author"


def test_a_forged_session_cookie_is_rejected(anon):
    anon.raw.cookies.set("reticle_session", "obviously-not-a-real-token")

    assert anon.get("/api/auth/me").status_code == 401


def test_logout_revokes_the_session_server_side(author, db_session):
    stolen = author.cookies.get("reticle_session")
    csrf = author.cookies.get("reticle_csrf")

    assert author.post("/api/auth/logout").status_code == 204

    author.raw.cookies.set("reticle_session", stolen)
    author.raw.cookies.set("reticle_csrf", csrf)
    assert author.get("/api/auth/me").status_code == 401

    row = db_session.scalars(select(SessionRow)).one()
    assert row.revoked_at is not None


def test_expired_session_is_rejected(author, db_session):
    from datetime import datetime, timedelta, timezone

    row = db_session.scalars(select(SessionRow)).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()

    assert author.get("/api/auth/me").status_code == 401


def test_mutating_request_without_the_csrf_header_is_rejected(author, category):
    response = author.raw.post("/api/guides", json={"title": "No token", "categoryId": category.id})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert "csrf" in response.json()["error"]["message"].lower()


def test_mutating_request_with_a_mismatched_csrf_header_is_rejected(author, category):
    response = author.raw.post(
        "/api/guides",
        json={"title": "Wrong token", "categoryId": category.id},
        headers={"X-CSRF-Token": "a-different-value"},
    )

    assert response.status_code == 403


def test_csrf_cookie_planted_by_an_attacker_does_not_match_the_session(author, category):
    """Plain double-submit falls to a cookie-injection attacker; the token is
    also bound to the server-side session, so a self-consistent forgery fails."""
    author.raw.cookies.set("reticle_csrf", "attacker-chosen-value")

    response = author.raw.post(
        "/api/guides",
        json={"title": "Injected", "categoryId": category.id},
        headers={"X-CSRF-Token": "attacker-chosen-value"},
    )

    assert response.status_code == 403


def test_safe_requests_do_not_need_the_csrf_header(author):
    assert author.raw.get("/api/auth/me").status_code == 200


@pytest.mark.parametrize("method,path", [("POST", "/api/guides"), ("PATCH", "/api/users/x"), ("DELETE", "/api/guides/x")])
def test_csrf_applies_to_every_mutating_verb(author, method, path):
    assert author.raw.request(method, path, json={}).status_code == 403


def test_login_is_throttled_per_account_and_address(anon, make_user):
    make_user("target@zmb.uzh.ch")
    limit = get_settings().login_max_attempts_per_email_and_ip

    for _ in range(limit):
        assert anon.login("target@zmb.uzh.ch", "wrong").status_code == 401

    blocked = anon.login("target@zmb.uzh.ch", "wrong")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"


def test_a_guessed_at_account_can_still_sign_in_from_its_own_machine(client_factory, make_user):
    """The tripwire follows the guesser, not the account.

    Counting wrong guesses against the account alone means the counter the owner
    is measured by is the one an attacker fills. Five requests would lock out a
    named colleague whose address is on the ZMB website, and one request every
    three minutes would keep them out — while Reticle holds the instrument
    safety procedures they need to reach.
    """
    make_user("target@zmb.uzh.ch")

    attacker = client_factory("198.51.100.7")
    for _ in range(get_settings().login_max_attempts_per_email_and_ip):
        attacker.login("target@zmb.uzh.ch", "wrong")
    assert attacker.login("target@zmb.uzh.ch", TEST_PASSWORD).status_code == 429

    owner = client_factory("192.0.2.50")
    assert owner.login("target@zmb.uzh.ch", TEST_PASSWORD).status_code == 200


def test_a_distributed_guess_at_one_account_still_hits_the_ceiling(client_factory, make_user):
    """Spreading the guess across addresses evades the tripwire, so a much
    larger per-account ceiling stays behind it as a backstop."""
    make_user("target@zmb.uzh.ch")

    for index in range(get_settings().login_max_attempts_per_email):
        client_factory(f"203.0.113.{index % 250 + 1}").login("target@zmb.uzh.ch", "wrong")

    fresh = client_factory("198.51.100.200")
    assert fresh.login("target@zmb.uzh.ch", TEST_PASSWORD).status_code == 429


def test_login_is_throttled_per_source_address(client_factory, make_user):
    """Spraying many accounts from one host is the attack the email counter misses."""
    client = client_factory("203.0.113.4")
    for index in range(get_settings().login_max_attempts_per_ip):
        assert client.login(f"spray-{index}@zmb.uzh.ch", "wrong").status_code == 401

    assert client.login("spray-final@zmb.uzh.ch", "wrong").status_code == 429


def test_a_successful_login_clears_that_account_s_failures(anon, make_user):
    make_user("recovers@zmb.uzh.ch")
    limit = get_settings().login_max_attempts_per_email_and_ip
    for _ in range(limit - 1):
        anon.login("recovers@zmb.uzh.ch", "wrong")

    assert anon.login("recovers@zmb.uzh.ch", TEST_PASSWORD).status_code == 200

    for _ in range(limit - 1):
        assert anon.login("recovers@zmb.uzh.ch", "wrong").status_code == 401


def test_throttling_does_not_leak_account_existence(client_factory, make_user):
    make_user("exists@zmb.uzh.ch")
    limit = get_settings().login_max_attempts_per_email

    known = client_factory("192.0.2.1")
    unknown = client_factory("192.0.2.2")
    for _ in range(limit):
        known.login("exists@zmb.uzh.ch", "wrong")
        unknown.login("absent@zmb.uzh.ch", "wrong")

    assert known.login("exists@zmb.uzh.ch", "wrong").json() == unknown.login("absent@zmb.uzh.ch", "wrong").json()


def test_login_rejects_a_malformed_email(anon):
    response = anon.post("/api/auth/login", json={"email": "not-an-email", "password": "x"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_unknown_path_under_api_returns_the_error_envelope(author):
    response = author.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_every_route_is_behind_authentication():
    """A route added without an auth dependency is a silent hole; assert it can
    never happen rather than trusting review to catch it.

    The sweep covers every route rather than those under ``/api``, and owns its
    own allow-list. The earlier version did neither, and so could not see that
    ``/docs``, ``/redoc`` and ``/openapi.json`` were publishing the whole route
    inventory to anyone who asked.
    """
    from app.main import unauthenticated_routes

    assert unauthenticated_routes() == []
