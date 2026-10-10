"""The login throttle: it must stop guessing without becoming a weapon.

The finding these tests close was that any colleague could lock a named person
out of Reticle indefinitely. A throttle that counts wrong guesses against the
*account* hands that power to whoever makes the wrong guesses, so every test
here is about who a counter belongs to.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app import security
from app.db import utcnow
from app.models import AuditLog, LoginAttempt, User
from app.models import Session as SessionRow
from app.settings import get_settings

from .conftest import TEST_PASSWORD

VICTIM = "victim@zmb.uzh.ch"


def exhaust_the_account_ceiling(client_factory, email: str = VICTIM) -> None:
    """A guess spread over many addresses, until the per-account ceiling trips."""
    settings = get_settings()
    per_source = settings.login_max_attempts_per_email_and_ip
    for index in range(settings.login_max_attempts_per_email // per_source + 1):
        attacker = client_factory(f"203.0.113.{index + 1}")
        for _ in range(per_source):
            attacker.login(email, "wrong-guess")


def test_a_colleague_cannot_lock_somebody_out_of_their_own_browser(client_factory, make_user):
    """The attack: fill the victim's account ceiling from a handful of
    addresses, repeat every window, and they can never sign in again.

    The victim's browser has signed in before, so it carries a device cookie and
    is measured only against that — a counter the attacker cannot reach.
    """
    make_user(VICTIM)
    victims_browser = client_factory("192.0.2.50")
    assert victims_browser.login(VICTIM).status_code == 200
    assert victims_browser.post("/api/auth/logout").status_code == 204

    exhaust_the_account_ceiling(client_factory)

    stranger = client_factory("198.51.100.200")
    assert stranger.login(VICTIM, TEST_PASSWORD).status_code == 429, "the ceiling still stops unknown browsers"
    assert victims_browser.login(VICTIM).status_code == 200, "and never the owner's own"


def test_the_lockout_cannot_be_inflicted_from_the_victims_own_address_either(client_factory, make_user):
    """Shared instrument PCs and NAT put the attacker and the victim behind one
    address. The per-(account, address) tripwire then belongs to both of them —
    unless the victim's browser is counted separately, which it is."""
    make_user(VICTIM)
    victims_browser = client_factory("192.0.2.50")
    victims_browser.login(VICTIM)

    same_address_other_browser = client_factory("192.0.2.50")
    for _ in range(get_settings().login_max_attempts_per_email_and_ip):
        same_address_other_browser.login(VICTIM, "wrong-guess")
    assert same_address_other_browser.login(VICTIM, TEST_PASSWORD).status_code == 429

    assert victims_browser.login(VICTIM).status_code == 200


def test_the_device_cookie_buys_no_more_guesses_than_anyone_gets(client_factory, make_user):
    make_user(VICTIM)
    browser = client_factory("192.0.2.50")
    browser.login(VICTIM)
    limit = get_settings().login_max_attempts_per_email_and_ip

    for _ in range(limit):
        assert browser.login(VICTIM, "wrong-guess").status_code == 401

    assert browser.login(VICTIM, TEST_PASSWORD).status_code == 429


def test_a_device_cookie_is_worthless_for_any_other_account(client_factory, make_user, db_session):
    """It is signed over the account it was issued for. Presented with another
    address it is ignored, so the attempt is counted like a stranger's."""
    make_user("attacker@zmb.uzh.ch")
    make_user(VICTIM)
    attacker = client_factory("198.51.100.7")
    attacker.login("attacker@zmb.uzh.ch")

    attacker.login(VICTIM, "wrong-guess")

    scopes = sorted(attempt.scope for attempt in db_session.scalars(select(LoginAttempt)))
    assert scopes == ["email", "email_ip", "ip"]


@pytest.mark.parametrize(
    "forged",
    [
        "", "no-dot", ".", "nonce.", ".signature", "nonce.deadbeef", "x" * 500, "nonce.\xe9", "a.b.c",
        "v2.nonce.123.deadbeef", "v2..123.sig", "v2.nonce.notanumber.sig", "v1.nonce.123.sig", "v2.nonce.١٢٣.sig",
        "v2.nonce." + "9" * 40 + ".sig",
    ],
)
def test_a_forged_device_cookie_is_ignored(forged):
    assert security.verified_device(VICTIM, forged) is None


