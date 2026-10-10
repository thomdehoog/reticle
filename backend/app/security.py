"""Password hashing, session tokens and the login throttle.

Nothing here formats a response or touches the request object; the routers do
that. Keeping the primitives separate is what makes the throttle testable and
what keeps the "never log a password" rule enforceable by inspection.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError, VerificationError
from argon2.low_level import Type
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session as DbSession

from .db import utcnow
from .models import LoginAttempt, Session as SessionRow, User
from .settings import Settings, get_settings

SESSION_COOKIE = "reticle_session"
CSRF_COOKIE = "reticle_csrf"
CSRF_HEADER = "X-CSRF-Token"

DEVICE_COOKIE = "reticle_device"
DEVICE_COOKIE_MAX_AGE_SECONDS = 180 * 24 * 3600
DEVICE_TOKEN_VERSION = "v2"
DEVICE_TOKEN_REFRESH_SECONDS = 30 * 24 * 3600
"""A device token older than this is replaced at the next successful sign-in,
so a browser in regular use never reaches the end of the cookie's life and one
that stops being used does."""

SCOPE_EMAIL = "email"
SCOPE_ADDRESS = "ip"
SCOPE_EMAIL_ADDRESS = "email_ip"
SCOPE_DEVICE = "device"
SCOPE_ACCOUNT_DEVICES = "devices"


@lru_cache(maxsize=4)
def _hasher(time_cost: int, memory_cost: int, parallelism: int) -> PasswordHasher:
    return PasswordHasher(
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    )


def _current_hasher() -> PasswordHasher:
    settings = get_settings()
    return _hasher(settings.argon2_time_cost, settings.argon2_memory_cost_kib, settings.argon2_parallelism)


def hash_password(plaintext: str) -> str:
    return _current_hasher().hash(plaintext)


def verify_password(stored_hash: str, plaintext: str) -> bool:
    try:
        return _current_hasher().verify(stored_hash, plaintext)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


@lru_cache(maxsize=4)
def _decoy_hash(time_cost: int, memory_cost: int, parallelism: int) -> str:
    """A hash of a value nobody knows, verified when the account is missing.

    Skipping the Argon2 work for an unknown email would make the failure
    measurably faster than a wrong password and turn the login endpoint into an
    account-enumeration oracle.
    """
    return _hasher(time_cost, memory_cost, parallelism).hash(secrets.token_urlsafe(32))


def burn_password_time() -> None:
    settings = get_settings()
    decoy = _decoy_hash(settings.argon2_time_cost, settings.argon2_memory_cost_kib, settings.argon2_parallelism)
    verify_password(decoy, "not-the-password")


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _current_hasher().check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    """Keyed digest, so a stolen database cannot be turned into live cookies.

    A bare SHA-256 of a 256-bit random token is already hard to reverse, but the
    application secret costs nothing here and removes the offline attack
    entirely.
    """
    secret = get_settings().secret_key.encode("utf-8")
    return hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()


def create_session(
    db: DbSession,
    user: User,
    ip_address: str | None,
    user_agent: str | None,
) -> tuple[SessionRow, str]:
    settings = get_settings()
    token = new_session_token()
    row = SessionRow(
        user_id=user.id,
        token_hash=token_digest(token),
        csrf_token=secrets.token_urlsafe(32),
        expires_at=utcnow() + timedelta(hours=settings.session_lifetime_hours),
        ip_address=ip_address,
        user_agent=(user_agent or "")[:400] or None,
    )
    db.add(row)
    return row, token


def resolve_session(db: DbSession, token: str | None) -> SessionRow | None:
    if not token:
        return None
    row = db.scalars(select(SessionRow).where(SessionRow.token_hash == token_digest(token))).one_or_none()
    if row is None or not row.is_live(utcnow()):
        return None
    return row


def revoke_session(row: SessionRow) -> None:
    if row.revoked_at is None:
        row.revoked_at = utcnow()


def end_credentials(db: DbSession, user: User, except_session_id: str | None = None) -> int:
    """Withdraw everything that was earned with the account's old credentials.

    Called when a password is changed or reset and when an account is
    deactivated. Its sessions are revoked — all but the one making the change,
    when the owner is changing their own — and its epoch is raised, which is
    what stops every device cookie issued before this moment from verifying.
    Returns how many sessions were revoked.
    """
    user.auth_epoch = (user.auth_epoch or 0) + 1
    return revoke_all_sessions(db, user.id, except_session_id=except_session_id)


def revoke_all_sessions(db: DbSession, user_id: str, except_session_id: str | None = None) -> int:
    rows = db.scalars(
        select(SessionRow).where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
    ).all()
    revoked = 0
    for row in rows:
        if row.id == except_session_id:
            continue
        revoke_session(row)
        revoked += 1
    return revoked


def constant_time_equals(left: str | None, right: str | None) -> bool:
    """Compare two tokens without leaking where they first differ.

    ``hmac.compare_digest`` refuses two ``str`` arguments as soon as either holds
    a code point above U+007F, and it signals that by raising ``TypeError``.
    Starlette hands headers over latin-1 decoded, so ``X-CSRF-Token: \xe9`` is a
    perfectly ordinary request that used to leave this function as an unhandled
    exception — a 500 from inside the middleware, which is to say a request that
    escaped the check it was supposed to fail. Encoding first makes every input
    comparable; ``surrogatepass`` keeps that true for the lone surrogates a
    cookie parser can produce.
    """
    if not left or not right:
        return False
    return hmac.compare_digest(
        left.encode("utf-8", "surrogatepass"),
        right.encode("utf-8", "surrogatepass"),
    )


def email_fingerprint(email: str) -> str:
    """A keyed digest standing in for a submitted address in the audit trail.

    What arrives at the login endpoint is not necessarily an email address: it
    only has to satisfy ``EmailStr``, and the thing that most often satisfies it
    by accident is a password typed one field too high. Recording the digest
    keeps repeated attempts on one address correlatable, and lets an operator
    confirm a suspected address by hashing it, without the submitted string ever
    being written down. When the address does resolve to an account the audit
    row already carries ``actor_id``, so nothing operational is lost.
    """
    secret = get_settings().secret_key.encode("utf-8")
    return hmac.new(secret, email.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def _window_start(settings: Settings) -> datetime:
    return utcnow() - timedelta(minutes=settings.login_attempt_window_minutes)


def throttle_source(ip_address: str | None) -> str | None:
    """The unit the per-source counters count: an IPv4 address, or an IPv6 /64.

    One IPv6 customer is handed at least a /64, which is eighteen quintillion
    addresses. Counting each as a separate source would let a single laptop
    rotate through as many fresh throttle buckets as it liked, which turns both
    per-source limits into decoration.
    """
    if ip_address is None:
        return None
    try:
        parsed = ipaddress.ip_address(ip_address)
    except ValueError:
        return ip_address
    if parsed.version == 4:
        return str(parsed)
    if parsed.ipv4_mapped is not None:
        return str(parsed.ipv4_mapped)
    return str(ipaddress.ip_network((int(parsed) >> 64 << 64, 64)))


def _device_signature(email: str, nonce: str, issued_at: int, auth_epoch: int) -> str:
    secret = get_settings().secret_key.encode("utf-8")
    message = f"device\x00{DEVICE_TOKEN_VERSION}\x00{email}\x00{nonce}\x00{issued_at}\x00{auth_epoch}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def new_device_token(email: str, auth_epoch: int = 0, issued_at: int | None = None) -> str:
    """Mint the cookie that marks this browser as one the account has used.

    A random nonce, the moment of issue, and a keyed signature over both
    together with the address and the account's credential epoch. There is
    still no table of them, and there does not need to be one for a token to
    die: it dies of age, because the issue time is signed and checked, and it
    dies with the credentials it was earned by, because the epoch is signed and
    the account's epoch moves on whenever its password is changed or reset or
    the account is switched off. The first version had neither, so a browser
    that had once signed in — with a password since changed, to an account
    since deactivated — kept its standing for good.
    """
    nonce = secrets.token_urlsafe(16)
    issued = int(time.time()) if issued_at is None else issued_at
    return f"{DEVICE_TOKEN_VERSION}.{nonce}.{issued}.{_device_signature(email, nonce, issued, auth_epoch)}"


def device_token_age(token: str | None) -> int | None:
    """Seconds since a token of the current format says it was issued; unverified."""
    parts = (token or "").split(".")
    if len(parts) != 4 or not parts[2].isascii() or not parts[2].isdigit():
        return None
    return int(time.time()) - int(parts[2])


def verified_device(email: str, token: str | None, auth_epoch: int | None = 0) -> str | None:
    """The device nonce, if the cookie is genuine, current and was issued for this account.

    ``auth_epoch`` is the account's present epoch, or ``None`` when there is no
    such active account — in which case nothing verifies, so that a token for a
    deactivated account is exactly as useful as no token. The signature is
    compared in constant time and before the age is looked at, so a forger
    learns nothing from which of the two failed.
    """
    if auth_epoch is None or not token or len(token) > 200:
        return None
    parts = token.split(".")
    if len(parts) != 4:
        return None
    version, nonce, issued_text, signature = parts
    if version != DEVICE_TOKEN_VERSION or not nonce or not issued_text.isascii() or not issued_text.isdigit():
        return None
    if len(issued_text) > 12:
        return None
    issued_at = int(issued_text)
    genuine = constant_time_equals(signature, _device_signature(email, nonce, issued_at, auth_epoch))
    age = int(time.time()) - issued_at
    if not genuine or age < -300 or age > DEVICE_COOKIE_MAX_AGE_SECONDS:
        return None
    return nonce


@dataclass(frozen=True)
class LoginSubject:
    """Who is trying to sign in, reduced to the keys the throttle counts by.

    The account is a keyed digest rather than the typed address. What arrives in
    the email field only has to look like an address, and the string that most
    often does so by accident is a password typed one field too high; the ledger
    must not become a place those are kept in the clear.
    """

    account: str
    source: str | None
    device: str | None

    @classmethod
    def of(
        cls,
        email: str,
        ip_address: str | None,
        device_token: str | None = None,
        auth_epoch: int | None = 0,
    ) -> "LoginSubject":
        return cls(
            account=email_fingerprint(email),
            source=throttle_source(ip_address),
            device=verified_device(email, device_token, auth_epoch),
        )

    @property
    def pair_key(self) -> str:
        return f"{self.account}|{self.source}"

    @property
    def device_key(self) -> str:
        return f"{self.account}|{self.device}"


def _failures(db: DbSession, scope: str, key: str, since: datetime) -> int:
    return db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.scope == scope, LoginAttempt.key == key, LoginAttempt.created_at >= since)
    )


def login_is_throttled(db: DbSession, subject: LoginSubject) -> bool:
    """Block whoever is guessing, never the account being guessed at.

    Five counters, and who can fill each one is the design.

    Everybody without a device cookie is counted three ways. Per (account,
    source) is the tripwire that stops one host guessing at one account. Per
    source catches one host spraying a common password across many accounts,
    which the first never sees. Per account is a much higher ceiling that still
    bounds a guess spread over many hosts.

    All three can be filled by someone other than the person they then keep
    out. Twenty mistyped or made-up addresses from one shared address — a NAT,
    an instrument PC — close the per-source counter for everyone behind it, and
    a guess spread over a few hosts closes the per-account one for the account's
    owner. A browser that has signed in to this account before carries a signed
    device cookie, and that is what it is for: such a browser is **not turned
    away by the counters that strangers fill**. It is measured by two of its
    own instead.

    Per device, the same five guesses a window that any stranger gets at one
    account. And per account across all of its devices, the same ceiling that
    bounds strangers — because one person can hold many cookies, each minted by
    a real sign-in, and without a total every one of them would be a fresh
    allowance. Only holders of a genuine, current cookie for the account can
    add to that total, so it cannot be used to lock the owner out either.

    The cookie buys nothing else. It expires, it stops verifying the moment the
    account's password is changed or reset or the account is deactivated, and
    attempts made with it are still written to the per-account counter that
    strangers are held to.

    Without a usable source address the attacker cannot be told from a
    first-time visitor, so only the account ceiling applies.
    """
    settings = get_settings()
    since = _window_start(settings)

    if subject.device is not None:
        if _failures(db, SCOPE_DEVICE, subject.device_key, since) >= settings.login_max_attempts_per_email_and_ip:
            return True
        return _failures(db, SCOPE_ACCOUNT_DEVICES, subject.account, since) >= settings.login_max_attempts_per_email

    if subject.source is None:
        return _failures(db, SCOPE_EMAIL, subject.account, since) >= settings.login_max_attempts_per_email

    if _failures(db, SCOPE_EMAIL_ADDRESS, subject.pair_key, since) >= settings.login_max_attempts_per_email_and_ip:
        return True
    if _failures(db, SCOPE_ADDRESS, subject.source, since) >= settings.login_max_attempts_per_ip:
        return True
    return _failures(db, SCOPE_EMAIL, subject.account, since) >= settings.login_max_attempts_per_email


def record_login_attempt(db: DbSession, subject: LoginSubject) -> list[str]:
    """Count an attempt *before* its password is checked; return the row ids.

    Counting afterwards leaves a gap exactly as wide as the Argon2 computation,
    and a hundred guesses sent in parallel all pass the check inside it. Writing
    the rows first and taking them back on success closes the gap without
    holding the database's write lock for the length of a password hash.

    An attempt from a known device is written to its own two counters and to
    the per-account one as well: a guess is a guess at the account whoever
    makes it, and leaving these out would let a holder of old cookies guess
    beside the ceiling instead of under it.
    """
    rows = [LoginAttempt(scope=SCOPE_EMAIL, key=subject.account)]
    if subject.device is not None:
        rows.append(LoginAttempt(scope=SCOPE_DEVICE, key=subject.device_key))
        rows.append(LoginAttempt(scope=SCOPE_ACCOUNT_DEVICES, key=subject.account))
    elif subject.source is not None:
        rows.append(LoginAttempt(scope=SCOPE_ADDRESS, key=subject.source))
        rows.append(LoginAttempt(scope=SCOPE_EMAIL_ADDRESS, key=subject.pair_key))
    db.add_all(rows)
    db.flush()
    return [row.id for row in rows]


def forgive_login_attempts(db: DbSession, subject: LoginSubject, attempt_ids: list[str]) -> None:
    """Take back exactly what proving the password disproves.

    The rows written for this attempt go, and so does the history of this
    browser or this (account, source) pair, since its owner has just shown they
    know the password. The per-source and per-account totals contributed by
    *other* attempts stay: an attacker who owns one valid account would
    otherwise reset the spray limit between every guess, and an owner signing in
    would otherwise hand a distributed attacker a fresh allowance.
    """
    conditions = [LoginAttempt.id.in_(attempt_ids)]
    if subject.device is not None:
        conditions.append(and_(LoginAttempt.scope == SCOPE_DEVICE, LoginAttempt.key == subject.device_key))
    if subject.source is not None:
        conditions.append(and_(LoginAttempt.scope == SCOPE_EMAIL_ADDRESS, LoginAttempt.key == subject.pair_key))
    db.execute(delete(LoginAttempt).where(or_(*conditions)))


SESSION_RETENTION = timedelta(days=7)
"""How long a dead session row is kept before it is deleted.

