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
from functools import lru_cache
from typing import Annotated

from fastapi import Cookie, Depends, Request
from sqlalchemy.orm import Session as DbSession

from . import errors
from .db import get_db
from .models import ROLE_RANK, Session as SessionRow, User
from .security import CSRF_COOKIE, SESSION_COOKIE, constant_time_equals, resolve_session
from .settings import get_settings

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

FORWARDED_HEADER = "x-forwarded-for"

DbDep = Annotated[DbSession, Depends(get_db)]

logger = logging.getLogger(__name__)

_untrusted_forwarding_warned = False


def parse_ip_address(value: str | None) -> str | None:
    """Accept a candidate address only if it really is one.

    ``X-Forwarded-For`` is client-supplied text until proven otherwise. Every
    consumer of this value writes it down — ``login_attempts.key``,
    ``audit_log.ip_address``, ``sessions.ip_address`` — so anything that is not
    an IP address is dropped here rather than persisted, which is also what
    keeps a 45-character column from being handed a kilobyte of attacker-chosen
    text.
    """
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


@lru_cache(maxsize=8)
def _networks(entries: tuple[str, ...]) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    return tuple(ipaddress.ip_network(entry, strict=False) for entry in entries)


def is_trusted_proxy(address: str | None) -> bool:
    """Whether an address is one of the proxies the operator has named."""
    parsed = parse_ip_address(address)
    if parsed is None:
        return False
    candidate = ipaddress.ip_address(parsed)
    networks = _networks(tuple(get_settings().trusted_proxies))
    return any(candidate.version == network.version and candidate in network for network in networks)


def _warn_about_untrusted_forwarding(peer: str) -> None:
    """Say once that the throttle is counting the proxy, not the caller.

    This is the misconfiguration that looks like nothing at all. Behind a
    reverse proxy that Reticle has not been told about, every request reports
    the proxy's address, so the per-source login limit buckets the entire
    institute and twenty mistyped passwords lock everybody out at once. Nothing
    in the logs says so unless something says so.
    """
    global _untrusted_forwarding_warned
    if _untrusted_forwarding_warned:
        return
    _untrusted_forwarding_warned = True
    logger.warning(
        "Requests from %s carry X-Forwarded-For, but that address is not in RETICLE_TRUSTED_PROXIES, so "
        "the header is ignored and every caller is being attributed to %s. If that is your reverse proxy, "
        "set RETICLE_TRUSTED_PROXIES=%s.",
        peer,
        peer,
        peer,
    )


def client_address(request: Request) -> str | None:
    """The address the throttle counts against and the audit trail records.

    ``X-Forwarded-For`` is believed only when the connection itself comes from a
    proxy the operator has listed in ``RETICLE_TRUSTED_PROXIES``, and then it is
    read from the right. Each proxy appends the address it saw, so the rightmost
    entries are the ones written by machinery we trust and everything to their
    left is whatever the client chose to send. Walking leftwards past the
    trusted hops and stopping at the first address that is not one of them
    yields the real caller whether the proxy overwrites the header or appends
    to it — which matters, because appending is nginx's default and taking the
    leftmost entry there means taking the attacker's word for who they are.

    That in turn is what keeps the login throttle honest in both directions: a
    client cannot mint itself a fresh bucket per request, and cannot spend a
    colleague's allowance by claiming their address.
    """
    peer = request.client.host if request.client else None
    forwarded = ",".join(request.headers.getlist(FORWARDED_HEADER))
    if not forwarded:
        return peer

    if not is_trusted_proxy(peer):
        parsed_peer = parse_ip_address(peer)
        if parsed_peer is not None and ipaddress.ip_address(parsed_peer).is_loopback:
            _warn_about_untrusted_forwarding(parsed_peer)
        return peer

    for hop in reversed(forwarded.split(",")):
        address = parse_ip_address(hop)
        if address is None:
            break
        if not is_trusted_proxy(address):
            return address
    return peer


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
