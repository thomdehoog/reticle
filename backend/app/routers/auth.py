"""Login, logout and session introspection.

Login is the one mutating endpoint outside the CSRF check, because a request
that establishes a session cannot echo a token it has not been given yet. The
protections that matter for it instead are the SameSite cookie, the dual
throttle and the identical failure response.

The throttle is built so that it cannot be turned on a colleague: see
``security.login_is_throttled`` for how a browser the account has used before
is kept out of reach of everybody else's wrong guesses.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .. import audit, errors
from ..auth import CurrentSession, CurrentUser, DbDep, client_address
from ..db import utcnow
from ..models import AuditLog, User
from ..schemas import LoginIn, UserOut, user_out
from ..security import (
    CSRF_COOKIE,
    DEVICE_COOKIE,
    DEVICE_COOKIE_MAX_AGE_SECONDS,
    SESSION_COOKIE,
    LoginSubject,
    DEVICE_TOKEN_REFRESH_SECONDS,
    burn_password_time,
    create_session,
    device_token_age,
    email_fingerprint,
    forgive_login_attempts,
    hash_password,
    login_is_throttled,
    needs_rehash,
    new_device_token,
    prune_if_due,
    record_login_attempt,
    revoke_session,
    verify_password,
)
from ..settings import Settings, get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


def set_session_cookies(response: Response, token: str, csrf_token: str, settings: Settings) -> None:
    max_age = settings.session_lifetime_hours * 3600
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        path="/",
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        path="/",
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=False,
        samesite="lax",
    )


def clear_session_cookies(response: Response, settings: Settings) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", domain=settings.cookie_domain)


def set_device_cookie(response: Response, token: str, settings: Settings) -> None:
    """Remember that this browser has signed in to this account.

    Scoped to the authentication endpoints because nothing else reads it, and
    deliberately left in place at logout: its whole purpose is to be there the
    next time somebody signs in.
    """
    response.set_cookie(
        DEVICE_COOKIE,
        token,
        max_age=DEVICE_COOKIE_MAX_AGE_SECONDS,
        path="/api/auth",
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _audit_throttled_once(db: DbSession, address: str | None, email: str) -> None:
    """Record that a source hit the throttle, once per window rather than per request.

    A throttled request is by definition one of many. Writing an audit row for
    each would let anybody who can reach the login form grow the audit table
    without limit, at exactly the moment the trail is most worth reading.
    """
    since = utcnow() - timedelta(minutes=get_settings().login_attempt_window_minutes)
    already = db.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.action == "auth.login_throttled",
            AuditLog.ip_address == address,
            AuditLog.created_at >= since,
        )
    )
    if already:
        return
    audit.record(
        db,
        action="auth.login_throttled",
        entity_type="auth",
        ip_address=address,
        detail={"emailDigest": email_fingerprint(email)},
    )


@router.post("/login", response_model=UserOut)
def login(payload: LoginIn, request: Request, response: Response, db: DbDep) -> UserOut:
    """Check a password, in three short transactions around one slow computation.

    The attempt is counted and committed first, the password is verified with no
    transaction open, and the outcome is written afterwards. Argon2 is slow on
    purpose; holding the database's write lock while it runs would let a handful
    of concurrent sign-ins stall every autosave in the building.
    """
    settings = get_settings()
    email = payload.email.strip().lower()
    address = client_address(request)
    device_token = request.cookies.get(DEVICE_COOKIE)

    # The account is looked up first because a device cookie is only as good as
    # the credentials it was earned with: it is checked against the account's
    # present epoch, and against nothing at all when the account is unknown or
    # switched off. Either way the request below is throttled, and refused when
    # over the limit, before any password hashing is done — for a real account
    # and for the decoy alike.
    user = db.scalars(select(User).where(User.email == email)).one_or_none()
    user_id = user.id if user is not None else None
    active = user is not None and user.is_active
    stored_hash = user.password_hash if active else None
    auth_epoch = user.auth_epoch if active else None
    subject = LoginSubject.of(email, address, device_token, auth_epoch)

    prune_if_due(db)
    if login_is_throttled(db, subject):
        _audit_throttled_once(db, address, email)
        db.commit()
        raise errors.rate_limited()

    attempt_ids = record_login_attempt(db, subject)
    db.commit()

    if stored_hash is None:
        burn_password_time()
        authenticated = False
    else:
        authenticated = verify_password(stored_hash, payload.password)

    user = db.get(User, user_id) if authenticated else None
    if user is None or not user.is_active:
        audit.record(
            db,
            action="auth.login_failed",
            entity_type="auth",
            actor_id=user_id,
            ip_address=address,
            detail={"emailDigest": email_fingerprint(email)},
        )
        db.commit()
        raise errors.invalid_credentials()

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    forgive_login_attempts(db, subject, attempt_ids)
    session_row, token = create_session(db, user, address, request.headers.get("user-agent"))
    audit.record(
        db,
        action="auth.login",
        entity_type="auth",
        actor=user,
        entity_id=session_row.id,
        ip_address=address,
    )
    csrf_token = session_row.csrf_token
    body = user_out(user)
    # Read again rather than reused from above: the password may have been
    # changed while this one was being verified, and the cookie has to be
    # signed for the epoch the account is in now.
    current_epoch = user.auth_epoch
    db.commit()

    set_session_cookies(response, token, csrf_token, settings)
    age = device_token_age(device_token)
    if subject.device is None or age is None or age > DEVICE_TOKEN_REFRESH_SECONDS:
        set_device_cookie(response, new_device_token(email, current_epoch), settings)
    return body


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def logout(request: Request, db: DbDep, session_row: CurrentSession) -> Response:
    revoke_session(session_row)
    audit.record(
        db,
        action="auth.logout",
        entity_type="auth",
        actor_id=session_row.user_id,
        entity_id=session_row.id,
        ip_address=client_address(request),
    )
    db.commit()

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(response, get_settings())
    return response


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return user_out(user)
