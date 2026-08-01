"""Security behaviours that only appear under a specific misconfiguration or
edge case, and so are easy to leave untested until they matter."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import UtcDateTime
from app.main import app
from app.models import Session as SessionRow
from app.models import User
from app.settings import get_settings
from app.slugs import slugify

from .conftest import ApiClient


def test_a_spoofed_forwarded_header_is_ignored_by_default(client_factory, make_user):
    """Without a declared proxy, an attacker could otherwise mint a fresh
    rate-limit bucket per request by varying one header."""
    make_user("spoof@zmb.uzh.ch")
    client = client_factory("203.0.113.99")
    limit = get_settings().login_max_attempts_per_ip

    for index in range(limit):
        client.login(f"unknown-{index}@zmb.uzh.ch", "wrong")

    blocked = client.raw.post(
        "/api/auth/login",
        json={"email": "another@zmb.uzh.ch", "password": "wrong"},
        headers={"X-Forwarded-For": "198.51.100.200"},
    )
    assert blocked.status_code == 429


def test_a_forwarded_header_is_honoured_once_a_proxy_is_declared(monkeypatch, db_session, make_user):
    monkeypatch.setenv("RETICLE_TRUST_FORWARDED_FOR", "true")
    get_settings.cache_clear()
    make_user("proxied@zmb.uzh.ch")

    client = ApiClient(TestClient(app, client=("10.0.0.1", 5000)))
    client.raw.post(
        "/api/auth/login",
        json={"email": "proxied@zmb.uzh.ch", "password": "wrong"},
        headers={"X-Forwarded-For": "198.51.100.7, 10.0.0.1"},
    )

    from app.models import LoginAttempt

    recorded = db_session.scalars(select(LoginAttempt).where(LoginAttempt.scope == "ip")).all()
    assert [attempt.key for attempt in recorded] == ["198.51.100.7"]


def test_a_live_session_dies_the_moment_the_account_is_deactivated(author, db_session):
    """Deactivation through the API revokes sessions; this covers the account
    being switched off directly in the database, where nothing revoked them."""
    user = db_session.scalars(select(User).where(User.email == "author@zmb.uzh.ch")).one()
    user.is_active = False
    db_session.commit()

    response = author.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
    assert db_session.scalars(select(SessionRow)).one().revoked_at is None


def test_a_naive_datetime_cannot_reach_the_database():
    """Every stored instant is UTC. A naive value would be written as if it were
    UTC and read back as a wrong instant, silently corrupting the concurrency
    token."""
    from datetime import datetime

    with pytest.raises(ValueError, match="naive"):
        UtcDateTime().process_bind_param(datetime(2026, 7, 31, 12, 0, 0), None)


def test_a_title_with_no_latin_characters_still_yields_a_usable_slug():
    assert slugify("顕微鏡", fallback="guide") == "guide"
    assert slugify("   ", fallback="category") == "category"


def test_the_application_creates_its_schema_on_startup(db_session):
    """`uvicorn app.main:app` on a fresh checkout must not fail on the first
    query, so the lifespan creates whatever tables are missing."""
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}


def test_hardening_headers_are_present_on_every_response(anon):
    headers = anon.get("/api/health").headers

    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"


NEW_SURFACE = frozenset(
    {
        "/api/pages",
        "/api/pages/{key}",
        "/api/pages/{page_id}",
        "/api/pages/{page_id}/publish",
        "/api/pages/{page_id}/unpublish",
        "/api/pages/{page_id}/revisions",
        "/api/pages/{page_id}/revisions/{version}",
        "/api/categories/{category_id}/page",
        "/api/tags",
        "/api/search",
    }
)
"""Everything the wiki and discovery routers added.

Listed by hand rather than derived from the routers, because a list derived from
the thing under test agrees with it however wrong it is.
"""


def test_the_wiki_and_discovery_routes_are_inside_the_authentication_sweep():
    """``unauthenticated_routes() == []`` is only a guarantee about the routes
    the sweep can see.

    A router mounted outside the ``APIRoute`` tree, or one whose paths the sweep
    never reaches, would satisfy that assertion by being absent from it — so the
    endpoints added with pages, tags and search are named here and required to be
    both present and guarded.
    """
    from fastapi.routing import APIRoute

    from app.main import _all_routes, _dependant_requires_auth, unauthenticated_routes

    api_routes = [route for route in _all_routes() if isinstance(route, APIRoute)]
    guarded = {route.path for route in api_routes if _dependant_requires_auth(route.dependant)}

    assert NEW_SURFACE <= {route.path for route in api_routes}
    assert NEW_SURFACE <= guarded
    assert unauthenticated_routes() == []


def test_the_authentication_sweep_can_actually_see_an_unguarded_route():
    """The sweep's own regression test.

    An assertion that a list is empty is worthless if the list is empty because
    nothing was examined — and that is exactly what happened: an included router
    stopped being copied into ``app.routes`` and became a single pathless
    wrapper, so the sweep skipped every endpoint in the application and reported
    a clean bill of health for a router mounted with no authentication at all.
    Planting a hole and requiring the sweep to name it is the only assertion that
    distinguishes "no holes" from "no sight".
    """
    from fastapi import APIRouter

    from app.main import unauthenticated_routes

    hole = APIRouter(prefix="/api/deliberate-hole")

    @hole.get("")
    def wide_open() -> dict[str, str]:  # pragma: no cover - never called
        return {}

    original = list(app.routes)
    try:
        app.include_router(hole)
        assert unauthenticated_routes() == ["/api/deliberate-hole"]
    finally:
        app.router.routes[:] = original


def test_the_public_allow_list_is_still_only_the_probe_and_the_login():
    """The sweep measures against this set, so widening it is how a hole gets
    declared safe rather than fixed."""
    from app.main import PUBLIC_PATHS

    assert set(PUBLIC_PATHS) == {"/api/health", "/api/auth/login"}


def test_every_readable_endpoint_on_the_new_surface_refuses_an_anonymous_caller(anon):
    """The structural sweep proves a dependency is declared; this proves the
    dependency actually fires."""
    for path in (
        "/api/pages",
        "/api/pages/anything",
        "/api/pages/01JQNOTAREALULID00000000/revisions",
        "/api/pages/01JQNOTAREALULID00000000/revisions/1",
        "/api/categories/01JQNOTAREALULID00000000/page",
        "/api/tags",
        "/api/search?q=anything",
    ):
        response = anon.get(path)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "not_authenticated", path


def test_an_unmapped_http_error_still_uses_the_error_envelope(author):
    """FastAPI raises its own HTTPException for things like an unparseable path
    parameter; the client must never see a bare FastAPI body."""
    response = author.get("/api/guides/x/revisions/not-a-number")

    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert response.json()["error"]["code"] == "validation_failed"
