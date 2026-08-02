"""Authentication and authorisation dependencies.

Every ``/api`` route except the login and the health probe declares one of the
aliases at the bottom of this module, and ``main`` refuses to start if a route
ever forgets. Role checks live here rather than inside handlers so that adding
an endpoint means choosing a role, not remembering one.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Annotated

from fastapi import Cookie, Depends, Request
from sqlalchemy.orm import Session as DbSession

from . import errors
from .db import get_db
from .models import ROLE_RANK, User
from .models import Session as SessionRow
from .security import CSRF_COOKIE, SESSION_COOKIE, constant_time_equals, resolve_session
from .settings import get_settings

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

FORWARDED_HEADER = "x-forwarded-for"

DbDep = Annotated[DbSession, Depends(get_db)]

logger = logging.getLogger(__name__)

_untrusted_forwarding_warned = False


def parse_ip_address(value: str | None) -> str | None:
    """Accept a candidate address only if it really is one.

    ``X-Forwarded-For`` stays client-supplied even where a proxy is declared: a
    proxy that appends rather than overwrites leaves whatever the caller sent
    sitting in front of its own entry. Every consumer of this value writes it
    down — ``login_attempts.key``, ``audit_log.ip_address``,
    ``sessions.ip_address`` — so anything that is not an IP address is dropped
    here rather than persisted, which is also what keeps a 45-character column
    from being handed a kilobyte of attacker-chosen text.
    """
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def _warn_about_untrusted_forwarding(peer: str | None) -> None:
    """Say once that the throttle is counting the proxy, not the caller.

    This is the misconfiguration that looks like nothing at all. With
    ``trust_forwarded_for`` off behind a reverse proxy — which is the deployment
    the README describes — every request reports the proxy's address, so the
    per-address login limit buckets the entire institute and twenty mistyped
    passwords lock everybody out at once. Nothing in the logs says so unless
    something says so.
    """
    global _untrusted_forwarding_warned
    if _untrusted_forwarding_warned:
        return
    _untrusted_forwarding_warned = True
    logger.warning(
        "Requests carry X-Forwarded-For but RETICLE_TRUST_FORWARDED_FOR is false, so every caller is "
        "being attributed to %s and the per-address login throttle now covers all of them at once. "
        "Set RETICLE_TRUST_FORWARDED_FOR=true if — and only if — that proxy overwrites the header "
        "rather than appending to it.",
        peer or "the peer address",
    )


def client_address(request: Request) -> str | None:
    """The address the throttle counts against and the audit trail records.

    ``X-Forwarded-For`` is only consulted when the operator has declared that
    Reticle sits behind a proxy that rewrites it; trusting it unconditionally
    would let any client pick its own throttle bucket.
    """
    forwarded = request.headers.get(FORWARDED_HEADER)
    if get_settings().trust_forwarded_for:
        if forwarded:
            return parse_ip_address(forwarded.split(",")[0])
    elif forwarded:
        _warn_about_untrusted_forwarding(request.client.host if request.client else None)
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