def test_a_genuine_device_cookie_verifies_only_for_its_own_account():
    token = security.new_device_token(VICTIM)
    nonce = token.split(".")[1]

    assert security.verified_device(VICTIM, token) == nonce
    assert security.verified_device("someone.else@zmb.uzh.ch", token) is None
    assert security.verified_device(VICTIM, None) is None
    assert security.new_device_token(VICTIM) != token


def test_a_device_cookie_from_before_the_format_changed_no_longer_verifies():
    """The first format was ``nonce.signature`` over the address alone: no
    issue time, nothing tying it to a password. One of those must not be
    accepted as if it were current."""
    import hashlib
    import hmac

    secret = get_settings().secret_key.encode()
    nonce = "0123456789abcdef"
    old = f"{nonce}.{hmac.new(secret, f'device\x00{VICTIM}\x00{nonce}'.encode(), hashlib.sha256).hexdigest()}"

    assert security.verified_device(VICTIM, old) is None


# ------------------------------------------- a device cookie expires and is bound


def test_a_device_cookie_stops_verifying_when_it_is_too_old():
    now = int(security.time.time())
    fresh = security.new_device_token(VICTIM, issued_at=now - security.DEVICE_COOKIE_MAX_AGE_SECONDS + 60)
    stale = security.new_device_token(VICTIM, issued_at=now - security.DEVICE_COOKIE_MAX_AGE_SECONDS - 60)
    from_the_future = security.new_device_token(VICTIM, issued_at=now + 3600)

    assert security.verified_device(VICTIM, fresh) is not None
    assert security.verified_device(VICTIM, stale) is None
    assert security.verified_device(VICTIM, from_the_future) is None


def test_the_issue_time_is_signed_so_an_old_cookie_cannot_be_made_young():
    old = security.new_device_token(VICTIM, issued_at=1_000_000)
    version, nonce, _, signature = old.split(".")

    redated = f"{version}.{nonce}.{int(security.time.time())}.{signature}"

    assert security.verified_device(VICTIM, redated) is None


def test_a_device_cookie_is_bound_to_the_credentials_it_was_earned_with():
    token = security.new_device_token(VICTIM, auth_epoch=3)

    assert security.verified_device(VICTIM, token, 3) is not None
    assert security.verified_device(VICTIM, token, 4) is None
    assert security.verified_device(VICTIM, token, None) is None, "no active account, nothing to verify against"


def _device_attempts(db_session) -> list[str]:
    db_session.expire_all()
    return sorted(attempt.scope for attempt in db_session.scalars(select(LoginAttempt)))


def test_changing_the_password_retires_every_device_cookie_issued_before(client_factory, make_user, db_session):
    """The finding: anyone who ever knew a password kept a cookie that bought
    guesses outside the shared ceilings for ever. After a password change the
    old cookie is a stranger's — counted per source and per account again."""
    user = make_user(VICTIM, role="author")
    former = client_factory("203.0.113.9")
    assert former.login(VICTIM).status_code == 200
    owner = client_factory("192.0.2.50")
    assert owner.login(VICTIM).status_code == 200

    changed = owner.post(
        f"/api/users/{user.id}/password",
        json={"currentPassword": TEST_PASSWORD, "newPassword": "A-Different-Passphrase-7"},
    )
    assert changed.status_code == 204

    assert former.login(VICTIM, "wrong-guess").status_code == 401
    assert _device_attempts(db_session) == ["email", "email_ip", "ip"], "counted as a stranger, not as a known device"

    assert owner.post("/api/auth/logout").status_code == 204, "the session that made the change survives it"
    assert owner.login(VICTIM, "wrong-guess").status_code == 401
    assert "device" in _device_attempts(db_session), "the browser that made the change kept its standing"


def test_an_admin_reset_retires_the_device_cookies_too(client_factory, make_user, as_role, db_session):
    user = make_user(VICTIM)
    browser = client_factory("203.0.113.9")
    assert browser.login(VICTIM).status_code == 200

    admin = as_role("admin")
    assert admin.post(f"/api/users/{user.id}/password", json={"newPassword": "Reset-By-An-Admin-22"}).status_code == 204

    browser.login(VICTIM, "wrong-guess")
    assert _device_attempts(db_session) == ["email", "email_ip", "ip"]


