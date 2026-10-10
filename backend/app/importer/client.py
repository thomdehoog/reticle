"""The one place the importer talks HTTP.

Everything the export sends goes through :class:`DozukiClient`, for three
reasons. Politeness lives here: a pause between requests, and patience when the
server says to slow down. So does persistence: a timeout, a 429 or a 5xx is
retried with a growing delay, honouring ``Retry-After``. And so does the one
rule about credentials: the token is attached to requests for the API host and
to nothing else. Media files are served from other hosts (a CDN, an object
store) by plain URL, and a token sent there would be a token handed to a third
party.

The transport is injectable so the tests run without a network.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from . import TOOL_NAME, TOOL_VERSION

RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
MAX_BACKOFF_SECONDS = 120.0
DOWNLOAD_CHUNK_BYTES = 256 * 1024


class ClientError(Exception):
    """A request that did not produce what was asked for."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class AuthenticationError(ClientError):
    """The site refused the credentials or the token. Nothing later can work."""


class NotFound(ClientError):
    """The item does not exist, or is not visible to this caller."""


@dataclass(frozen=True)
class Download:
    path: Path
    sha256: str
    size: int
    content_type: str


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
        self._http = httpx.Client(
            transport=transport,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": f"{TOOL_NAME}/{TOOL_VERSION} (content export by the site owner)", "Accept": "application/json"},
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "DozukiClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def authenticated(self) -> bool:
        return bool(self.token or self.cookie)

    # ------------------------------------------------------------ plumbing

    def _headers(self, url: str) -> dict[str, str]:
        """Credentials for the API host only; see the module docstring."""
        if (urlsplit(url).hostname or "").lower() != self.host:
            return {}
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

    def _fail(self, response: httpx.Response, what: str) -> ClientError:
        status = response.status_code
        if status == 401:
            if self.authenticated and (response.request.url.host or "").lower() == self.host:
                return AuthenticationError(
                    f"The site rejected the {'API token' if self.token else 'session cookie'} (HTTP 401). It may have "
                    "expired or been revoked; obtain a new one and run the export again — it resumes where it stopped.",
                    status,
                )
            return NotFound(f"{what}: not visible without signing in (HTTP 401)", status)
        if status in {403, 404, 410}:
            return NotFound(f"{what}: not found or not visible to this account (HTTP {status})", status)
        return ClientError(f"{what}: HTTP {status}", status)

    def _send(self, method: str, url: str, what: str, **kwargs: Any) -> httpx.Response:
        """One request, retried while the failure looks temporary."""
        attempt = 0
        while True:
            if self.delay and self.requests_made:
                self.sleep(self.delay)
            self.requests_made += 1
            response: httpx.Response | None = None
            problem: str
            try:
                response = self._http.request(method, url, headers=self._headers(url), **kwargs)
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

    def get(self, path: str, params: dict[str, Any] | None = None) -> tuple[Any, bytes]:
        """``GET`` an API path; returns the decoded JSON and the exact bytes received."""
        what = f"GET {path}"
        response = self._send("GET", f"{self.base}{path}", what, params=params)
        if response.status_code != 200:
            raise self._fail(response, what)
        body = response.content
        try:
            return json.loads(body), body
        except ValueError as error:
            raise ClientError(f"{what}: the response is not JSON") from error

    def download(self, url: str, destination: Path) -> Download:
        """Stream a file to ``destination``, atomically, hashing as it goes.

        The bytes land in a ``.part`` file beside the target and are renamed
        into place only when complete, so an interrupted run never leaves a
        truncated file that a later run would take for a finished one.
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
                with self._http.stream("GET", url, headers=self._headers(url)) as response:
                    status = response.status_code
                    if status == 200:
                        digest = hashlib.sha256()
                        size = 0
                        with partial.open("wb") as output:
                            for chunk in response.iter_bytes(DOWNLOAD_CHUNK_BYTES):
                                digest.update(chunk)
                                size += len(chunk)
                                output.write(chunk)
                            output.flush()
                            os.fsync(output.fileno())
                        os.replace(partial, destination)
                        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                        return Download(destination, digest.hexdigest(), size, content_type)
                    if status not in RETRY_STATUSES:
                        raise self._fail(response, what)
                    problem = f"HTTP {status}"
            except httpx.TransportError as error:
                problem = type(error).__name__
            finally:
                partial.unlink(missing_ok=True)
            if attempt >= self.retries:
                raise ClientError(f"{what}: {problem} after {attempt + 1} attempts", status)
            wait = self._backoff(attempt, response if status is not None else None)
            self.log(f"  {what}: {problem}; retrying in {wait:.0f}s")
            self.sleep(wait)
            attempt += 1
