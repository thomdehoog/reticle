"""The one place the importer talks HTTP.

Everything the export sends goes through :class:`DozukiClient`, for three
reasons. Politeness lives here: a pause between requests, and patience when the
server says to slow down. So does persistence: a timeout, a 429 or a 5xx is
retried with a growing delay, honouring ``Retry-After``. And so does the one
rule about credentials: only the API host ever sees them.

There are two HTTP clients for that reason. The *API client* talks to the site
and carries the token, the session cookie and the app id. It follows a redirect
only within that host. The *bare client* carries nothing that identifies the
caller — no token, no cookie, no app id — and is used for everything else:
media downloads, and the anonymous listing pass that records what the site
shows to visitors who are not signed in.

Media URLs come out of API payloads, so a download is treated as a request to
an address somebody else chose. It must be ``https``; at most three redirects
are followed and every hop is checked again; a host that resolves to a private,
loopback or link-local address is refused, because the export runs inside the
facility network and must not be steerable at what is reachable from there; the
size is capped while the bytes arrive; and the declared type has to be the kind
of file that was asked for.

The transport and the name lookup are injectable so the tests run without a
network.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import httpx

from . import TOOL_NAME, TOOL_VERSION

RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
MAX_BACKOFF_SECONDS = 120.0
DOWNLOAD_CHUNK_BYTES = 256 * 1024
MAX_REDIRECTS = 3
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
MAX_IMAGE_BYTES = 200 * 1024 * 1024
MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024
GENERIC_CONTENT_TYPES = frozenset({"", "application/octet-stream", "binary/octet-stream", "application/binary"})
"""What an object store says when it was never told what it holds."""

SIGNATURES: tuple[tuple[bytes, int, str], ...] = (
    (b"\xff\xd8\xff", 0, "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", 0, "image/png"),
    (b"GIF87a", 0, "image/gif"),
    (b"GIF89a", 0, "image/gif"),
    (b"WEBP", 8, "image/webp"),
    (b"BM", 0, "image/bmp"),
    (b"II*\x00", 0, "image/tiff"),
    (b"MM\x00*", 0, "image/tiff"),
    (b"ftyp", 4, "video/mp4"),
    (b"\x1a\x45\xdf\xa3", 0, "video/webm"),
)
"""Leading bytes, their offset, and the type they mean. Only consulted when the
server did not say what it was sending."""


class ClientError(Exception):
    """A request that did not produce what was asked for."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class AuthenticationError(ClientError):
    """The site refused the credentials or the token. Nothing later can work."""


class NotFound(ClientError):
    """The item does not exist, or is not visible to this caller."""


class UnsafeAddress(ClientError):
    """A URL the importer will not fetch: not https, or a host it must not reach."""


@dataclass(frozen=True)
class Download:
    path: Path
    sha256: str
    size: int
    content_type: str
    """The type the file is taken to be: what the server declared, or, where it
    declared nothing useful, what the first bytes show. Empty if neither says."""
    declared_type: str = ""
    final_url: str = ""


def sniff_content_type(head: bytes) -> str:
    for signature, offset, content_type in SIGNATURES:
        if head[offset : offset + len(signature)] == signature:
            return content_type
    return ""


def resolve_host(host: str) -> list[str]:
    """Every address a host name stands for, as the system resolver sees it."""
    return sorted({str(info[4][0]) for info in socket.getaddrinfo(host, None)})


def is_public_address(address: str) -> bool:
    """Whether an IP address is somewhere on the public internet.

    Everything else is refused for downloads: loopback, the private ranges,
    link-local (which is where a cloud metadata service lives), carrier-grade
    NAT, multicast, and the unspecified address. An IPv4 address wrapped in
    IPv6 is judged as the IPv4 address it is.
    """
    try:
        parsed = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    return parsed.is_global and not parsed.is_multicast


def api_base(site: str) -> str:
    """``zmb.dozuki.com`` or a full URL, as the versioned API root."""
    site = site.strip()
    if "://" not in site:
        site = f"https://{site}"
    parts = urlsplit(site)
    if not parts.hostname:
        raise ValueError(f"{site!r} is not a site address")
    return f"{parts.scheme}://{parts.netloc}/api/2.0"