def test_a_deactivated_account_cannot_be_guessed_at_outside_the_ceilings(client_factory, make_user, as_role, db_session):
    """Each attempt at a deactivated account runs a full password hash. With a
    cookie that skipped the shared counters that was unlimited work to ask of
    the server; now the cookie is void and the ordinary limits apply."""
    user = make_user(VICTIM)
    browser = client_factory("203.0.113.9")
    assert browser.login(VICTIM).status_code == 200
    admin = as_role("admin")
    assert admin.patch(f"/api/users/{user.id}", json={"isActive": False}).status_code == 200

    limit = get_settings().login_max_attempts_per_email_and_ip
    for _ in range(limit):
        assert browser.login(VICTIM).status_code == 401
    assert browser.login(VICTIM).status_code == 429
    assert "device" not in _device_attempts(db_session)

    db_session.expire_all()
    assert db_session.get(User, user.id).auth_epoch == 1


def test_reactivating_an_account_does_not_bring_its_old_cookies_back(client_factory, make_user, as_role, db_session):
    user = make_user(VICTIM)
    browser = client_factory("203.0.113.9")
    browser.login(VICTIM)
    admin = as_role("admin")
    admin.patch(f"/api/users/{user.id}", json={"isActive": False})
    admin.patch(f"/api/users/{user.id}", json={"isActive": True})

    browser.login(VICTIM, "wrong-guess")

    assert _device_attempts(db_session) == ["email", "email_ip", "ip"]


def test_a_throttled_login_is_refused_before_any_password_hashing(client_factory, make_user, monkeypatch):
    """429 has to be the cheap answer. Verifying first and refusing afterwards
    would let a throttled client keep the server hashing at full speed."""
    from app.routers import auth as auth_router

    make_user(VICTIM)
    client = client_factory("203.0.113.9")
    for _ in range(get_settings().login_max_attempts_per_email_and_ip):
        client.login(VICTIM, "wrong-guess")

    hashed = []
    monkeypatch.setattr(auth_router, "verify_password", lambda *a: hashed.append("real") or False)
    monkeypatch.setattr(auth_router, "burn_password_time", lambda: hashed.append("decoy"))

    assert client.login(VICTIM).status_code == 429
    assert client.login("nobody@zmb.uzh.ch").status_code == 401
    assert hashed == ["decoy"], "the throttled request hashed nothing; the unknown account burned exactly one"


def test_an_inactive_account_costs_one_decoy_hash_like_an_unknown_one(client_factory, make_user, monkeypatch):
    from app.routers import auth as auth_router

    make_user(VICTIM, is_active=False)
    hashed = []
    monkeypatch.setattr(auth_router, "verify_password", lambda *a: hashed.append("real") or False)
    monkeypatch.setattr(auth_router, "burn_password_time", lambda: hashed.append("decoy"))

    assert client_factory("203.0.113.9").login(VICTIM).status_code == 401
    assert hashed == ["decoy"]


# ----------------------------------------- what a device cookie does and does not buy


def test_noise_from_a_shared_address_does_not_lock_out_a_colleague_who_has_signed_in_here(client_factory, make_user):
    """Twenty failures on made-up addresses from one source — a NAT, a shared
    instrument PC — close that source for everybody behind it. Somebody whose
    browser has signed in before is who the device cookie is for."""
    make_user(VICTIM)
    regular = client_factory("192.0.2.50")
    assert regular.login(VICTIM).status_code == 200
    regular.post("/api/auth/logout")

    noisy = client_factory("192.0.2.50")
    for index in range(get_settings().login_max_attempts_per_ip):
        noisy.login(f"made-up-{index}@zmb.uzh.ch", "whatever")
    assert noisy.login(VICTIM).status_code == 429, "a browser with no history here is still shut out"

    assert regular.login(VICTIM).status_code == 200


def test_attempts_from_a_known_device_still_count_towards_the_account(client_factory, make_user, db_session):
    make_user(VICTIM)
    browser = client_factory("192.0.2.50")
    browser.login(VICTIM)

    browser.login(VICTIM, "wrong-guess")

    assert _device_attempts(db_session) == ["device", "devices", "email"]


