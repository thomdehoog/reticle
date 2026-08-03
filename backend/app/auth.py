"""Who is asking, and whether they are allowed.

Signing in creates a **session**: a row in the database, and a long random token
in a cookie that points at it. The browser sends that cookie on every later
request, this module looks the row up, and the endpoint is handed the ``User``
it belongs to. Nothing else identifies a caller — there is no API key and no
token in a header — so every ``/api`` route ends up here.

Two cookies rather than one, and the second is the part worth understanding.
The session cookie is ``httpOnly``, which means a script on the page cannot read
it — good, but it also means the *browser* sends it automatically, including on
a request some other website provoked. That is cross-site request forgery: a
page a colleague happens to be visiting quietly asks Reticle to delete a guide,
and their cookie makes it work. The defence is a second cookie the page *can*
read, which the frontend copies into the ``X-CSRF-Token`` header; another site
can make the browser send cookies but cannot read them, so it cannot produce the
header. Anything that changes data must present both.

At the bottom are the names a route declares to say who may call it —
``MaybeUser``, ``AnyUser``, ``AuthorUser``, ``AdminUser``. Declaring one is not
optional: ``main.unguarded_endpoints`` walks the whole routing table and a test
fails on anything that neither requires a role nor appears in the list of
endpoints deliberately left open, so adding one means choosing rather than
remembering to.

``MaybeUser`` is the reading public. The corpus is published material and a
login decides who may *change* it, not who may see it, so a route serving
finished public content takes a caller who may be nobody at all.

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


def _warn_about_collapsed_attribution(peer: str) -> None:
    """Say once that the throttle is counting the proxy, not the caller.

    This is the misconfiguration that looks like nothing at all: every request
    reports the proxy's address, so the per-address login limit buckets the
    entire institute and twenty mistyped passwords lock everybody out at once.
    Nothing in the logs says so unless something says so.

    It fires only when attribution really has collapsed — the caller's own
    address has been lost. The shipped multi-facility unit runs uvicorn with
    ``--proxy-headers --forwarded-allow-ips 127.0.0.1``, which rewrites the peer
    address to the forwarded one before any of this code sees it, so on that
    deployment there is nothing to warn about and telling the operator to set
    ``RETICLE_TRUST_FORWARDED_FOR`` would make things worse: with a proxy that
    appends rather than overwrites, the value read back is one the caller chose.
    """
    global _untrusted_forwarding_warned
    if _untrusted_forwarding_warned:
        return
    _untrusted_forwarding_warned = True
    logger.warning(
        "Requests carry X-Forwarded-For, the peer address is still %s, and it is not the address "
        "in the header — so every caller is being attributed to that one address and the "
        "per-address login throttle now covers all of them at once. The fix is to start uvicorn "
        "with --proxy-headers --forwarded-allow-ips <the proxy's address>, which rewrites the peer "
        "address before Reticle sees it. RETICLE_TRUST_FORWARDED_FOR is the last resort: it makes "
        "Reticle read the first entry of the header itself, which a client can write if the proxy "
        "appends to the header rather than overwriting it.",
        peer,
    )


def client_address(request: Request) -> str | None:
    """The address the throttle counts against and the audit trail records.

    ``X-Forwarded-For`` is only consulted when the operator has declared that
    Reticle sits behind a proxy that rewrites it; trusting it unconditionally
    would let any client pick its own throttle bucket.

    Two other places in the application ask a similar-looking question and both
    answer it from the peer address alone, on purpose. ``ratelimit._identify``
    runs before authentication and must not use a value a caller can influence;
    ``observability._client_ip`` records the connection this process accepted,
    which is what a log line is for. This one is the only one that decides
    *responsibility* — whose login attempt, whose audit entry — so it is the
    only one that is allowed to believe a declared proxy.
    """
    forwarded = request.headers.get(FORWARDED_HEADER)
    peer = request.client.host if request.client else None
    if get_settings().trust_forwarded_for:
        if forwarded:
            return parse_ip_address(forwarded.split(",")[0])
    elif forwarded and peer is not None:
        # Only when a real address was forwarded and the peer is somebody else.
        # If uvicorn's own --proxy-headers already rewrote the peer to the
        # forwarded address the two match and attribution is correct, and a
        # header that is not an address at all is evidence of a caller making
        # things up rather than of a proxy nobody configured.
        claimed = parse_ip_address(forwarded.split(",")[0])
        if claimed is not None and claimed != peer:
            _warn_about_collapsed_attribution(peer)
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


def get_reader(
    request: Request,
    db: DbDep,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> User | None:
    """Whoever is reading, signed in or not.

    ZMB's guides are how somebody standing at an instrument finds out how to use
    it, and asking them for an account first is a barrier with nothing behind
    it: the corpus is public and the login exists to decide who may *change* a
    guide.

    So a caller with no session gets ``None`` rather than a refusal. That does
    not weaken anything for a caller who has one — a cookie that is present is
    resolved exactly as ``get_session_row`` resolves it, and a signed-in author
    reading a draft is still the author. What ``None`` must never do is widen
    what is visible, and it cannot: every route taking this asks
    ``visibility.sees_unpublished``, which an anonymous reader fails the same
    way a viewer does, through the same test rather than a second one.

    An expired or forged cookie reads as anonymous instead of as an error, which
    is what a reader wants — a tab left open overnight shows the public site
    again rather than a wall.
    """
    row = resolve_session(db, session_token)
    if row is None or not row.user.is_active:
        return None

    # Every route that takes a reader is a GET, so the CSRF check that guards a
    # write has nothing to do here. Refused rather than assumed: a write that
    # quietly accepted this dependency would accept a session cookie without the
    # header proving this page and not another site sent it.
    if request.method not in SAFE_METHODS:
        raise errors.forbidden("This endpoint does not accept writes.")

    request.state.session_id = row.id
    return row.user


AnyUser = Annotated[User, Depends(get_current_user)]
MaybeUser = Annotated[User | None, Depends(get_reader)]
CurrentSession = Annotated[SessionRow, Depends(get_session_row)]


def require_role(minimum: str):
    """Build a dependency that admits the given role and everything above it."""
    threshold = ROLE_RANK[minimum]

    def dependency(user: AnyUser) -> User:
        if ROLE_RANK[user.role] < threshold:
            raise errors.forbidden(f"This action requires the {minimum} role.")
        return user

    dependency.__name__ = f"require_{minimum}"
    return dependency


AuthorUser = Annotated[User, Depends(require_role("author"))]
AdminUser = Annotated[User, Depends(require_role("admin"))]
