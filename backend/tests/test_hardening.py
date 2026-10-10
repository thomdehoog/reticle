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


def _recorded_sources(db_session) -> list[str]:
    from app.models import LoginAttempt

    return [attempt.key for attempt in db_session.scalars(select(LoginAttempt).where(LoginAttempt.scope == "ip"))]


def _failed_login(client: ApiClient, forwarded: str | list[str] | None = None, email: str = "proxied@zmb.uzh.ch"):
    headers = [("X-Forwarded-For", value) for value in ([forwarded] if isinstance(forwarded, str) else forwarded or [])]
    return client.raw.post("/api/auth/login", json={"email": email, "password": "wrong"}, headers=headers)


@pytest.fixture()
def behind_proxy(monkeypatch, db_session):
    """Reticle told that 10.0.0.1 and the 192.168.7.0/24 block are its proxies."""
    monkeypatch.setenv("RETICLE_TRUSTED_PROXIES", "10.0.0.1, 192.168.7.0/24")
    get_settings.cache_clear()
    return lambda host="10.0.0.1": ApiClient(TestClient(app, client=(host, 5000)))


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


def test_the_header_is_believed_only_from_a_listed_proxy(behind_proxy, db_session):
    """Naming the proxy is what makes the header evidence. The same header from
    any other peer is just something a client typed."""
    _failed_login(behind_proxy("10.0.0.1"), "198.51.100.7")
    _failed_login(behind_proxy("192.168.7.40"), "198.51.100.8")
    _failed_login(behind_proxy("203.0.113.50"), "198.51.100.9")

    assert _recorded_sources(db_session) == ["198.51.100.7", "198.51.100.8", "203.0.113.50"]


def test_an_appending_proxy_cannot_be_fooled_by_a_client_supplied_prefix(behind_proxy, db_session):
    """nginx's default is to *append* the address it saw. The caller's real
    address is then the rightmost entry, and everything to its left is whatever
    the caller sent — including, if they like, a colleague's address to spend
    that colleague's login allowance."""
    _failed_login(behind_proxy(), "192.0.2.77, 198.51.100.7")

    assert _recorded_sources(db_session) == ["198.51.100.7"]


def test_a_chain_of_trusted_proxies_is_walked_back_to_the_first_stranger(behind_proxy, db_session):
    _failed_login(behind_proxy(), "192.0.2.1, 198.51.100.7, 192.168.7.9, 10.0.0.1")
    _failed_login(behind_proxy(), ["192.0.2.1", "198.51.100.8, 192.168.7.9"])

    assert _recorded_sources(db_session) == ["198.51.100.7", "198.51.100.8"]


def test_a_header_naming_only_proxies_or_nothing_usable_falls_back_to_the_peer(behind_proxy, db_session):
    _failed_login(behind_proxy(), "192.168.7.9, 10.0.0.1")
    _failed_login(behind_proxy(), "198.51.100.7, <script>alert(1)</script>")
    _failed_login(behind_proxy(), "x" * 2000)
    _failed_login(behind_proxy(), None)

    assert _recorded_sources(db_session) == ["10.0.0.1"] * 4


def test_an_ipv6_proxy_and_client_are_handled(monkeypatch, db_session):
    monkeypatch.setenv("RETICLE_TRUSTED_PROXIES", '["::1", "fd00::/8"]')
    get_settings.cache_clear()

    _failed_login(ApiClient(TestClient(app, client=("::1", 5000))), "2001:db8:1:2:aaaa:bbbb:cccc:dddd, fd00::5")

    assert _recorded_sources(db_session) == ["2001:db8:1:2::/64"]


def test_a_forwarded_address_reaches_the_audit_trail_and_the_session(behind_proxy, make_user, db_session):
    from app.models import AuditLog

    make_user("proxied@zmb.uzh.ch")
    client = behind_proxy()
    response = client.raw.post(
        "/api/auth/login",
        json={"email": "proxied@zmb.uzh.ch", "password": "Reticle-Test-Passphrase-9"},
        headers={"X-Forwarded-For": "198.51.100.7"},
    )

    assert response.status_code == 200
    assert db_session.scalars(select(SessionRow)).one().ip_address == "198.51.100.7"
    assert db_session.scalars(select(AuditLog).where(AuditLog.action == "auth.login")).one().ip_address == "198.51.100.7"