def test_many_device_cookies_do_not_add_up_to_more_than_the_account_ceiling(client_factory, make_user, db_session):
    """Every successful sign-in from a new browser mints a cookie, and each has
    its own allowance. Someone who collected many would otherwise have that many
    allowances per window; together they are held to the account's ceiling."""
    make_user(VICTIM)
    settings = get_settings()
    per_device = settings.login_max_attempts_per_email_and_ip
    devices_needed = settings.login_max_attempts_per_email // per_device

    guesses = 0
    for index in range(devices_needed):
        browser = client_factory(f"198.51.100.{index + 1}")
        assert browser.login(VICTIM).status_code == 200
        for _ in range(per_device):
            assert browser.login(VICTIM, "wrong-guess").status_code == 401
            guesses += 1
    assert guesses == settings.login_max_attempts_per_email

    one_more = client_factory("198.51.100.250")
    one_more.cookies.set("reticle_device", security.new_device_token(VICTIM), path="/api/auth")
    assert one_more.login(VICTIM, "wrong-guess").status_code == 429


def test_strangers_cannot_fill_the_ceiling_that_known_devices_are_held_to(client_factory, make_user):
    make_user(VICTIM)
    owner = client_factory("192.0.2.50")
    owner.login(VICTIM)
    owner.post("/api/auth/logout")

    exhaust_the_account_ceiling(client_factory)

    assert owner.login(VICTIM).status_code == 200


def test_an_ageing_device_cookie_is_renewed_at_the_next_sign_in(anon, make_user):
    make_user(VICTIM)
    old = security.new_device_token(
        VICTIM, issued_at=int(security.time.time()) - security.DEVICE_TOKEN_REFRESH_SECONDS - 60
    )
    anon.cookies.set("reticle_device", old, path="/api/auth")

    response = anon.login(VICTIM)

    renewed = [h for h in response.headers.get_list("set-cookie") if h.startswith("reticle_device=")]
    assert len(renewed) == 1 and old not in renewed[0]


def test_the_device_cookie_is_httponly_scoped_to_auth_and_outlives_logout(anon, make_user):
    make_user(VICTIM)

    response = anon.login(VICTIM)
    cookie = next(h for h in response.headers.get_list("set-cookie") if h.startswith("reticle_device="))

    assert "HttpOnly" in cookie
    assert "Path=/api/auth" in cookie
    assert "samesite=lax" in cookie.lower()
    assert f"Max-Age={180 * 24 * 3600}" in cookie
    assert "Secure" not in cookie

    logout = anon.post("/api/auth/logout")
    assert not [h for h in logout.headers.get_list("set-cookie") if h.startswith("reticle_device=")]

    again = anon.login(VICTIM)
    assert not [h for h in again.headers.get_list("set-cookie") if h.startswith("reticle_device=")], "kept, not re-minted"


def test_a_failed_login_issues_no_device_cookie(anon, make_user):
    make_user(VICTIM)

    response = anon.login(VICTIM, "wrong-guess")

    assert not [h for h in response.headers.get_list("set-cookie") if h.startswith("reticle_device=")]


def test_the_device_cookie_is_secure_in_production(monkeypatch, client_factory, make_user):
    make_user(VICTIM)
    monkeypatch.setenv("RETICLE_COOKIE_SECURE", "true")
    get_settings.cache_clear()

    response = client_factory().login(VICTIM)

    cookie = next(h for h in response.headers.get_list("set-cookie") if h.startswith("reticle_device="))
    assert "Secure" in cookie


# ------------------------------------------------------------------- sources


@pytest.mark.parametrize(
    "address,source",
    [
        ("198.51.100.7", "198.51.100.7"),
        ("2001:db8:aa:bb:1:2:3:4", "2001:db8:aa:bb::/64"),
        ("2001:db8:aa:bb:ffff:ffff:ffff:ffff", "2001:db8:aa:bb::/64"),
        ("2001:db8:aa:bc::1", "2001:db8:aa:bc::/64"),
        ("::ffff:198.51.100.7", "198.51.100.7"),
        ("testclient", "testclient"),
        (None, None),
    ],
)
def test_an_ipv6_source_is_its_whole_64_not_one_address(address, source):
    assert security.throttle_source(address) == source


def test_rotating_through_an_ipv6_prefix_does_not_mint_fresh_buckets(client_factory, make_user):
    """One laptop has eighteen quintillion addresses in its /64. Counted
    singly, both per-source limits would be decoration."""
    make_user(VICTIM)
    limit = get_settings().login_max_attempts_per_email_and_ip

    for index in range(limit):
        assert client_factory(f"2001:db8:1:2::{index + 1:x}").login(VICTIM, "wrong-guess").status_code == 401

    assert client_factory("2001:db8:1:2:dead:beef:0:1").login(VICTIM, "wrong-guess").status_code == 429
    assert client_factory("2001:db8:1:3::1").login(VICTIM, "wrong-guess").status_code == 401


