"""The real database path: migrations, SQLite tuning and the server against a file.

The rest of the suite runs on an in-memory database built straight from the
models, which is fast and is not what production does. Everything here uses a
database file on disk, created by the migrations and opened through
``db.build_engine`` — the path a deployment actually takes.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import OperationalError

from app import db, migrate, seed
from app.main import app
from app.models import Base, Category, Guide, LoginAttempt, Page, User
from app.security import hash_password
from app.settings import get_settings

from .conftest import TEST_PASSWORD, ApiClient, bullet, document_from, mp4_bytes, step

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture()
def file_db(tmp_path, monkeypatch, media_root):
    """Point the application at an empty SQLite file, as a deployment would."""
    url = f"sqlite:///{tmp_path / 'reticle.db'}"
    monkeypatch.setenv("RETICLE_DATABASE_URL", url)
    get_settings.cache_clear()
    engine = db.build_engine(url)
    writer, reader = db.session_factories(engine)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", writer)
    monkeypatch.setattr(db, "ReadSessionLocal", reader)
    yield engine
    engine.dispose()
    get_settings.cache_clear()


@pytest.fixture()
def migrated(file_db):
    migrate.upgrade()
    return file_db


@pytest.fixture()
def live(migrated):
    """The application served from the migrated file, with an author signed in."""
    with db.SessionLocal() as session:
        session.add(Category(slug="lm", name="Light Microscopy"))
        session.add(User(email="author@zmb.uzh.ch", display_name="Author", role="author", password_hash=hash_password(TEST_PASSWORD)))
        session.commit()
    with TestClient(app) as raw:
        client = ApiClient(raw)
        assert client.login("author@zmb.uzh.ch").status_code == 200
        yield client


# ---------------------------------------------------------------- migrations


def test_migrating_an_empty_database_creates_the_whole_schema(file_db):
    assert inspect(file_db).get_table_names() == []

    revision = migrate.upgrade()

    tables = set(inspect(file_db).get_table_names())
    assert set(Base.metadata.tables) <= tables
    assert "alembic_version" in tables
    assert revision == migrate.head_revision() == migrate.current_revision(file_db)


def test_the_migrated_schema_is_exactly_what_the_models_describe(migrated):
    """If this fails, a model changed without a migration — or the other way
    round — and a fresh install would differ from an upgraded one."""
    with migrated.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True, "render_as_batch": True})
        difference = compare_metadata(context, Base.metadata)

    assert difference == []


def test_the_partial_landing_index_survives_migration(migrated):
    indexes = {index["name"]: index for index in inspect(migrated).get_indexes("pages")}

    assert indexes["uq_pages_one_landing_per_category"]["unique"] == 1
    with migrated.connect() as connection:
        definition = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'uq_pages_one_landing_per_category'")
        ).scalar_one()
    assert "WHERE" in definition and "archived" in definition


def test_migrating_twice_changes_nothing(migrated):
    before = sorted(inspect(migrated).get_table_names())

    assert migrate.upgrade() == migrate.head_revision()

    assert sorted(inspect(migrated).get_table_names()) == before


def test_the_baseline_can_be_rolled_back(migrated):
    command.downgrade(migrate.alembic_config(migrated), "base")

    assert inspect(migrated).get_table_names() == ["alembic_version"]
    assert migrate.current_revision(migrated) is None


def test_adding_the_hero_description_keeps_the_pages_that_were_already_there(file_db):
    """0003 adds a NOT NULL column to a table with rows in it. On SQLite that is
    a table rebuild, which is exactly where a migration loses data quietly."""
    command.upgrade(migrate.alembic_config(file_db), "0002")
    with file_db.begin() as connection:
        connection.execute(text(
            "INSERT INTO users (id, email, display_name, role, password_hash, is_active, created_at, updated_at) "
            "VALUES ('01HZZZZZZZZZZZZZZZZZZZZZZU', 'a@zmb.example', 'A', 'author', 'x', 1, '2026-01-01', '2026-01-01')"
        ))
        connection.execute(text(
            "INSERT INTO pages (id, slug, title, summary, status, version, view_count, created_at, updated_at, "
            "author_id, last_edited_by_id, is_landing, body) VALUES ('01HZZZZZZZZZZZZZZZZZZZZZZP', 'old', 'Old page', "
            "'', 'published', 1, 7, '2026-01-01', '2026-01-01', '01HZZZZZZZZZZZZZZZZZZZZZZU', "
            "'01HZZZZZZZZZZZZZZZZZZZZZZU', 0, 'Body from before.')"
        ))

    assert migrate.upgrade() == migrate.head_revision()

    with file_db.connect() as connection:
        row = connection.execute(text("SELECT title, body, view_count, hero_alt FROM pages")).one()
    assert tuple(row) == ("Old page", "Body from before.", 7, "")

    command.downgrade(migrate.alembic_config(file_db), "0002")
    assert "hero_alt" not in {column["name"] for column in inspect(file_db).get_columns("pages")}
    with file_db.connect() as connection:
        assert connection.execute(text("SELECT body FROM pages")).scalar_one() == "Body from before."


def test_a_database_from_before_migrations_is_refused_with_instructions(file_db):
    """Early development builds made their tables with ``create_all``. Running
    the baseline over one would die on "table already exists"."""
    Base.metadata.create_all(file_db)

    with pytest.raises(migrate.SchemaError, match="no migration history"):
        migrate.upgrade()


def test_the_migrate_command_reports_the_revision(file_db, capsys):
    migrate.main()

    assert f"revision {migrate.head_revision()}" in capsys.readouterr().out
    assert migrate.current_revision(file_db) == migrate.head_revision()


def test_the_alembic_command_line_works_from_the_backend_directory(tmp_path):
    """``alembic upgrade head`` is the documented alternative for developers,
    so the ini file and env.py have to work without the wrapper."""
    database = tmp_path / "cli.db"
    environment = {
        **os.environ,
        "RETICLE_ENV_FILE": "",
        "RETICLE_SECRET_KEY": "a-secret-key-long-enough",
        "RETICLE_DATABASE_URL": f"sqlite:///{database}",
    }

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND, env=environment, capture_output=True, text=True, timeout=120,
    )

    assert result.returncode == 0, result.stderr
    engine = db.build_engine(f"sqlite:///{database}")
    try:
        assert migrate.current_revision(engine) == migrate.head_revision()
    finally:
        engine.dispose()


def test_offline_sql_generation_is_declined(tmp_path):
    environment = {**os.environ, "RETICLE_ENV_FILE": "", "RETICLE_SECRET_KEY": "a-secret-key-long-enough"}

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND, env=environment, capture_output=True, text=True, timeout=120,
    )

    assert result.returncode != 0
    assert "python -m app.migrate" in result.stderr + result.stdout


# ----------------------------------------------------------- start-up checks


def test_the_server_refuses_to_start_on_an_uninitialised_database(file_db):
    with pytest.raises(migrate.SchemaError, match="python -m app.migrate"):
        with TestClient(app):
            pass  # pragma: no cover


def _set_revision(engine, revision: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = :revision"), {"revision": revision})


def test_the_server_refuses_to_start_on_a_schema_from_a_newer_release(migrated):
    """Someone went back to an older image. "Run migrate" would be the wrong
    advice: the database is ahead of the code, not behind it."""
    _set_revision(migrated, "from-the-future")

    with pytest.raises(migrate.SchemaError, match="from-the-future") as refusal:
        with TestClient(app):
            pass  # pragma: no cover

    message = str(refusal.value)
    assert "newer release" in message
    assert "restore the backup" in message and "docs/MAINTENANCE.md" in message
    assert "Run `python -m app.migrate`" not in message


def test_the_server_refuses_to_start_on_a_schema_that_is_behind(migrated):
    _set_revision(migrated, "0001")

    with pytest.raises(migrate.SchemaError, match="revision 0001 but this release expects") as refusal:
        with TestClient(app):
            pass  # pragma: no cover

    assert "python -m app.migrate" in str(refusal.value)


def test_migrating_a_database_from_a_newer_release_explains_itself(migrated):
    """Alembic's own words for this are "Can't locate revision identified by
    'from-the-future'", which is no help to whoever rolled the image back."""
    _set_revision(migrated, "from-the-future")

    with pytest.raises(migrate.SchemaError) as refusal:
        migrate.upgrade()

    message = str(refusal.value)
    assert "from-the-future" in message and "newer release" in message
    assert "Can't locate" not in message
    assert migrate.current_revision(migrated) == "from-the-future"