Long enough that last week's audit entries can still be matched to the session
they name; short enough that the table tracks the number of people using
Reticle rather than the number of times anyone ever signed in.
"""

PRUNE_INTERVAL_SECONDS = 600.0

_last_prune: float | None = None


def prune_stale_rows(db: DbSession) -> tuple[int, int]:
    """Delete login attempts outside the window and sessions long dead.

    Returns how many of each went, for the log line and the tests.
    """
    attempts = db.execute(
        delete(LoginAttempt).where(LoginAttempt.created_at < _window_start(get_settings()))
    ).rowcount
    horizon = utcnow() - SESSION_RETENTION
    sessions = db.execute(
        delete(SessionRow).where(
            or_(
                SessionRow.expires_at < horizon,
                and_(SessionRow.revoked_at.is_not(None), SessionRow.revoked_at < horizon),
            )
        )
    ).rowcount
    return attempts, sessions


def prune_if_due(db: DbSession) -> bool:
    """Prune at most once per interval per process.

    Called from the login path, which is the one place that writes to both
    tables, so they are kept in check by the same traffic that fills them —
    including a stream of failed attempts, which never reaches a successful
    login and so never reached the pruning that used to live there.
    """
    global _last_prune
    now = time.monotonic()
    if _last_prune is not None and now - _last_prune < PRUNE_INTERVAL_SECONDS:
        return False
    _last_prune = now
    prune_stale_rows(db)
    return True