def test_spraying_from_one_ipv6_prefix_hits_the_per_source_limit(client_factory):
    for index in range(get_settings().login_max_attempts_per_ip):
        client = client_factory(f"2001:db8:5:5::{index + 1:x}")
        assert client.login(f"spray-{index}@zmb.uzh.ch", "Winter2026!").status_code == 401

    assert client_factory("2001:db8:5:5::ffff").login("one-more@zmb.uzh.ch", "Winter2026!").status_code == 429


def test_a_valid_account_cannot_be_used_to_reset_the_spray_limit(client_factory, make_user):
    """An attacker who owns one account would otherwise sign in to it between
    guesses and start the per-source count again."""
    make_user("attacker@zmb.uzh.ch")
    limit = get_settings().login_max_attempts_per_ip
    sprayer = client_factory("203.0.113.4")

    for index in range(limit - 1):
        sprayer.login(f"spray-{index}@zmb.uzh.ch", "Winter2026!")
    assert client_factory("203.0.113.4").login("attacker@zmb.uzh.ch").status_code == 200
    assert sprayer.login("spray-last@zmb.uzh.ch", "Winter2026!").status_code == 401

    assert sprayer.login("spray-over@zmb.uzh.ch", "Winter2026!").status_code == 429


def test_the_owner_signing_in_does_not_refill_a_distributed_attackers_allowance(client_factory, make_user):
    make_user(VICTIM)
    owner = client_factory("192.0.2.50")
    owner.login(VICTIM)
    exhaust_the_account_ceiling(client_factory)

    assert owner.login(VICTIM).status_code == 200

    assert client_factory("198.51.100.201").login(VICTIM, "wrong-guess").status_code == 429


def test_without_a_source_address_only_the_account_ceiling_applies(db_session):
    subject = security.LoginSubject.of(VICTIM, None)
    limit = get_settings().login_max_attempts_per_email

    for _ in range(limit - 1):
        security.record_login_attempt(db_session, subject)
    assert security.login_is_throttled(db_session, subject) is False
    assert {attempt.scope for attempt in db_session.scalars(select(LoginAttempt))} == {"email"}

    security.record_login_attempt(db_session, subject)
    assert security.login_is_throttled(db_session, subject) is True

    security.forgive_login_attempts(db_session, subject, [])
    assert security.login_is_throttled(db_session, subject) is True, "there is no pair history to forgive"


# ------------------------------------------------------------------ the ledger


def test_an_attempt_is_counted_before_its_password_is_checked(anon, make_user, db_session, monkeypatch):
    """Counting afterwards leaves a gap as wide as the Argon2 computation, and a
    hundred guesses sent in parallel all pass the check inside it."""
    from app.routers import auth as auth_router

    make_user(VICTIM)
    seen_during_verification = []

    def verifying(stored_hash, plaintext):
        seen_during_verification.append(len(db_session.scalars(select(LoginAttempt)).all()))
        db_session.rollback()
        return security.verify_password(stored_hash, plaintext)

    monkeypatch.setattr(auth_router, "verify_password", verifying)

    assert anon.login(VICTIM, "wrong-guess").status_code == 401
    assert seen_during_verification == [3]


def test_a_successful_login_takes_its_own_attempt_back(anon, make_user, db_session):
    make_user(VICTIM)

    assert anon.login(VICTIM).status_code == 200

    assert db_session.scalars(select(LoginAttempt)).all() == []


def test_the_ledger_never_holds_what_was_typed_into_the_email_field(anon, db_session):
    """The thing most often typed there by mistake is a password, with an ``@``
    in it. It satisfies validation and would otherwise be stored verbatim."""
    anon.login("Tr0ub4dor&3@horse.staple", "whatever")

    keys = " ".join(attempt.key for attempt in db_session.scalars(select(LoginAttempt)))
    assert "tr0ub4dor" not in keys.lower()
    assert "horse.staple" not in keys
    assert security.email_fingerprint("tr0ub4dor&3@horse.staple") in keys


def test_an_account_deactivated_mid_login_is_still_refused(anon, make_user, db_session, monkeypatch):
    from app.routers import auth as auth_router

    make_user(VICTIM)

    def deactivate_then_verify(stored_hash, plaintext):
        user = db_session.scalars(select(User).where(User.email == VICTIM)).one()
        user.is_active = False
        db_session.commit()
        return security.verify_password(stored_hash, plaintext)

    monkeypatch.setattr(auth_router, "verify_password", deactivate_then_verify)

    response = anon.login(VICTIM)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert db_session.scalars(select(SessionRow)).all() == []


