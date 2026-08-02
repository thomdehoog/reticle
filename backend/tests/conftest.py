"""Shared test harness for the Reticle backend.

**The suite runs against PostgreSQL, because the application does.** There is
no second engine to fall back to, and that is deliberate: a lighter engine
accepts things PostgreSQL rejects — a NUL byte in a text column, a string into
an integer column, an aggregate over a column that is not grouped — so a green
run against one of those would be evidence about it rather than about
production. The server is ``DEFAULT_TEST_DATABASE_URL`` below, overridden by
``RETICLE_TEST_DATABASE_URL`` where CI and a developer's own server differ. If
it cannot be reached the run stops and says so; there is nothing useful to run
without it.

Every test gets a clean database and a private media directory. That isolation
is not cosmetic: the login throttle, the session table and the uploaded files
are all persistent state, so sharing a database between tests would make the
suite order-dependent and would let one test's failed logins lock another test
out.

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
from datetime import datetime
from io import BytesIO
from typing import Any

DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://reticle@/reticle_test?host=/var/tmp&port=55432"
TEST_DATABASE_URL = os.environ.get("RETICLE_TEST_DATABASE_URL") or DEFAULT_TEST_DATABASE_URL

UNREACHABLE = """\
Cannot connect to the PostgreSQL server the suite needs.

    URL: {url}
    {error}

Reticle runs on PostgreSQL only, so the suite does too. Start a server and
point the suite at it:

    docker run --rm -d -p 5432:5432 \\
        -e POSTGRES_USER=reticle -e POSTGRES_PASSWORD=reticle \\
        -e POSTGRES_DB=reticle_test postgres:16
    export RETICLE_TEST_DATABASE_URL=postgresql+psycopg://reticle:reticle@localhost:5432/reticle_test

