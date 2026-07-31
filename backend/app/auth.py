"""Authentication and authorisation dependencies.

Every ``/api`` route except the login and the health probe declares one of the
aliases at the bottom of this module, and ``main`` refuses to start if a route
ever forgets. Role checks live here rather than inside handlers so that adding
an endpoint means choosing a role, not remembering one.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, Request
from sqlalchemy.orm import Session as DbSession

from . import errors
from .db import get_db
from .models import ROLE_RANK, Session as SessionRow, User
from .security import CSRF_COOKIE, SESSION_COOKIE, constant_time_equals, resolve_session
from .settings import get_settings

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

DbDep = Annotated[DbSession, Depends(get_db)]


def client_address(request: Request) -> str | None:
    """The address the throttle counts against.

    ``X-Forwarded-For`` is only consulted when the operator has declared that
    Reticle sits behind a proxy that rewrites it; trusting it unconditionally
    would let any client pick its own throttle bucket.
    """
    if get_settings().trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def get_session_row(
    request: Request,
    db: DbDep,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> SessionRow:
    row = resolve_session(db, session_token)
    if row is None:
        raise errors.not_authenticated()
    if not row.user.is_active:
        raise errors.not_authenticated()

    if request.method not in SAFE_METHODS:
        presented = request.cookies.get(CSRF_COOKIE)
        if not constant_time_equals(presented, row.csrf_token):
            raise errors.forbidden("CSRF token does not match this session.")

    request.state.session_id = row.id
    return row


def get_current_user(session_row: Annotated[SessionRow, Depends(get_session_row)]) -> User:
    return session_row.user


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentSession = Annotated[SessionRow, Depends(get_session_row)]


def require_role(minimum: str):
    """Build a dependency that admits the given role and everything above it."""
    threshold = ROLE_RANK[minimum]

    def dependency(user: CurrentUser) -> User:
        if ROLE_RANK[user.role] < threshold:
            raise errors.forbidden(f"This action requires the {minimum} role.")
        return user

    dependency.__name__ = f"require_{minimum}"
    return dependency


AnyUser = CurrentUser
AuthorUser = Annotated[User, Depends(require_role("author"))]
AdminUser = Annotated[User, Depends(require_role("admin"))]