def test_the_migrate_command_exits_with_the_explanation_and_no_traceback(migrated):
    _set_revision(migrated, "from-the-future")

    with pytest.raises(SystemExit) as stopped:
        migrate.main()

    assert str(stopped.value).startswith("reticle: The database schema is at revision from-the-future")
    assert stopped.value.code != 0


def test_a_version_table_alembic_cannot_place_is_still_this_modules_error(migrated, monkeypatch):
    """The backstop behind the up-front check, for whatever that check missed."""
    from alembic.util import CommandError

    def cannot_locate(config, revision):
        raise CommandError("Can't locate revision identified by 'elsewhere'")

    monkeypatch.setattr(migrate.command, "upgrade", cannot_locate)

    with pytest.raises(migrate.SchemaError, match="newer release"):
        migrate.upgrade()


def test_an_unrelated_alembic_failure_is_not_dressed_up_as_a_rollback(migrated, monkeypatch):
    from alembic.util import CommandError

    def broken(config, revision):
        raise CommandError("Multiple head revisions are present")

    monkeypatch.setattr(migrate.command, "upgrade", broken)

    with pytest.raises(CommandError, match="Multiple head"):
        migrate.upgrade()


def test_the_server_starts_on_a_migrated_database_and_health_queries_it(migrated):
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_503_when_the_database_does_not_answer(migrated):
    """The probe must fail when the one real dependency is down, and must not
    describe the failure to whoever is asking without a session."""
    database = Path(migrated.url.database)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        migrated.dispose()
        database.unlink()
        database.mkdir()

        response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_starting_the_server_prunes_what_has_expired(migrated):
    from datetime import timedelta

    from app.db import utcnow
    from app.models import Session as SessionRow

    with db.SessionLocal() as session:
        user = User(email="gone@zmb.uzh.ch", display_name="Gone", role="viewer", password_hash="x")
        session.add(user)
        session.flush()
        long_ago = utcnow() - timedelta(days=30)
        session.add(SessionRow(user_id=user.id, token_hash="a" * 64, csrf_token="c", expires_at=long_ago))
        session.add(LoginAttempt(scope="ip", key="203.0.113.9", created_at=long_ago))
        session.commit()

    with TestClient(app):
        pass

    with db.ReadSessionLocal() as session:
        assert session.scalars(select(SessionRow)).all() == []
        assert session.scalars(select(LoginAttempt)).all() == []


