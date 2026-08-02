"""Login, logout and session introspection.

Login is the one mutating endpoint outside the CSRF check, because a request
that establishes a session cannot echo a token it has not been given yet. The
protections that matter for it instead are the SameSite cookie, the dual
throttle and the identical failure response.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from .. import audit, errors
from ..auth import CurrentSession, CurrentUser, DbDep, client_address
from ..models import User
from ..schemas import LoginIn, UserOut, user_out
from ..security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    burn_password_time,
    clear_failed_logins,
    create_session,
    email_fingerprint,
    hash_password,
    login_is_throttled,
    needs_rehash,
    prune_login_attempts,
    record_failed_login,
    revoke_session,
    verify_password,
)
from ..settings import Settings, get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


def set_session_cookies(
    response: Response, token: str, csrf_token: str, settings: Settings
) -> None:
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


@router.post("/login", response_model=UserOut)
def login(payload: LoginIn, request: Request, response: Response, db: DbDep) -> UserOut:
    settings = get_settings()
    email = payload.email.strip().lower()
    address = client_address(request)

    if login_is_throttled(db, email, address):
        audit.record(
            db,
            action="auth.login_throttled",
            entity_type="auth",
            ip_address=address,
            detail={"emailDigest": email_fingerprint(email)},
        )
        db.commit()
        raise errors.rate_limited()

    user = db.scalars(select(User).where(User.email == email)).one_or_none()
    authenticated = False
    if user is None or not user.is_active:
        burn_password_time()
    else:
        authenticated = verify_password(user.password_hash, payload.password)

    if not authenticated:
        record_failed_login(db, email, address)
        audit.record(
            db,
            action="auth.login_failed",
            entity_type="auth",
            actor_id=user.id if user is not None else None,
            ip_address=address,
            detail={"emailDigest": email_fingerprint(email)},
        )
        db.commit()
        raise errors.invalid_credentials()

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    clear_failed_logins(db, email, address)
    prune_login_attempts(db)
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
    db.commit()

    set_session_cookies(response, token, csrf_token, settings)
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
