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
from argon2.exceptions import InvalidHashError, VerifyMismatchError, VerificationError
from argon2.low_level import Type
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from .db import utcnow
from .models import LoginAttempt, Session as SessionRow, User
from .settings import Settings, get_settings

SESSION_COOKIE = "reticle_session"
CSRF_COOKIE = "reticle_csrf"
CSRF_HEADER = "X-CSRF-Token"


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
    if not left or not right:
        return False
    return hmac.compare_digest(left, right)


def _window_start(settings: Settings) -> datetime:
    return utcnow() - timedelta(minutes=settings.login_attempt_window_minutes)


def login_is_throttled(db: DbSession, email: str, ip_address: str | None) -> bool:
    """Two independent counters, because they stop different attacks.

    The per-email counter stops a slow distributed guess at one known account;
    the per-address counter stops one host spraying a common password across
    many accounts, which the per-email counter never sees.
    """
    settings = get_settings()
    since = _window_start(settings)

    email_failures = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.scope == "email", LoginAttempt.key == email, LoginAttempt.created_at >= since)
    )
    if email_failures >= settings.login_max_attempts_per_email:
        return True

    if ip_address is None:
        return False
    ip_failures = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.scope == "ip", LoginAttempt.key == ip_address, LoginAttempt.created_at >= since)
    )
    return ip_failures >= settings.login_max_attempts_per_ip


def record_failed_login(db: DbSession, email: str, ip_address: str | None) -> None:
    db.add(LoginAttempt(scope="email", key=email))
    if ip_address is not None:
        db.add(LoginAttempt(scope="ip", key=ip_address))


def clear_failed_logins(db: DbSession, email: str) -> None:
    """Only the account's own counter is cleared on success.

    Clearing the address counter too would let an attacker who owns one valid
    account reset the spray limit between every guess.
    """
    db.execute(delete(LoginAttempt).where(LoginAttempt.scope == "email", LoginAttempt.key == email))


def prune_login_attempts(db: DbSession) -> None:
    db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < _window_start(get_settings())))