# ------------------------------------------------------------- SQLite tuning


def test_a_database_file_is_opened_in_wal_mode_with_a_busy_timeout_and_foreign_keys(file_db):
    with file_db.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == db.SQLITE_BUSY_TIMEOUT_MS
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert connection.exec_driver_sql("PRAGMA synchronous").scalar_one() == 1


def test_an_in_memory_database_is_left_out_of_wal():
    engine = db.build_engine("sqlite://")
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "memory"
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    finally:
        engine.dispose()


def test_a_postgres_url_gets_a_plain_engine_with_none_of_the_sqlite_tuning(monkeypatch):
    """The code is kept PostgreSQL-compatible; the SQLite pragmas must not be
    sent to a server that would reject them."""
    created = {}

    def fake_create_engine(url, **kwargs):
        created.update(url=url, kwargs=kwargs)
        return "engine"

    monkeypatch.setattr(db, "create_engine", fake_create_engine)

    assert db.build_engine("postgresql+psycopg://reticle@localhost/reticle") == "engine"
    assert created["kwargs"] == {"future": True}


def test_configure_repoints_the_application(tmp_path, monkeypatch):
    original = (db.engine, db.SessionLocal, db.ReadSessionLocal)
    throwaway = db.build_engine("sqlite://")
    monkeypatch.setattr(db, "engine", throwaway)
    try:
        engine = db.configure(f"sqlite:///{tmp_path / 'other.db'}")

        assert db.engine is engine
        assert str(engine.url).endswith("other.db")
        with db.SessionLocal() as session:
            assert session.execute(text("SELECT 1")).scalar_one() == 1
        engine.dispose()
    finally:
        db.engine, db.SessionLocal, db.ReadSessionLocal = original


def test_a_transaction_is_real_and_rolls_back(migrated):
    """Reticle issues ``BEGIN`` itself instead of leaving it to the driver; this
    is the check that doing so did not quietly turn every statement into its own
    commit."""
    with db.SessionLocal() as session:
        session.add(Category(slug="temporary", name="Temporary"))
        session.flush()
        session.rollback()

    with db.ReadSessionLocal() as session:
        assert session.scalars(select(Category)).all() == []


def _read_then_write(factory, barrier: threading.Barrier, failures: list[BaseException], name: str) -> None:
    """What every mutating request does: read first, write afterwards."""
    try:
        with factory() as session:
            session.execute(text("SELECT count(*) FROM categories")).scalar_one()
            barrier.wait(timeout=10)
            session.add(Category(slug=name, name=name))
            session.commit()
    except BaseException as exc:  # noqa: BLE001 -- the test inspects whatever went wrong
        failures.append(exc)