def test_an_unlisted_local_proxy_is_called_out_once_in_the_log(client_factory, caplog, monkeypatch):
    """Behind a proxy Reticle has not been told about, every caller looks like
    the proxy and the per-source limit covers the whole institute at once. The
    one thing that can be done about a silent misconfiguration is to say so."""
    from app import auth

    monkeypatch.setattr(auth, "_untrusted_forwarding_warned", False)
    local = client_factory("127.0.0.1")

    with caplog.at_level("WARNING", logger="app.auth"):
        _failed_login(local, "198.51.100.7")
        _failed_login(local, "198.51.100.8")
        _failed_login(client_factory("203.0.113.5"), "198.51.100.9")

    warnings = [record for record in caplog.records if "RETICLE_TRUSTED_PROXIES" in record.getMessage()]
    assert len(warnings) == 1
    assert "127.0.0.1" in warnings[0].getMessage()


def test_the_old_on_off_switch_refuses_to_start_rather_than_be_misread(monkeypatch):
    """``RETICLE_TRUST_FORWARDED_FOR=true`` used to mean "believe the header
    from anyone". Ignoring it silently would leave an upgraded deployment
    attributing everybody to its proxy; honouring it would keep the hole."""
    from pydantic import ValidationError

    from app.settings import Settings

    monkeypatch.setenv("RETICLE_TRUST_FORWARDED_FOR", "true")
    with pytest.raises(ValidationError, match="RETICLE_TRUSTED_PROXIES"):
        Settings(_env_file=None)

    monkeypatch.setenv("RETICLE_TRUSTED_PROXIES", "127.0.0.1")
    assert Settings(_env_file=None).trusted_proxies == ["127.0.0.1"]


def test_a_mistyped_proxy_entry_refuses_to_start(monkeypatch):
    from pydantic import ValidationError

    from app.settings import Settings

    monkeypatch.setenv("RETICLE_TRUSTED_PROXIES", "127.0.0.1, nginx")
    with pytest.raises(ValidationError, match="nginx"):
        Settings(_env_file=None)


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


def test_slugs_transliterate_the_way_a_german_reader_would_spell_them():
    assert slugify("Präparation der Probe") == "praeparation-der-probe"
    assert slugify("Übersicht: Maßstab & Größe") == "uebersicht-massstab-groesse"
    assert slugify("Café crème, señor") == "cafe-creme-senor"
    assert slugify("Pra\u0308paration") == "praeparation"


def test_a_truncated_slug_does_not_end_in_a_hyphen():
    assert slugify("a" * 199 + " b") == "a" * 199


def test_hardening_headers_are_present_on_every_response(anon, author):
    for response in (anon.get("/api/health"), anon.get("/api/auth/me"), author.get("/api/guides"), author.get("/api/nope")):
        headers = response.headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        assert headers["cross-origin-resource-policy"] == "same-site"
        assert headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
        assert headers["cache-control"] == "no-store"


def test_authenticated_json_is_never_cached_and_media_only_to_be_asked_about_again(author):
    """A shared instrument PC's back button must not show the last user's
    drafts. An image may be kept by the browser that fetched it, but not used
    again without asking: ``max-age`` let it be shown from the disk cache after
    its reader had signed out."""
    from .conftest import upload_media

    image = upload_media(author)

    assert author.get("/api/auth/me").headers["cache-control"] == "no-store"
    assert author.get(f"/api/media/{image['id']}").headers["cache-control"] == "private, no-cache"


def test_hsts_is_sent_exactly_when_the_deployment_is_https_only(anon, monkeypatch):
    assert "strict-transport-security" not in anon.get("/api/health").headers

    monkeypatch.setenv("RETICLE_COOKIE_SECURE", "true")
    get_settings.cache_clear()

    assert anon.get("/api/health").headers["strict-transport-security"] == "max-age=31536000"


# ------------------------------------------------------ generated API docs


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"])
def test_the_generated_documentation_is_not_served(anon, author, path):
    """FastAPI mounts these outside the router tree, so no auth dependency ever
    touches them: left on, they hand the full route and schema inventory to
    anybody who asks. They are off for signed-in users too — a deployed
    instance has no use for them."""
    assert anon.get(path).status_code == 404
    assert author.get(path).status_code == 404


def test_documentation_is_only_ever_mounted_in_debug_mode(monkeypatch):
    from app.main import create_app
    from app.settings import Settings

    assert Settings(_env_file=None).debug is False

    from app.main import inspected_routes, unauthenticated_routes

    def documented(application) -> set[str]:
        return set(inspected_routes(application)) & {"/docs", "/redoc", "/openapi.json"}

    assert documented(create_app()) == set()

    monkeypatch.setenv("RETICLE_DEBUG", "true")
    get_settings.cache_clear()
    debugging = create_app()
    assert documented(debugging) == {"/docs", "/redoc", "/openapi.json"}
    assert {"/docs", "/redoc", "/openapi.json"} <= set(unauthenticated_routes(debugging))