def test_being_throttled_is_audited_once_per_window_not_once_per_request(anon, make_user, db_session):
    """Anybody who can reach the login form could otherwise grow the audit
    table without limit, at the moment the trail is most worth reading."""
    make_user(VICTIM)
    for _ in range(get_settings().login_max_attempts_per_email_and_ip):
        anon.login(VICTIM, "wrong-guess")

    for _ in range(25):
        assert anon.login(VICTIM, "wrong-guess").status_code == 429

    throttled = db_session.scalars(select(AuditLog).where(AuditLog.action == "auth.login_throttled")).all()
    assert len(throttled) == 1
    assert throttled[0].detail == {"emailDigest": security.email_fingerprint(VICTIM)}
    assert len(db_session.scalars(select(LoginAttempt)).all()) == 3 * get_settings().login_max_attempts_per_email_and_ip


def test_the_throttle_lifts_when_the_window_has_passed(anon, make_user, db_session):
    make_user(VICTIM)
    for _ in range(get_settings().login_max_attempts_per_email_and_ip):
        anon.login(VICTIM, "wrong-guess")
    assert anon.login(VICTIM).status_code == 429

    for attempt in db_session.scalars(select(LoginAttempt)):
        attempt.created_at = utcnow() - timedelta(minutes=get_settings().login_attempt_window_minutes + 1)
    db_session.commit()

    assert anon.login(VICTIM).status_code == 200


# -------------------------------------------------------------------- pruning


def _session_row(user_id: str, token: str, **fields) -> SessionRow:
    return SessionRow(user_id=user_id, token_hash=token * 64, csrf_token="c", **fields)


def test_pruning_removes_dead_sessions_and_stale_attempts_and_nothing_else(db_session, make_user):
    user = make_user(VICTIM)
    now = utcnow()
    window = timedelta(minutes=get_settings().login_attempt_window_minutes)
    old = now - security.SESSION_RETENTION - timedelta(hours=1)
    recent = now - timedelta(hours=1)
    db_session.add_all(
        [
            _session_row(user.id, "a", expires_at=now + timedelta(hours=1)),
            _session_row(user.id, "b", expires_at=old),
            _session_row(user.id, "c", expires_at=recent),
            _session_row(user.id, "d", expires_at=now + timedelta(hours=1), revoked_at=old),
            _session_row(user.id, "e", expires_at=now + timedelta(hours=1), revoked_at=recent),
            LoginAttempt(scope="ip", key="stale", created_at=now - window - timedelta(minutes=1)),
            LoginAttempt(scope="ip", key="fresh", created_at=now - window + timedelta(minutes=1)),
        ]
    )
    db_session.commit()

    removed = security.prune_stale_rows(db_session)
    db_session.commit()

    assert removed == (1, 2)
    assert sorted(row.token_hash[0] for row in db_session.scalars(select(SessionRow))) == ["a", "c", "e"]
    assert [attempt.key for attempt in db_session.scalars(select(LoginAttempt))] == ["fresh"]


def test_login_traffic_prunes_even_when_nobody_ever_succeeds(anon, db_session, make_user, monkeypatch):
    """Pruning used to run only after a *successful* login, so a stream of
    failures — the case that fills the table — never triggered it."""
    user = make_user(VICTIM)
    long_ago = utcnow() - timedelta(days=60)
    db_session.add(LoginAttempt(scope="ip", key="ancient", created_at=long_ago))
    db_session.add(_session_row(user.id, "z", expires_at=long_ago))
    db_session.commit()
    monkeypatch.setattr(security, "_last_prune", None)

    assert anon.login("nobody@zmb.uzh.ch", "wrong-guess").status_code == 401

    assert "ancient" not in [attempt.key for attempt in db_session.scalars(select(LoginAttempt))]
    assert db_session.scalars(select(SessionRow)).all() == []


def test_pruning_runs_at_most_once_per_interval(db_session, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(security.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(security, "_last_prune", None)

    assert security.prune_if_due(db_session) is True
    clock[0] += security.PRUNE_INTERVAL_SECONDS - 1
    assert security.prune_if_due(db_session) is False
    clock[0] += 2
    assert security.prune_if_due(db_session) is True