def path_segment(value: str) -> str:
    """A title or id as one URL path segment."""
    return quote(str(value), safe="")


def retry_after_seconds(value: str | None, now: Callable[[], datetime] | None = None) -> float | None:
    """``Retry-After`` as seconds, from either of its two legal forms."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    current = now() if now is not None else datetime.now(timezone.utc)
    return max(0.0, (moment - current).total_seconds())


class DozukiClient:
    def __init__(
        self,
        site: str,
        *,
        token: str | None = None,
        app_id: str | None = None,
        cookie: str | None = None,
        transport: httpx.BaseTransport | None = None,
        delay: float = 0.25,
        retries: int = 5,
        timeout: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] | None = None,
        resolve: Callable[[str], list[str]] = resolve_host,
        allow_private_media_hosts: bool = False,
    ) -> None:
        self.base = api_base(site)
        self.host = (urlsplit(self.base).hostname or "").lower()
        self.token = token
        self.app_id = app_id
        self.cookie = cookie
        self.delay = max(0.0, delay)
        self.retries = max(0, retries)
        self.sleep = sleep
        self.log = log or (lambda message: None)
        self.requests_made = 0
        self.resolve = resolve
        self.allow_private_media_hosts = allow_private_media_hosts
        self._checked_hosts: dict[str, str | None] = {}
        agent = f"{TOOL_NAME}/{TOOL_VERSION} (content export by the site owner)"
        # Redirects are followed by hand in both clients, one checked hop at a
        # time: httpx would carry the app id along to wherever a redirect points.
        self._http = httpx.Client(
            transport=transport, timeout=timeout, follow_redirects=False, headers={"User-Agent": agent, "Accept": "application/json"}
        )
        self._bare = httpx.Client(transport=transport, timeout=timeout, follow_redirects=False, headers={"User-Agent": agent})

    def close(self) -> None:
        self._http.close()
        self._bare.close()

    def __enter__(self) -> "DozukiClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def authenticated(self) -> bool:
        return bool(self.token or self.cookie)

    # ------------------------------------------------------------ plumbing

    def _headers(self) -> dict[str, str]:
        """The credentials. Only :meth:`_api_request` asks, and it only ever asks the API host."""
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"api {self.token}"
        elif self.cookie:
            headers["Cookie"] = self.cookie
        if self.app_id:
            headers["X-App-Id"] = self.app_id
        return headers

    def _backoff(self, attempt: int, response: httpx.Response | None) -> float:
        wait = min(MAX_BACKOFF_SECONDS, 2.0**attempt)
        if response is not None:
            asked = retry_after_seconds(response.headers.get("Retry-After"))
            if asked is not None:
                wait = min(max(wait, asked), MAX_BACKOFF_SECONDS * 5)
        return wait

    def _fail(self, response: httpx.Response, what: str, credentials_sent: bool = True) -> ClientError:
        status = response.status_code
        if status == 401:
            if credentials_sent and self.authenticated and (response.request.url.host or "").lower() == self.host:
                return AuthenticationError(
                    f"The site rejected the {'API token' if self.token else 'session cookie'} (HTTP 401). It may have "
                    "expired or been revoked; obtain a new one and run the export again — it resumes where it stopped.",
                    status,
                )
            return NotFound(f"{what}: not visible without signing in (HTTP 401)", status)
        if status in {403, 404, 410}:
            return NotFound(f"{what}: not found or not visible to this account (HTTP {status})", status)
        return ClientError(f"{what}: HTTP {status}", status)

    def _api_request(self, method: str, url: str, what: str, anonymous: bool, **kwargs: Any) -> httpx.Response:
        """One API request, following redirects only while they stay on the API host.

        The credentials are worked out again for every hop, and a redirect to
        any other host is an error rather than something to follow: the site's
        own API has no reason to send its caller elsewhere, and the caller is
        holding the site's token.
        """
        for _ in range(MAX_REDIRECTS + 1):
            if anonymous:
                self._bare.cookies.clear()
                response = self._bare.request(method, url, headers={"Accept": "application/json"}, **kwargs)
            else:
                # No cookie jar either: what goes out is what _headers decides, nothing a response planted.
                self._http.cookies.clear()
                response = self._http.request(method, url, headers=self._headers(), **kwargs)
            target = response.headers.get("Location")
            if method != "GET" or response.status_code not in REDIRECT_STATUSES or not target:
                return response
            following = urljoin(url, target)
            parts = urlsplit(following)
            if (parts.hostname or "").lower() != self.host or parts.scheme not in {"https", urlsplit(self.base).scheme}:
                raise ClientError(f"{what}: the site redirected to {parts.scheme}://{parts.hostname}, which is not the API host; not followed")
            url, kwargs = following, {}
        raise ClientError(f"{what}: more than {MAX_REDIRECTS} redirects")

    def _send(self, method: str, url: str, what: str, anonymous: bool = False, **kwargs: Any) -> httpx.Response:
        """One request, retried while the failure looks temporary."""
        attempt = 0
        while True:
            if self.delay and self.requests_made:
                self.sleep(self.delay)
            self.requests_made += 1
            response: httpx.Response | None = None
            problem: str
            try:
                response = self._api_request(method, url, what, anonymous, **kwargs)
            except httpx.TransportError as error:
                problem = f"{type(error).__name__}"
            else:
                if response.status_code not in RETRY_STATUSES:
                    return response
                problem = f"HTTP {response.status_code}"
            if attempt >= self.retries:
                raise ClientError(f"{what}: {problem} after {attempt + 1} attempts", response.status_code if response is not None else None)
            wait = self._backoff(attempt, response)
            self.log(f"  {what}: {problem}; retrying in {wait:.0f}s")
            self.sleep(wait)
            attempt += 1

    # ------------------------------------------------------------ API

    def login(self, email: str, password: str) -> None:
        """Exchange an email and password for a token; nothing is stored on disk."""
        response = self._send("POST", f"{self.base}/user/token", "sign-in", json={"email": email, "password": password})
        if response.status_code not in {200, 201}:
            raise AuthenticationError(
                f"Signing in failed (HTTP {response.status_code}). On a site that signs in through single sign-on "
                "an email and password cannot work; see docs/IMPORT.md for the alternatives.",
                response.status_code,
            )
        try:
            token = response.json().get("authToken")
        except (ValueError, AttributeError):
            token = None
        if not token:
            raise AuthenticationError("Signing in returned no authToken.", response.status_code)
        self.token = str(token)

    def get(self, path: str, params: dict[str, Any] | None = None, *, anonymous: bool = False) -> tuple[Any, bytes]:
        """``GET`` an API path; returns the decoded JSON and the exact bytes received.

        ``anonymous`` sends the request through the bare client, with no
        credentials at all: it is how the export finds out what the site shows
        to a visitor who is not signed in.
        """
        what = f"GET {path}" + (" (anonymously)" if anonymous else "")
        response = self._send("GET", f"{self.base}{path}", what, anonymous, params=params)
        if response.status_code != 200:
            raise self._fail(response, what, credentials_sent=not anonymous)
        body = response.content
        try:
            return json.loads(body), body
        except ValueError as error:
            raise ClientError(f"{what}: the response is not JSON") from error

    # ------------------------------------------------------------ downloads

    def check_media_url(self, url: str) -> None:
        """Refuse a download address that is not https or not on the public internet.

        Called for the first URL and again for every redirect target. A host is
        looked up once per run; a name that cannot be looked up is refused too,
        since nothing can then be said about where it leads.
        """
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not host:
            raise UnsafeAddress(f"refusing to download {url[:200]!r}: media is fetched over https only")
        if self.allow_private_media_hosts:
            return
        if host not in self._checked_hosts:
            self._checked_hosts[host] = self._host_problem(host)
        reason = self._checked_hosts[host]
        if reason is not None:
            raise UnsafeAddress(
                f"refusing to download from {host}: {reason}. Media hosts must be on the public internet; "
                "pass --allow-private-media-hosts if this site really serves its media from an internal address "
                "or the downloads go through a proxy that does the name lookup."
            )

    def _host_problem(self, host: str) -> str | None:
        """Why a host must not be downloaded from, or ``None`` if it may be."""
        try:
            ipaddress.ip_address(host)
            addresses = [host]
        except ValueError:
            try:
                addresses = self.resolve(host)
            except OSError as error:
                return f"its address could not be looked up ({type(error).__name__})"
        if not addresses:
            return "it has no address"
        private = [address for address in addresses if not is_public_address(address)]
        return f"it resolves to a non-public address ({private[0]})" if private else None

    def _open_media(self, url: str, what: str) -> httpx.Response:
        """Send the download request and return the open response of the last hop.

        No credential of any kind goes out here: the bare client has none, and
        its cookie jar is emptied before each request so that nothing a media
        host set earlier is replayed either.
        """
        for _ in range(MAX_REDIRECTS + 1):
            self.check_media_url(url)
            self._bare.cookies.clear()
            response = self._bare.send(self._bare.build_request("GET", url, headers={"Accept": "*/*"}), stream=True)
            target = response.headers.get("Location")
            if response.status_code not in REDIRECT_STATUSES or not target:
                return response
            response.close()
            url = urljoin(url, target)
        raise ClientError(f"{what}: more than {MAX_REDIRECTS} redirects")

    def download(self, url: str, destination: Path, *, expect: str | None = None, max_bytes: int | None = None) -> Download:
        """Stream a file to ``destination``, atomically, hashing as it goes.

        The bytes land in a ``.part`` file beside the target and are renamed
        into place only when complete, so an interrupted run never leaves a
        truncated file that a later run would take for a finished one.

        ``expect`` is ``"image"`` or ``"video"``: a response declared as
        anything else — a login page, an error document — is refused before its
        body is read. ``max_bytes`` is enforced on the bytes that actually
        arrive, not on what ``Content-Length`` promises.
        """
        what = f"download {urlsplit(url).path.rsplit('/', 1)[-1] or url}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        attempt = 0
        while True:
            if self.delay and self.requests_made:
                self.sleep(self.delay)
            self.requests_made += 1
            status: int | None = None
            response: httpx.Response | None = None
            try:
                response = self._open_media(url, what)
                status = response.status_code
                if status == 200:
                    return self._receive(response, what, destination, partial, expect, max_bytes)
                if status not in RETRY_STATUSES:
                    raise self._fail(response, what, credentials_sent=False)
                problem = f"HTTP {status}"
            except httpx.TransportError as error:
                problem = type(error).__name__
            finally:
                if response is not None:
                    response.close()
                partial.unlink(missing_ok=True)
            if attempt >= self.retries:
                raise ClientError(f"{what}: {problem} after {attempt + 1} attempts", status)
            wait = self._backoff(attempt, response if status is not None else None)
            self.log(f"  {what}: {problem}; retrying in {wait:.0f}s")
            self.sleep(wait)
            attempt += 1

    @staticmethod
    def _receive(response: httpx.Response, what: str, destination: Path, partial: Path, expect: str | None, max_bytes: int | None) -> Download:
        declared = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if expect is not None and declared not in GENERIC_CONTENT_TYPES and not declared.startswith(f"{expect}/"):
            raise ClientError(f"{what}: the server sent {declared}, not {'an image' if expect == 'image' else f'a {expect}'}; not kept")
        limit_text = f"{max_bytes / (1024 * 1024):.0f} MB" if max_bytes is not None else ""
        announced = response.headers.get("Content-Length", "")
        if max_bytes is not None and announced.isdigit() and int(announced) > max_bytes:
            raise ClientError(f"{what}: the file is {int(announced)} bytes, over the limit of {limit_text}; not downloaded")
        digest = hashlib.sha256()
        size = 0
        head = b""
        with partial.open("wb") as output:
            for chunk in response.iter_bytes(DOWNLOAD_CHUNK_BYTES):
                size += len(chunk)
                if max_bytes is not None and size > max_bytes:
                    raise ClientError(f"{what}: the file is larger than the limit of {limit_text}; download stopped")
                if len(head) < 16:
                    head += chunk[: 16 - len(head)]
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        os.replace(partial, destination)
        content_type = sniff_content_type(head) if declared in GENERIC_CONTENT_TYPES else declared
        return Download(destination, digest.hexdigest(), size, content_type, declared, str(response.url))