# ------------------------------------------------------------ body ceilings


def test_an_oversized_json_body_is_refused_from_its_declared_length(anon, monkeypatch):
    """Before login, so on behalf of nobody: the body must not even be read."""
    from starlette.requests import Request

    read = []
    original = Request.body
    monkeypatch.setattr(Request, "body", lambda self: read.append(1) or original(self))
    limit = get_settings().max_request_bytes

    response = anon.raw.post(
        "/api/auth/login",
        content=b'{"email":"a@zmb.uzh.ch","password":"' + b"x" * limit + b'"}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert "2 MB" in response.json()["error"]["message"]
    assert read == []


def test_a_chunked_body_with_no_declared_length_is_cut_off_as_it_arrives(anon):
    """``Transfer-Encoding: chunked`` declares nothing, so a check on
    ``Content-Length`` alone waves it through."""
    limit = get_settings().max_request_bytes
    sent = []

    def stream():
        yield b'{"email":"a@zmb.uzh.ch","password":"'
        for _ in range(limit // 65536 + 8):
            sent.append(1)
            yield b"x" * 65536
        yield b'"}'

    response = anon.raw.post("/api/auth/login", content=stream(), headers={"Content-Type": "application/json"})

    assert "content-length" not in {key.lower() for key in response.request.headers}
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_calling_a_request_multipart_does_not_buy_the_upload_allowance(anon, author, category):
    """The large limit belongs to the upload route. It used to be enough to
    *label* a request multipart to be exempt everywhere, login included."""
    oversized = b"x" * (get_settings().max_request_bytes + 1)

    for client, path in ((anon, "/api/auth/login"), (author, "/api/guides"), (author, "/api/media/extra")):
        response = client.post(path, content=oversized, headers={"Content-Type": "multipart/form-data; boundary=x"})
        assert response.status_code == 413, path


def test_the_upload_route_has_its_own_ceiling_declared_and_streamed(author, monkeypatch):
    monkeypatch.setenv("RETICLE_MAX_UPLOAD_BYTES", "1024")
    monkeypatch.setenv("RETICLE_MAX_VIDEO_BYTES", "4096")
    get_settings.cache_clear()
    from app.main import MULTIPART_HEADROOM_BYTES, create_app

    application = create_app()
    client = ApiClient(TestClient(application))
    client.raw.cookies.update(author.raw.cookies)
    application.dependency_overrides = app.dependency_overrides
    too_much = b"x" * (4096 + MULTIPART_HEADROOM_BYTES + 1)

    declared = client.post("/api/media", content=too_much, headers={"Content-Type": "multipart/form-data; boundary=x"})
    streamed = client.post(
        "/api/media",
        content=(too_much[index : index + 65536] for index in range(0, len(too_much), 65536)),
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )
    trailing_slash = client.post("/api/media/", files={"file": ("a.bin", b"y" * (3 * 1024 * 1024), "x/y")})

    assert declared.status_code == 413
    assert streamed.status_code == 413
    assert streamed.json()["error"]["code"] == "payload_too_large"
    assert trailing_slash.status_code == 413


def test_ordinary_requests_fit_comfortably_under_the_ceiling(author, category):
    from .conftest import bullet, create_guide, save_guide, step

    created = create_guide(author, category.id)

    saved = save_guide(
        author,
        created,
        steps=[step(f"Step {index}", bullets=[bullet("A sentence of instruction. " * 10)] * 20) for index in range(60)],
    )

    assert len(saved["steps"]) == 60


# --------------------------------------------------------------------- CORS


def test_a_wildcard_origin_is_refused_at_start_up(monkeypatch):
    """With cookies and ``Allow-Credentials``, ``*`` makes the server echo back
    whichever origin asks: any page a signed-in colleague visits could then
    read every guide."""
    from pydantic import ValidationError

    from app.settings import Settings

    for value in ("*", "https://guides.zmb.uzh.ch, *", '["*"]'):
        monkeypatch.setenv("RETICLE_CORS_ORIGINS", value)
        with pytest.raises(ValidationError, match="must not contain"):
            Settings(_env_file=None)


def test_only_listed_origins_are_granted_credentialed_access(author):
    listed = author.get("/api/auth/me", headers={"Origin": "http://localhost:5173"})
    stranger = author.get("/api/auth/me", headers={"Origin": "https://evil.example"})
    preflight = author.raw.options(
        "/api/guides",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )

    assert listed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert listed.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in stranger.headers
    assert "access-control-allow-origin" not in preflight.headers
    assert preflight.status_code == 400


def test_an_unmapped_http_error_still_uses_the_error_envelope(author):
    """FastAPI raises its own HTTPException for things like an unparseable path
    parameter; the client must never see a bare FastAPI body."""
    response = author.get("/api/guides/x/revisions/not-a-number")

    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert response.json()["error"]["code"] == "validation_failed"


# ------------------------------------------------- failures nobody planned for


@pytest.fixture()
def tolerant(make_user):
    """A signed-in author whose client reports a server error instead of raising it."""
    make_user("tolerant@zmb.uzh.ch", role="author")
    client = ApiClient(TestClient(app, raise_server_exceptions=False))
    assert client.login("tolerant@zmb.uzh.ch").status_code == 200
    return client


def test_an_unexpected_exception_answers_in_the_error_envelope_and_says_nothing(tolerant, monkeypatch, caplog):
    """Whatever went wrong, the caller gets the contract's shape and a message
    that describes nothing of the server — and the log line names the route
    and the kind of failure without a byte of what was submitted."""
    from app import content

    def explode(*args, **kwargs):
        raise RuntimeError("column 'password_hash' of row 7: hunter2")

    monkeypatch.setattr(content, "read", explode)

    with caplog.at_level("ERROR", logger="app.main"):
        response = tolerant.get("/api/guides/anything?secret-in-the-query=topsecret")

    assert response.status_code == 500
    body = response.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == "internal_error"
    assert "hunter2" not in response.text and "password_hash" not in response.text and "RuntimeError" not in response.text
    assert response.headers["cache-control"] == "no-store"
    record = next(entry for entry in caplog.records if entry.name == "app.main")
    assert record.getMessage() == "Unhandled RuntimeError on GET /api/guides/anything"
    assert "topsecret" not in record.getMessage()
    assert record.exc_info is not None, "the traceback is kept for whoever has to fix it"


def test_an_unexpected_failure_while_saving_does_not_log_the_document(tolerant, category, monkeypatch, caplog):
    from app.routers import guides as guides_router

    from .conftest import bullet, create_guide, document_from, step

    created = create_guide(tolerant, category.id)

    def explode(*args, **kwargs):
        raise ZeroDivisionError

    monkeypatch.setattr(guides_router, "apply_document", explode)
    document = document_from(created, steps=[step("One", bullets=[bullet("The door code is 4471.")])])

    with caplog.at_level("ERROR", logger="app.main"):
        response = tolerant.put(f"/api/guides/{created['id']}", json=document)

    assert response.status_code == 500 and response.json()["error"]["code"] == "internal_error"
    assert "4471" not in caplog.text


def test_an_integrity_error_nobody_anticipated_is_a_conflict_not_a_crash(tolerant, monkeypatch, caplog):
    """Two requests that each passed every check and then collided in the
    database. That is a 409 to retry; and on PostgreSQL the driver's message
    goes on to quote the offending values, so only its first line is logged."""
    from sqlalchemy.exc import IntegrityError

    from app import content

    def collide(*args, **kwargs):
        driver_message = 'duplicate key value violates unique constraint "bullets_pkey"\nDETAIL:  Key (text)=(the door code is 4471)'
        raise IntegrityError("INSERT INTO bullets ...", {"text": "the door code is 4471"}, Exception(driver_message))

    monkeypatch.setattr(content, "read", collide)

    with caplog.at_level("WARNING", logger="app.main"):
        response = tolerant.get("/api/guides/anything")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert "4471" not in response.text and "bullets" not in response.text
    assert "bullets_pkey" in caplog.text, "which constraint is worth knowing"
    assert "4471" not in caplog.text


def test_sql_errors_never_carry_the_values_that_were_bound(tmp_path):
    """The values are what people wrote, and on one table password hashes. With
    the engine's default a failed statement is logged with all of them."""
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    from app import db

    engine = db.build_engine(f"sqlite:///{tmp_path / 'hidden.db'}")
    try:
        with engine.connect() as connection, pytest.raises(SQLAlchemyError) as failure:
            connection.execute(text("INSERT INTO no_such_table (body) VALUES (:body)"), {"body": "the door code is 4471"})
    finally:
        engine.dispose()

    assert "4471" not in str(failure.value)
    assert "hidden" in str(failure.value).lower()


def test_a_rate_limit_can_say_when_to_come_back():
    from app import errors

    assert errors.rate_limited().headers is None, "the login throttle tells an attacker nothing about its window"
    assert errors.rate_limited("Busy.", retry_after=5).headers == {"Retry-After": "5"}
