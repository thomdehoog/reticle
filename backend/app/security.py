"""Password hashing, session tokens and the login throttle.

Nothing here formats a response or touches the request object; the routers do
that. Keeping the primitives separate is what makes the throttle testable and
what keeps the "never log a password" rule enforceable by inspection.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session as DbSession

from .db import utcnow
from .models import LoginAttempt, User
from .models import Session as SessionRow
from .settings import Settings, get_settings

SESSION_COOKIE = "reticle_session"
CSRF_COOKIE = "reticle_csrf"
CSRF_HEADER = "X-CSRF-Token"

SCOPE_EMAIL = "email"
SCOPE_ADDRESS = "ip"
SCOPE_EMAIL_ADDRESS = "email_ip"


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


PAIR_SEPARATOR = "\x1f"
"""ASCII unit separator, joining the two halves of a per-email-and-address key.

It has to be a character that cannot occur in either half, or two different
pairs could collapse onto one key and share a throttle budget. It also has to
be storable, and that is the part that was wrong: this was ``\\x00``, and
PostgreSQL text columns cannot hold a NUL byte at all. SQLite accepted it
silently, so every login worked in development and every login would have
failed the moment the database moved — found by running the suite against
PostgreSQL, which is why that job exists.
"""


def _pair_key(email: str, ip_address: str) -> str:
    return f"{email}{PAIR_SEPARATOR}{ip_address}"


def _failures(db: DbSession, scope: str, key: str, since: datetime) -> int:
    return db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.scope == scope, LoginAttempt.key == key, LoginAttempt.created_at >= since)
    )


def login_is_throttled(db: DbSession, email: str, ip_address: str | None) -> bool:
    """Block the source that is guessing, not the account being guessed at.

    The decisive counter is per (account, source address). Counting wrong
    guesses against the account alone — which is what this used to do — means
    the counter the owner is measured against is the one an attacker fills, so
    five requests lock a named colleague out and one request every three minutes
    keeps them out indefinitely. Against an address published on the ZMB website
    that is not a theoretical attack, and Reticle holds instrument safety
    procedures that people need to reach.

    The other two counters stay as ceilings rather than tripwires: a much larger
    per-account count still catches a genuinely distributed guess at one known
    account, and the per-address count catches one host spraying a common
    password across many accounts, which neither of the others sees.

    Without a usable source address there is no way to tell the attacker from
    the owner, so only the large per-account ceiling applies; using the tight
    limit there would hand back the lockout through the back door.
    """
    settings = get_settings()
    since = _window_start(settings)

    if ip_address is None:
        return _failures(db, SCOPE_EMAIL, email, since) >= settings.login_max_attempts_per_email

    pair_failures = _failures(db, SCOPE_EMAIL_ADDRESS, _pair_key(email, ip_address), since)
    if pair_failures >= settings.login_max_attempts_per_email_and_ip:
        return True
    if _failures(db, SCOPE_EMAIL, email, since) >= settings.login_max_attempts_per_email:
        return True
    return _failures(db, SCOPE_ADDRESS, ip_address, since) >= settings.login_max_attempts_per_ip


def record_failed_login(db: DbSession, email: str, ip_address: str | None) -> None:
    db.add(LoginAttempt(scope=SCOPE_EMAIL, key=email))
    if ip_address is not None:
        db.add(LoginAttempt(scope=SCOPE_ADDRESS, key=ip_address))
        db.add(LoginAttempt(scope=SCOPE_EMAIL_ADDRESS, key=_pair_key(email, ip_address)))


def clear_failed_logins(db: DbSession, email: str, ip_address: str | None = None) -> None:
    """Clear exactly what proving the password disproves.

    The account's own counters go, including the pair counter for the address
    that just succeeded. The address counter stays: an attacker who owns one
    valid account would otherwise reset the spray limit between every guess.
    """
    conditions = [and_(LoginAttempt.scope == SCOPE_EMAIL, LoginAttempt.key == email)]
    if ip_address is not None:
        conditions.append(
            and_(LoginAttempt.scope == SCOPE_EMAIL_ADDRESS, LoginAttempt.key == _pair_key(email, ip_address))
        )
    db.execute(delete(LoginAttempt).where(or_(*conditions)))


def prune_login_attempts(db: DbSession) -> None:
    db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < _window_start(get_settings())))
