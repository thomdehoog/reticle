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


def test_a_forwarded_header_is_honoured_once_a_proxy_is_declared(
    monkeypatch, db_session, make_user
):
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


def test_an_enormous_body_is_refused_before_anything_reads_it(anon):
    """The allocation that matters is the endpoint reading the body in order to
    validate it, and on the login endpoint that is performed on behalf of a
    caller who has not authenticated and never will: a 210 MB login attempt was
    held in memory in full and only then rejected as invalid."""
    response = anon.raw.post(
        "/api/auth/login",
        json={"email": "flood@zmb.uzh.ch", "password": "x" * (3 * 1024 * 1024)},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert "MB" in response.json()["error"]["message"]


def test_the_size_limit_does_not_apply_to_a_multipart_upload(author):
    """Uploads legitimately run to tens of megabytes and ``media`` streams them
    against its own, larger cap rather than trusting the declared length; the
    blanket limit must not shadow it."""
    from .conftest import image_bytes

    response = author.post("/api/media", files={"file": ("x.png", image_bytes(), "image/png")})

    assert response.status_code == 201


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

    assert {route.path for route in api_routes} >= NEW_SURFACE
    assert guarded >= NEW_SURFACE
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


def test_the_public_allow_list_holds_only_what_has_been_argued_for():
    """The sweep measures against this set, so widening it is how a hole gets
    declared safe rather than fixed.

    Four entries, each with a reason that has to survive being read aloud.
    ``/api/health`` reveals liveness. The login endpoint cannot require a
    session it exists to create. And ``/api/config`` carries the name of the
    facility running the instance, which the login screen has to show before
    anybody has signed in and which the hostname pointing at the server already
    gives away.

    ``/api/ready`` is the newest and the one worth arguing hardest, because it
    is the only entry that discloses something operational: whether this
    instance can currently reach its database. It is here because the thing
    that reads it is a load balancer or an orchestrator, which has no session
    and cannot be given one — and a readiness probe behind a login is a
    readiness probe that reports "not ready" forever. The disclosure is bounded
    on purpose: a status word and nothing else, no error text, no driver
    message, no URL. **It should still be bound to an internal interface where
    the deployment allows it** — see ``DEPLOYMENT.md``.

    Anything else appearing here is a hole somebody decided not to fix.
    """
    from app.main import PUBLIC_PATHS

    assert set(PUBLIC_PATHS) == {
        "/api/health",
        "/api/ready",
        "/api/auth/login",
        "/api/config",
    }


def test_the_readiness_probe_discloses_a_status_word_and_nothing_else(anon):
    """It is unauthenticated, so what it returns is the whole of its risk.

    In particular it must never echo the exception: a driver error names the
    host, the database and sometimes the user.

    Both branches are exercised here because the interesting one is the
    negative. ``state.ready`` is set by the lifespan handler after migrations
    finish, so an instance that has not completed startup answers 503 — which
    is what stops a load balancer sending requests to a process whose schema is
    still being changed underneath it.
    """
    from app.main import app

    app.state.ready = False
    starting = anon.get("/api/ready")
    assert starting.status_code == 503
    assert starting.json() == {"status": "starting"}

    app.state.ready = True
    try:
        response = anon.get("/api/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}
    finally:
        app.state.ready = False


def test_the_readiness_probe_reports_a_lost_database_without_describing_it(anon, monkeypatch):
    """The failure path is the one that leaks, and it is never exercised by
    accident: a driver error message names the host, the database and often the
    user, and this endpoint needs no session to read."""
    from app.main import app
    from app.routers import system

    class Unreachable:
        def __enter__(self):
            raise RuntimeError(
                "connection to server at 'db.internal' (10.0.0.5), user 'reticle' failed"
            )

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(system, "SessionLocal", lambda: Unreachable())
    app.state.ready = True
    try:
        response = anon.get("/api/ready")
    finally:
        app.state.ready = False

    assert response.status_code == 503
    assert response.json() == {"status": "database_unavailable"}
    assert "db.internal" not in response.text
    assert "reticle" not in response.text


def test_the_public_config_endpoint_carries_nothing_but_the_name(anon):
    """It is the one unauthenticated endpoint that returns content, so what it
    returns is the whole of its risk."""
    body = anon.get("/api/config").json()

    assert set(body) == {"organisation"}
    assert set(body["organisation"]) == {"name", "shortName", "url"}


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
    # ``requestId`` accompanies ``error`` on every failure so a user can quote
    # it when reporting one. Nothing else may appear: FastAPI's own body has a
    # ``detail`` key that leaks the raw validation structure.
    assert set(response.json()) == {"error", "requestId"}
    assert set(response.json()["error"]) == {"code", "message"}
    assert response.json()["error"]["code"] == "validation_failed"


def test_an_unanticipated_failure_still_returns_the_documented_envelope(author):
    """The catch-all handler has to survive being reached.

    It builds its response with `ApiError`, which refuses a code it does not
    know - so a missing entry in the code table meant the handler raised while
    handling, and the caller got an empty 500 body with no request id. Every
    other error path is exercised by some test; this one is only reached when
    something has already gone unexpectedly wrong, which is exactly when nobody
    is watching.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    @app.get("/api/deliberate-explosion")
    def explode() -> dict[str, str]:  # pragma: no cover - raises before returning
        raise RuntimeError("the database caught fire")

    # raise_server_exceptions=False makes the client behave like a browser:
    # it reads the response the handler produced instead of re-raising the
    # exception, which is the only way to see what a real caller would get.
    original = list(app.router.routes)
    try:
        client = TestClient(app, raise_server_exceptions=False)
        client.cookies.update(author.raw.cookies)
        response = client.get("/api/deliberate-explosion")
    finally:
        app.router.routes[:] = original

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    # A real id, not the "-" a ContextVar reads back as when it was never set.
    # Starlette runs an `@app.exception_handler(Exception)` in the outermost
    # layer of all, outside the middleware that assigns the id and outside the
    # one that adds the headers - so a 500 built there is the one error a user
    # is most likely to report and the one they cannot quote an id for.
    assert response.json()["requestId"] not in (None, "", "-")
    assert response.headers["X-Request-ID"] == response.json()["requestId"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cross-Origin-Resource-Policy"] == "same-site"
    # The exception must not describe itself: the message could name a table, a
    # filesystem path, or echo submitted input.
    assert "database caught fire" not in response.text


# --- the order the middleware actually runs in -----------------------------


def test_a_refused_request_still_gets_an_id_a_log_line_and_the_headers(anon, monkeypatch):
    """`add_middleware` inserts at the front, so the last one added is the
    outermost - and getting that backwards is invisible until something is
    refused. Every 429 and 413 went out with no request id, no log line and no
    security headers, because the layers that add those sat inside the layers
    doing the refusing.

    A 429 nobody can correlate is indistinguishable from an outage.
    """
    from app.main import app
    from app.ratelimit import RateLimitMiddleware, SlidingWindow

    limiters = []
    stack, seen = [app.middleware_stack], set()
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, RateLimitMiddleware):
            limiters.append(current)
        for attribute in ("app", "next", "_app"):
            stack.append(getattr(current, attribute, None))
    assert limiters

    for limiter in limiters:
        monkeypatch.setattr(limiter.settings, "rate_limit_enabled", True, raising=False)
        monkeypatch.setattr(limiter.settings, "rate_limit_reads_per_minute", 1, raising=False)
        limiter.window = SlidingWindow()

    anon.get("/api/health")  # exempt, so it does not spend the allowance
    anon.get("/api/config")
    refused = anon.get("/api/config")

    assert refused.status_code == 429
    assert refused.headers["X-Request-ID"] not in (None, "", "-")
    assert refused.json()["requestId"] == refused.headers["X-Request-ID"]
    assert refused.headers["X-Content-Type-Options"] == "nosniff"
    assert refused.headers["X-Frame-Options"] == "DENY"


def test_an_oversized_body_is_refused_however_it_is_declared(anon):
    """Two escapes were open, both unauthenticated, both against the login
    endpoint - which reads its whole body before it can tell it is not JSON.

    Claiming to be a file upload used to skip the check entirely, and sending
    no Content-Length at all meant there was no claim to check.
    """
    from app.settings import get_settings

    cap = get_settings().max_request_bytes
    oversized = b"x" * (cap + 100_000)

    declared = anon.raw.post(
        "/api/auth/login", content=oversized, headers={"Content-Type": "application/json"}
    )
    assert declared.status_code == 413

    pretending_to_be_an_upload = anon.raw.post(
        "/api/auth/login",
        content=oversized,
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )
    assert pretending_to_be_an_upload.status_code == 413

    def chunks():
        yield oversized

    undeclared = anon.raw.post(
        "/api/auth/login", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert undeclared.status_code != 200


def test_only_the_upload_route_gets_the_upload_cap(anon):
    """The larger cap belongs to the route, not to a header the caller writes.

    Keyed on the content type, any endpoint takes the 205 MB ceiling by
    claiming to be an upload — including the login endpoint, which buffers its
    whole body before it can tell it is not JSON and which is exempt from both
    the rate limiter and CSRF.
    """
    from app.main import RequestSizeLimitMiddleware

    middleware = RequestSizeLimitMiddleware(app=None, max_bytes=1000, upload_max_bytes=999_000)
    multipart = [(b"content-type", b"multipart/form-data; boundary=x")]

    assert (
        middleware._cap_for({"path": "/api/auth/login", "method": "POST", "headers": multipart})
        == 1000
    )
    assert middleware._cap_for({"path": "/api/media", "method": "POST", "headers": []}) == 999_000
    # Reading a file is not uploading one.
    assert middleware._cap_for({"path": "/api/media/01ABC", "method": "GET", "headers": []}) == 1000


def test_a_refused_body_says_a_size_a_person_can_act_on(anon, monkeypatch):
    """Whole megabytes render a sub-megabyte cap as "0 MB", which reads as a
    server that accepts nothing at all."""
    from app.main import _size_words

    assert _size_words(2 * 1024 * 1024) == "2 MB"
    assert _size_words(64 * 1024) == "64 KB"
    assert _size_words(900) == "900 bytes"


def test_a_413_carries_a_request_id_like_every_other_error(anon):
    """It is issued by middleware rather than by a handler, which is how it
    became the one error in the API with no id to quote."""
    from app.settings import get_settings

    oversized = b"x" * (get_settings().max_request_bytes + 100_000)
    refused = anon.raw.post(
        "/api/auth/login", content=oversized, headers={"Content-Type": "application/json"}
    )

    assert refused.status_code == 413
    assert set(refused.json()) == {"error", "requestId"}
    assert refused.json()["requestId"] not in (None, "", "-")
    assert refused.headers["X-Request-ID"] == refused.json()["requestId"]


# --- attribution behind a proxy --------------------------------------------


def test_no_warning_when_the_proxy_has_already_rewritten_the_peer_address(monkeypatch, caplog):
    """The shipped multi-facility unit runs uvicorn with ``--proxy-headers
    --forwarded-allow-ips 127.0.0.1``, so the peer address *is* the real client
    by the time any of this code runs and attribution is already correct.

    Warning there fires forever and tells the operator to set
    ``RETICLE_TRUST_FORWARDED_FOR``, which combined with a proxy that appends
    rather than overwrites lets a client choose the address the login throttle
    counts against.
    """
    import logging

    from app import auth

    monkeypatch.setattr(auth, "_untrusted_forwarding_warned", False)
    request = _request_from("198.51.100.7", forwarded="198.51.100.7")

    with caplog.at_level(logging.WARNING, logger="app.auth"):
        assert auth.client_address(request) == "198.51.100.7"

    assert caplog.records == []


def test_a_warning_when_every_caller_really_is_being_attributed_to_the_proxy(monkeypatch, caplog):
    """The misconfiguration that looks like nothing: twenty mistyped passwords
    from anywhere in the institute lock everybody out at once."""
    import logging

    from app import auth

    monkeypatch.setattr(auth, "_untrusted_forwarding_warned", False)
    request = _request_from("10.0.0.1", forwarded="198.51.100.7")

    with caplog.at_level(logging.WARNING, logger="app.auth"):
        assert auth.client_address(request) == "10.0.0.1"

    assert len(caplog.records) == 1
    assert "10.0.0.1" in caplog.records[0].getMessage()


def _request_from(peer: str, forwarded: str | None = None):
    """The smallest thing ``auth.client_address`` reads: a peer and a header."""
    from starlette.requests import Request

    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "headers": headers, "client": (peer, 50000)})


def test_no_warning_for_a_forwarded_header_that_is_not_an_address(monkeypatch, caplog):
    """A header holding junk is evidence of a caller inventing one, not of a
    proxy nobody configured — and ``parse_ip_address`` has already dropped it,
    so nothing is being attributed anywhere it should not be."""
    import logging

    from app import auth

    monkeypatch.setattr(auth, "_untrusted_forwarding_warned", False)
    request = _request_from("10.0.0.1", forwarded="not-an-address")

    with caplog.at_level(logging.WARNING, logger="app.auth"):
        assert auth.client_address(request) == "10.0.0.1"

    assert caplog.records == []


def test_the_warning_points_at_uvicorn_rather_than_the_setting(monkeypatch, caplog):
    """``RETICLE_TRUST_FORWARDED_FOR`` makes Reticle read the first entry of the
    header itself.

    Behind a proxy that appends rather than overwrites, that entry is one the
    caller wrote — so the setting hands a client its own login-throttle bucket,
    and a garbage value yields no address at all, which drops the tight
    per-(email, address) limit and disables the per-address one. Telling an
    operator to reach for it first is advice that makes the deployment worse.
    """
    import logging

    from app import auth

    monkeypatch.setattr(auth, "_untrusted_forwarding_warned", False)

    with caplog.at_level(logging.WARNING, logger="app.auth"):
        auth.client_address(_request_from("10.0.0.1", forwarded="198.51.100.7"))

    message = caplog.records[0].getMessage()
    assert "--forwarded-allow-ips" in message
    assert message.index("--forwarded-allow-ips") < message.index("RETICLE_TRUST_FORWARDED_FOR")
