"""Shared test harness for the Reticle backend.

Every test gets a private in-memory database and a private media directory.
That isolation is not cosmetic: the login throttle, the session table and the
uploaded files are all persistent state, so sharing a database between tests
would make the suite order-dependent and would let one test's failed logins
lock another test out.

The environment is configured before ``app`` is imported because settings are
read once and cached; the values here are deliberately weak (cheap Argon2
parameters, an insecure cookie flag) so the suite stays fast and so cookies
survive the plain-HTTP transport that ``TestClient`` uses.

``RETICLE_ENV_FILE`` is blanked first. A developer's ``.env`` sitting next to
the code would otherwise feed real configuration into the suite, which turns a
passing run into a statement about that developer's machine.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from io import BytesIO
from typing import Any

os.environ["RETICLE_ENV_FILE"] = ""
os.environ["RETICLE_SECRET_KEY"] = "test-secret-key-do-not-use-in-production"
os.environ["RETICLE_DATABASE_URL"] = "sqlite://"
os.environ["RETICLE_COOKIE_SECURE"] = "false"
os.environ["RETICLE_ARGON2_TIME_COST"] = "1"
os.environ["RETICLE_ARGON2_MEMORY_COST_KIB"] = "8"
os.environ["RETICLE_ARGON2_PARALLELISM"] = "1"

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Category, User
from app.security import hash_password
from app.settings import get_settings

TEST_PASSWORD = "Reticle-Test-Passphrase-9"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class ApiClient:
    """A ``TestClient`` that behaves like the browser the API expects.

    The real frontend reads the non-httpOnly ``reticle_csrf`` cookie and echoes
    it back in the ``X-CSRF-Token`` header on every mutating request. Mirroring
    that here keeps the CSRF mechanism under test without every test having to
    plumb the header by hand; tests that want to prove the rejection path use
    :attr:`raw` to bypass the echo.
    """

    def __init__(self, client: TestClient) -> None:
        self.raw = client

    @property
    def cookies(self) -> Any:
        return self.raw.cookies

    def _send(self, method: str, url: str, **kwargs: Any) -> Any:
        if method not in SAFE_METHODS:
            token = self.raw.cookies.get("reticle_csrf")
            if token is not None:
                headers = dict(kwargs.get("headers") or {})
                headers.setdefault("X-CSRF-Token", token)
                kwargs["headers"] = headers
        return self.raw.request(method, url, **kwargs)

    def get(self, url: str, **kwargs: Any) -> Any:
        return self._send("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        return self._send("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Any:
        return self._send("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> Any:
        return self._send("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Any:
        return self._send("DELETE", url, **kwargs)

    def login(self, email: str, password: str = TEST_PASSWORD) -> Any:
        return self.post("/api/auth/login", json={"email": email, "password": password})


@pytest.fixture()
def media_root(tmp_path, monkeypatch) -> Iterator[Any]:
    root = tmp_path / "media_store"
    monkeypatch.setenv("RETICLE_MEDIA_ROOT", str(root))
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()


@pytest.fixture()
def db_session(media_root) -> Iterator[Session]:
    """Bind the application to a throwaway in-memory database.

    ``StaticPool`` keeps every connection pointed at the same in-memory
    database; without it each pooled connection would silently get its own
    empty schema and requests would see a different world than the fixtures.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, future=True)

    def override_get_db() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    session = factory()
    try:
        yield session
    finally:
        session.close()
        app.dependency_overrides.clear()
        engine.dispose()