The database is emptied at the start of the run, so give the suite one of its
own rather than a database holding anything you want to keep.
"""

os.environ["RETICLE_ENV_FILE"] = ""
os.environ["RETICLE_SECRET_KEY"] = "test-secret-key-do-not-use-in-production"
os.environ["RETICLE_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["RETICLE_COOKIE_SECURE"] = "false"
os.environ["RETICLE_ARGON2_TIME_COST"] = "1"
os.environ["RETICLE_ARGON2_MEMORY_COST_KIB"] = "8"
os.environ["RETICLE_ARGON2_PARALLELISM"] = "1"
# The rate limiter is off for the suite at large and exercised deliberately in
# test_ratelimit.py. Leaving it on would make every other test share one
# per-process window keyed by client address, so adding tests would eventually
# start failing unrelated ones - the worst kind of flake, because the failure
# appears in whatever ran last rather than in what caused it.
os.environ["RETICLE_RATE_LIMIT_ENABLED"] = "false"

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

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


def pytest_configure(config: Any) -> None:
    """Stop the run, once and legibly, if the server is not there.

    Without this the same connection error is reported against every test in
    the suite, and the reason it happened scrolls past.
    """
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect():
            pass
    except OperationalError as error:
        raise pytest.UsageError(UNREACHABLE.format(url=TEST_DATABASE_URL, error=error)) from error
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def database() -> Iterator[Engine]:
    """The one database the whole run uses, emptied before anything touches it.

    Everything is dropped rather than only the tables the models describe: a
    table left behind by a since-deleted model, or an ``alembic_version`` stamped
    by an older revision of this checkout, would otherwise make the first
    start-up try to migrate a schema it did not create.
    """
    engine = create_engine(TEST_DATABASE_URL)
    with engine.connect() as connection:
        existing = (
            connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
            )
            .scalars()
            .all()
        )
        for table in existing:
            connection.execute(text(f'DROP TABLE "{table}" CASCADE'))
        connection.commit()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


# Children before parents, so emptying the database does not trip a foreign key.
EMPTY_EVERY_TABLE = text(
    "; ".join(f'DELETE FROM "{table.name}"' for table in reversed(Base.metadata.sorted_tables))
)


@pytest.fixture()
def db_session(media_root, database: Engine) -> Iterator[Session]:
    """Bind the application to an empty database.

    The tables are emptied rather than dropped and rebuilt. Both give a test a
    database with nothing in it; ``DELETE`` does it in about a millisecond
    against tables this size, where ``CREATE``/``DROP`` costs a fifth of a
    second per test and would add minutes to the run.

    ``app.db.engine`` points at the same database, so start-up — which runs the
    migrations — acts on the schema the tests then use.
    """
    with database.connect() as connection:
        connection.execute(EMPTY_EVERY_TABLE)
        connection.commit()

    factory = sessionmaker(bind=database, autoflush=False, future=True)

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


@pytest.fixture()
def scratch_engine(database: Engine) -> Iterator[Callable[[str], Engine]]:
    """Hand out further empty databases, for the tests that need two.

    A restore has to be proved into a database that is not the one exported
    from, and the migration tests compare a schema built by Alembic against one
    built from the models. Each caller gets a PostgreSQL schema of its own,
    pinned with ``search_path`` so the code under test sees an ordinary empty
    database, and dropped afterwards.
    """
    created: list[tuple[str, Engine]] = []

    def _make(label: str) -> Engine:
        name = f"scratch_{label}_{len(created)}"
        with database.connect() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
            connection.execute(text(f'CREATE SCHEMA "{name}"'))
            connection.commit()
        engine = create_engine(TEST_DATABASE_URL, connect_args={"options": f"-csearch_path={name}"})
        created.append((name, engine))
        return engine

    yield _make

    for name, engine in created:
        engine.dispose()
        with database.connect() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
            connection.commit()


@pytest.fixture()
def empty_database(scratch_engine) -> Iterator[Session]:
    """A session on a second, empty database — the machine being restored onto."""
    engine = scratch_engine("restore")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, future=True)()
    try:
        yield session
    finally:
        session.close()


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


def mp4_bytes(brand: bytes = b"isom", padding: int = 64) -> bytes:
    """The smallest byte string ``app.videos`` will accept as an MP4.

    The sniffer reads an ``ftyp`` box header and a known brand, which is all a
    container test needs; a real clip would only make the fixture slow and the
    failure message longer.
    """
    box = b"\x00\x00\x00\x18ftyp" + brand + b"\x00\x00\x02\x00" + brand
    return box + b"\x00" * padding


def webm_bytes(padding: int = 64) -> bytes:
    """An EBML header, which is what identifies a WebM container."""
    return b"\x1a\x45\xdf\xa3" + b"\x01\x00\x00\x00\x00\x00\x00\x1f" + b"\x00" * padding


def upload_media(
    client: ApiClient, payload: bytes | None = None, filename: str = "step.png"
) -> dict:
    files = {"file": (filename, payload if payload is not None else image_bytes(), "image/png")}
    response = client.post("/api/media", files=files)
    assert response.status_code == 201, response.text
    return response.json()


def upload_video(
    client: ApiClient, payload: bytes | None = None, filename: str = "stage.mp4"
) -> dict:
    """Upload a clip through the same endpoint images use, and prove it landed as one."""
    files = {"file": (filename, payload if payload is not None else mp4_bytes(), "video/mp4")}
    response = client.post("/api/media", files=files)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "video", body
    return body


def create_guide(client: ApiClient, category_id: str, title: str = "Aligning the Confocal") -> dict:
    response = client.post("/api/guides", json={"title": title, "categoryId": category_id})
    assert response.status_code == 201, response.text
    return response.json()


def create_page(
    client: ApiClient,
    title: str = "Light Microscopy",
    category_id: str | None = None,
    is_landing: bool = False,
) -> dict:
    body: dict[str, Any] = {"title": title, "isLanding": is_landing}
    if category_id is not None:
        body["categoryId"] = category_id
    response = client.post("/api/pages", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def instant(value: str) -> datetime:
    """Parse a wire timestamp.

    Wire timestamps must be compared as instants, never as strings: pydantic
    omits a zero microsecond field, so ``...:00Z`` and ``...:00.000001Z`` sort
    the wrong way round lexicographically.
    """

    assert value.endswith("Z"), value
    return datetime.fromisoformat(value[:-1] + "+00:00")


def document_from(guide: dict, **overrides: Any) -> dict:
    """Round-trip a fetched guide into a ``PUT`` body, as the editor does."""
    body = dict(guide)
    body.update(overrides)
    return body


def page_document_from(page: dict, **overrides: Any) -> dict:
    """The wiki half of :func:`document_from`.

    A page is saved by the same whole-document ``PUT`` as a guide, so its editor
    hands back the object it was given — including the ``updatedAt`` that the
    concurrency guard compares against.
    """
    body = dict(page)
    body.update(overrides)
    return body


def step(
    title: str,
    bullets: list[dict] | None = None,
    media: list[dict] | None = None,
    step_id: str | None = None,
    video: dict | None = None,
    kind: str = "step",
) -> dict:
    entry: dict[str, Any] = {
        "title": title,
        "kind": kind,
        "orderIndex": 99,
        "bullets": bullets or [],
        "media": media or [],
        "video": video,
    }
    if step_id is not None:
        entry["id"] = step_id
    return entry


def annotation(
    shape: str = "rectangle",
    color: str = "red",
    x: float = 0.1,
    y: float = 0.2,
    width: float = 0.3,
    height: float = 0.4,
    annotation_id: str | None = None,
) -> dict:
    """One shape over a step image, as fractions of the image's own size."""
    entry: dict[str, Any] = {
        "shape": shape,
        "color": color,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
    }
    if annotation_id is not None:
        entry["id"] = annotation_id
    return entry


def annotated(media: dict, *shapes: dict) -> dict:
    """Attach shapes to a fetched media object without mutating the original."""
    entry = dict(media)
    entry["annotations"] = list(shapes)
    return entry


def bullet(
    text: str,
    color: str = "black",
    icon: str | None = None,
    level: int = 0,
    bullet_id: str | None = None,
) -> dict:
    entry: dict[str, Any] = {"text": text, "color": color, "icon": icon, "level": level}
    if bullet_id is not None:
        entry["id"] = bullet_id
    return entry