def test_concurrent_writers_queue_instead_of_failing(migrated):
    """Two workers, two autosaves at once.

    Opened for writing, the second request waits its turn at ``BEGIN IMMEDIATE``
    — it never reaches the barrier while the first holds the lock, so the
    barrier times out in the first, which then commits and lets the second
    through. Nobody fails.
    """
    other_process = db.build_engine(str(migrated.url))
    other_writer, _ = db.session_factories(other_process)
    failures: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker(factory, name):
        try:
            with factory() as session:
                session.execute(text("SELECT count(*) FROM categories")).scalar_one()
                try:
                    barrier.wait(timeout=0.5)
                except threading.BrokenBarrierError:
                    pass
                session.add(Category(slug=name, name=name))
                session.commit()
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)

    threads = [
        threading.Thread(target=worker, args=(db.SessionLocal, "first")),
        threading.Thread(target=worker, args=(other_writer, "second")),
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
    finally:
        other_process.dispose()

    assert failures == []
    with db.ReadSessionLocal() as session:
        assert sorted(session.scalars(select(Category.slug))) == ["first", "second"]


def test_the_failure_that_write_intent_prevents_is_real(migrated):
    """The same two requests opened the default, deferred way: both read, one
    commits, and the other's upgrade to a write lock is refused outright. This
    is here so that nobody "simplifies" the write-intent sessions away."""
    other_process = db.build_engine(str(migrated.url))
    _, other_reader = db.session_factories(other_process)
    failures: list[BaseException] = []
    barrier = threading.Barrier(2)
    threads = [
        threading.Thread(target=_read_then_write, args=(db.ReadSessionLocal, barrier, failures, "first")),
        threading.Thread(target=_read_then_write, args=(other_reader, barrier, failures, "second")),
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
    finally:
        other_process.dispose()

    assert len(failures) == 1
    assert isinstance(failures[0], OperationalError)
    assert "locked" in str(failures[0])


def test_requests_open_for_writing_only_when_the_verb_can_write(migrated, monkeypatch):
    opened = []
    monkeypatch.setattr(db, "SessionLocal", lambda: opened.append("write") or db.ReadSessionLocal())

    with TestClient(app) as client:
        opened.clear()
        client.get("/api/health")
        assert opened == []
        client.post("/api/auth/login", json={"email": "nobody@zmb.uzh.ch", "password": "x"})
        assert opened == ["write"]


# ------------------------------------------------- the API on the real engine


def test_the_whole_content_lifecycle_works_against_the_migrated_file(live):
    """One pass through every kind of write on the production engine: explicit
    transactions, savepoints for tag creation, the partial index, cascades."""
    category_id = live.get("/api/categories").json()[0]["id"]

    guide = live.post("/api/guides", json={"title": "On Disk", "categoryId": category_id}).json()
    clip = live.post("/api/media", files={"file": ("clip.mp4", mp4_bytes(), "video/mp4")}).json()
    saved = live.put(
        f"/api/guides/{guide['id']}",
        json=document_from(guide, tags=["LAS X", "confocal"], steps=[step("One", bullets=[bullet("Text")], media=[clip])]),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["tags"] == ["confocal", "las-x"]
    resaved = live.put(f"/api/guides/{guide['id']}", json=document_from(saved.json(), tags=["confocal", "new-tag"], steps=[]))
    assert resaved.status_code == 200, resaved.text
    republished = live.put(
        f"/api/guides/{guide['id']}",
        json=document_from(resaved.json(), steps=[step("Again", bullets=[bullet("Text")])]),
    ).json()
    assert live.post(f"/api/guides/{guide['id']}/publish").json()["version"] == 1
    assert live.post(f"/api/guides/{guide['id']}/view").status_code == 204
    assert live.get(f"/api/guides/{guide['id']}").json()["viewCount"] == 1
    assert live.get(f"/api/guides/{guide['id']}/pdf").status_code == 200
    assert republished["tags"] == ["confocal", "new-tag"]

    landing = live.post("/api/pages", json={"title": "Landing", "categoryId": category_id, "isLanding": True}).json()
    rival = live.post("/api/pages", json={"title": "Rival", "categoryId": category_id, "isLanding": True})
    assert rival.status_code == 409
    page = live.put(f"/api/pages/{landing['id']}", json=document_from(landing, body=f"[clip](/api/media/{clip['id']})"))
    assert page.status_code == 200, page.text
    assert live.post(f"/api/pages/{landing['id']}/publish").json()["status"] == "published"

    assert {tag["slug"] for tag in live.get("/api/tags").json()} == {"confocal", "new-tag"}
    assert len(live.get("/api/search", params={"q": "landing"}).json()) == 1
    assert live.get(f"/api/media/{clip['id']}", headers={"Range": "bytes=0-3"}).status_code == 206

    with db.ReadSessionLocal() as session:
        assert session.scalars(select(Guide)).one().version == 1
        assert session.scalars(select(Page)).one().status == "published"


def test_a_refused_save_leaves_nothing_behind_on_the_real_engine(live):
    category_id = live.get("/api/categories").json()[0]["id"]
    guide = live.post("/api/guides", json={"title": "Atomic", "categoryId": category_id}).json()

    refused = live.put(
        f"/api/guides/{guide['id']}",
        json=document_from(guide, title="Changed", tags=["brand-new-tag"], steps=[step("Bad", step_id="not-a-ulid")]),
    )

    assert refused.status_code == 422
    assert live.get(f"/api/guides/{guide['id']}").json()["title"] == "Atomic"
    assert live.get("/api/tags").json() == []
    with db.ReadSessionLocal() as session:
        assert session.execute(text("SELECT count(*) FROM tags")).scalar_one() == 0


# ---------------------------------------------------------------------- seed


def test_the_seed_command_migrates_then_seeds_and_reports(file_db, monkeypatch, capsys):
    monkeypatch.setenv("RETICLE_ADMIN_EMAIL", "zmb.admin@zmb.uzh.ch")
    monkeypatch.setenv("RETICLE_ADMIN_PASSWORD", "Bootstrap-Admin-Passphrase-2")
    get_settings.cache_clear()

    seed.main([])
    first = capsys.readouterr().out
    seed.main([])
    second = capsys.readouterr().out

    assert migrate.current_revision(file_db) == migrate.head_revision()
    assert "administrator zmb.admin@zmb.uzh.ch" in first
    assert "guide Starting a Session on the Confocal" in first
    assert "Nothing to do" in second
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200


def test_the_write_lock_is_not_held_while_a_password_is_being_hashed(live, monkeypatch):
    """Argon2 is slow on purpose. If a sign-in kept its transaction open across
    it, a handful of concurrent logins would stall every autosave in the
    building; here a second writer must get through *while* one is verifying."""
    from app.routers import auth as auth_router

    verifying, release = threading.Event(), threading.Event()
    outcome = {}

    def slow_verify(stored_hash, plaintext):
        verifying.set()
        release.wait(timeout=20)
        return False

    monkeypatch.setattr(auth_router, "verify_password", slow_verify)
    other_process = db.build_engine(str(db.engine.url))
    other_writer, _ = db.session_factories(other_process)

    def sign_in():
        with TestClient(app) as second_client:
            outcome["login"] = second_client.post(
                "/api/auth/login", json={"email": "author@zmb.uzh.ch", "password": "anything"}
            ).status_code

    thread = threading.Thread(target=sign_in)
    thread.start()
    try:
        assert verifying.wait(timeout=20)
        started = time.monotonic()
        with other_writer() as session:
            session.add(Category(slug="meanwhile", name="Meanwhile"))
            session.commit()
        waited = time.monotonic() - started
    finally:
        release.set()
        thread.join(timeout=30)
        other_process.dispose()

    assert outcome["login"] == 401
    assert waited < db.SQLITE_BUSY_TIMEOUT_MS / 1000 / 2, "the writer had to queue behind the login"
    with db.ReadSessionLocal() as session:
        assert "meanwhile" in session.scalars(select(Category.slug)).all()


def test_an_upload_does_not_hold_the_write_lock_while_its_body_is_handled(live, monkeypatch):
    """Authenticating a POST opens a write transaction; a slow two-hundred
    megabyte upload must not sit on it."""
    from app.routers import media as media_router

    state = {}
    original = media_router._accept_upload

    def inspecting(session, *args, **kwargs):
        state["in_transaction"] = session.in_transaction()
        return original(session, *args, **kwargs)

    monkeypatch.setattr(media_router, "_accept_upload", inspecting)

    response = live.post("/api/media", files={"file": ("clip.mp4", mp4_bytes(), "video/mp4")})

    assert response.status_code == 201
    assert state == {"in_transaction": False}