@pytest.fixture()
def make_user(db_session: Session) -> Callable[..., User]:
    def _make(
        email: str,
        role: str = "viewer",
        password: str = TEST_PASSWORD,
        display_name: str | None = None,
        is_active: bool = True,
    ) -> User:
        user = User(
            email=email.lower(),
            display_name=display_name or email.split("@")[0].replace(".", " ").title(),
            role=role,
            password_hash=hash_password(password),
            is_active=is_active,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return _make


@pytest.fixture()
def client_factory(db_session: Session) -> Callable[..., ApiClient]:
    """Build clients that can pretend to come from a chosen source address.

    Per-IP throttling is only testable if a test can vary the peer address, and
    ``TestClient`` fixes it at construction time.
    """

    def _factory(host: str = "testclient") -> ApiClient:
        return ApiClient(TestClient(app, client=(host, 50000)))

    return _factory


@pytest.fixture()
def anon(client_factory) -> ApiClient:
    return client_factory()


@pytest.fixture()
def as_role(make_user, client_factory) -> Callable[..., ApiClient]:
    def _as(role: str, email: str | None = None, **user_kwargs: Any) -> ApiClient:
        address = email or f"{role}@zmb.uzh.ch"
        make_user(address, role=role, **user_kwargs)
        client = client_factory()
        response = client.login(address)
        assert response.status_code == 200, response.text
        return client

    return _as


@pytest.fixture()
def viewer(as_role) -> ApiClient:
    return as_role("viewer")


@pytest.fixture()
def author(as_role) -> ApiClient:
    return as_role("author")


@pytest.fixture()
def admin(as_role) -> ApiClient:
    return as_role("admin")


@pytest.fixture()
def category(db_session: Session) -> Category:
    entry = Category(
        slug="light-microscopy",
        name="Light Microscopy",
        description="Confocal, widefield and superresolution systems.",
        parent_id=None,
        order_index=0,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


def image_bytes(
    width: int = 24,
    height: int = 16,
    image_format: str = "PNG",
    color: str = "#3366aa",
    exif: bytes | None = None,
) -> bytes:
    mode = "RGB" if image_format in {"JPEG", "WEBP"} else "RGBA"
    if image_format == "GIF":
        mode = "P"
    image = Image.new("RGB", (width, height), color).convert(mode)
    buffer = BytesIO()
    save_kwargs: dict[str, Any] = {}
    if exif is not None:
        save_kwargs["exif"] = exif
    image.save(buffer, format=image_format, **save_kwargs)
    return buffer.getvalue()


def noisy_png(width: int = 400, height: int = 400) -> bytes:
    """An incompressible PNG, for exercising the byte-size cap.

    A flat colour compresses to a couple of kilobytes no matter how many pixels
    it has, so a size-limit test needs real entropy.
    """
    image = Image.frombytes("RGB", (width, height), os.urandom(width * height * 3))
    buffer = BytesIO()
    image.save(buffer, format="PNG", compress_level=0)
    return buffer.getvalue()


def jpeg_with_exif(make: str = "ZMB-Stellaris", model: str = "DMi8") -> bytes:
    """A JPEG carrying identifiable EXIF, for proving the upload strips it."""
    exif = Image.Exif()
    exif[0x010F] = make
    exif[0x0110] = model
    return image_bytes(32, 24, "JPEG", exif=exif.tobytes())


def upload_media(client: ApiClient, payload: bytes | None = None, filename: str = "step.png") -> dict:
    files = {"file": (filename, payload if payload is not None else image_bytes(), "image/png")}
    response = client.post("/api/media", files=files)
    assert response.status_code == 201, response.text
    return response.json()


def create_guide(client: ApiClient, category_id: str, title: str = "Aligning the Confocal") -> dict:
    response = client.post("/api/guides", json={"title": title, "categoryId": category_id})
    assert response.status_code == 201, response.text
    return response.json()


def instant(value: str) -> "datetime":
    """Parse a wire timestamp.

    Wire timestamps must be compared as instants, never as strings: pydantic
    omits a zero microsecond field, so ``...:00Z`` and ``...:00.000001Z`` sort
    the wrong way round lexicographically.
    """
    from datetime import datetime

    assert value.endswith("Z"), value
    return datetime.fromisoformat(value[:-1] + "+00:00")


def document_from(guide: dict, **overrides: Any) -> dict:
    """Round-trip a fetched guide into a ``PUT`` body, as the editor does."""
    body = dict(guide)
    body.update(overrides)
    return body


def step(title: str, bullets: list[dict] | None = None, media: list[dict] | None = None, step_id: str | None = None) -> dict:
    entry: dict[str, Any] = {
        "title": title,
        "orderIndex": 99,
        "bullets": bullets or [],
        "media": media or [],
    }
    if step_id is not None:
        entry["id"] = step_id
    return entry


def bullet(text: str, color: str = "black", icon: str | None = None, level: int = 0, bullet_id: str | None = None) -> dict:
    entry: dict[str, Any] = {"text": text, "color": color, "icon": icon, "level": level}
    if bullet_id is not None:
        entry["id"] = bullet_id
    return entry
