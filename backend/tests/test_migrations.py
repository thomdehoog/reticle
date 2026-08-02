"""Migrations, and the one way they go wrong that nobody notices.

The failure this file exists for is drift. Somebody adds a column to
``models.py``, the test suite creates its tables from that metadata, everything
passes — and the migration that would have added the column to a real database
was never written. Nothing is wrong until a deploy, at which point production
is running new code against last release's schema.

So the central test is not that migrations run. It is that running them
produces a schema **identical** to the one the models describe, column by
column, index by index, constraint by constraint. That test fails the moment
somebody edits a model without generating a migration, which is exactly when
they need to be told.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app import models  # noqa: F401  -- registers every mapper
from app.db import Base, init_db

BACKEND = __import__("pathlib").Path(__file__).resolve().parents[1]


def alembic_config(engine=None) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    if engine is not None:
        config.attributes["connection"] = engine
    return config


def schema_of(engine) -> dict:
    """Everything about the shape of a database that a query could depend on."""
    inspector = inspect(engine)
    schema = {}
    for table in sorted(inspector.get_table_names()):
        if table == "alembic_version":
            continue
        schema[table] = {
            "columns": {
                column["name"]: (str(column["type"]), column["nullable"])
                for column in inspector.get_columns(table)
            },
            "indexes": sorted(
                (index["name"], tuple(index["column_names"]), bool(index["unique"]))
                for index in inspector.get_indexes(table)
            ),
            "foreign_keys": sorted(
                (tuple(key["constrained_columns"]), key["referred_table"])
                for key in inspector.get_foreign_keys(table)
            ),
            "unique_constraints": sorted(
                (constraint["name"], tuple(constraint["column_names"]))
                for constraint in inspector.get_unique_constraints(table)
            ),
        }
    return schema


@pytest.fixture
def migrated(scratch_engine):
    engine = scratch_engine("migrated")
    command.upgrade(alembic_config(engine), "head")
    return engine


@pytest.fixture
def from_models(scratch_engine):
    engine = scratch_engine("models")
    Base.metadata.create_all(engine)
    return engine


# --- the one that matters --------------------------------------------------


def test_migrating_produces_exactly_the_schema_the_models_describe(migrated, from_models):
    """If this fails, somebody changed a model without writing a migration.

    The fix is to generate one, not to relax this test:

        alembic revision --autogenerate -m "what changed"
    """
    assert schema_of(migrated) == schema_of(from_models)


def test_autogenerate_finds_nothing_left_to_do(migrated):
    """The same claim from the other direction, and the stricter of the two.

    Comparing two inspected schemas can miss a difference the inspector does not
    surface. Asking Alembic itself whether the migrated database still differs
    from the metadata catches those, because that comparison is the one it would
    use to write the next migration.
    """
    from alembic.autogenerate import compare_metadata

    with migrated.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        )
        difference = compare_metadata(context, Base.metadata)

    assert difference == [], f"models and migrations have drifted: {difference}"


# --- the history itself ----------------------------------------------------


def test_there_is_exactly_one_head():
    """Two heads means two people generated a migration from the same parent.

    Alembic will not upgrade past it, and the failure appears during a deploy
    rather than in the pull request that caused it.
    """
    scripts = ScriptDirectory.from_config(alembic_config())

    assert len(scripts.get_heads()) == 1


VISIBILITY_REVISION = "a307e0dfe4d8"
"""The migration that adds ``guides.visibility``, exercised below against a
database that already holds a guide — which is every facility that has ever
written one, and the only condition under which the interesting failure (adding
a ``NOT NULL`` column with no default) actually happens."""


def _write_one_guide(engine) -> None:
    """The smallest legal guide: an account, a category, and the row itself."""
    with engine.connect() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, email, display_name, role, password_hash, is_active, "
                "created_at, updated_at) VALUES ('01ARZ3NDEKTSV4RRFFQ69G5FA0', 'a@zmb.uzh.ch', "
                "'A', 'admin', 'x', true, now(), now())"
            )
        )
        connection.execute(
            text(
                "INSERT INTO categories (id, slug, name, description, order_index, is_hidden, "
                "created_at, updated_at) VALUES ('01ARZ3NDEKTSV4RRFFQ69G5FA1', 'lm', 'LM', '', "
                "0, false, now(), now())"
            )
        )
        connection.execute(
            text(
                "INSERT INTO guides (id, slug, title, summary, category_id, difficulty, "
                "introduction, conclusion, status, is_quick_link, version, view_count, author_id, "
                "last_edited_by_id, created_at, updated_at) VALUES "
                "('01ARZ3NDEKTSV4RRFFQ69G5FA2', 'starting-the-confocal', 'Starting the Confocal', "
                "'', '01ARZ3NDEKTSV4RRFFQ69G5FA1', 'moderate', '', '', 'published', false, 1, 0, "
                "'01ARZ3NDEKTSV4RRFFQ69G5FA0', '01ARZ3NDEKTSV4RRFFQ69G5FA0', now(), now())"
            )
        )
        connection.commit()


def test_the_visibility_column_lands_on_a_database_that_already_holds_a_guide(scratch_engine):
    """The one that fails on a real server and never in an empty test database.

    A ``NOT NULL`` column added without a server default is refused outright by
    PostgreSQL when the table has rows in it, so this upgrades to the revision
    before, writes a guide, and only then applies the one under test. The
    backfill has to say ``everyone``: before this column existed the only way to
    keep a guide internal was to leave it unpublished, so a published guide in
    an existing database is one somebody published to the whole institute.
    """
    engine = scratch_engine("populated")
    config = alembic_config(engine)

    command.upgrade(config, f"{VISIBILITY_REVISION}-1")
    _write_one_guide(engine)
    command.upgrade(config, VISIBILITY_REVISION)

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT slug, visibility FROM guides")).all()
    assert rows == [("starting-the-confocal", "everyone")]

    # And the default is not left behind: a server default the models do not
    # describe is drift, which the autogenerate comparison above would report on
    # the next release.
    with engine.connect() as connection:
        default = connection.execute(
            text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = 'guides' AND column_name = 'visibility' "
                "AND table_schema = current_schema()"
            )
        ).scalar()
    assert default is None


def test_undoing_the_visibility_column_leaves_the_guide_itself_alone(scratch_engine):
    """Rolling a release back must cost the distinction, not the guides.

    It does cost the distinction: a staff guide comes back readable by everyone,
    because the older schema cannot say otherwise and the guides are published.
    That is stated in the migration's own docstring so that whoever rolls back
    unpublishes them first.
    """
    engine = scratch_engine("populated_down")
    config = alembic_config(engine)

    command.upgrade(config, f"{VISIBILITY_REVISION}-1")
    _write_one_guide(engine)
    command.upgrade(config, VISIBILITY_REVISION)
    with engine.connect() as connection:
        connection.execute(text("UPDATE guides SET visibility = 'staff'"))
        connection.commit()

    command.downgrade(config, f"{VISIBILITY_REVISION}-1")

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT slug, status FROM guides")).all()
        columns = {column["name"] for column in inspect(engine).get_columns("guides")}
    assert rows == [("starting-the-confocal", "published")]
    assert "visibility" not in columns


def test_every_migration_can_be_undone(scratch_engine):
    """A migration without a working downgrade is a one-way door.

    Rolling a release back is the cheapest incident response there is, and it
    stops being available the moment a downgrade is left as ``pass``.
    """
    engine = scratch_engine("roundtrip")
    config = alembic_config(engine)

    command.upgrade(config, "head")
    assert inspect(engine).get_table_names() != ["alembic_version"]

    command.downgrade(config, "base")

    remaining = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert remaining == set(), f"downgrade left tables behind: {sorted(remaining)}"


# --- how a server actually starts ------------------------------------------


def test_a_fresh_database_comes_up_migrated_and_stamped(scratch_engine):
    engine = scratch_engine("fresh")

    init_db(engine)

    with engine.connect() as connection:
        stamped = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert stamped is not None
    assert schema_of(engine) == schema_of_metadata(scratch_engine)


def schema_of_metadata(scratch_engine):
    engine = scratch_engine("reference")
    Base.metadata.create_all(engine)
    return schema_of(engine)


def test_a_database_from_before_migrations_existed_is_adopted_not_broken(scratch_engine):
    """The upgrade path for the installation already running.

    Its tables were made by ``create_all`` and it has no ``alembic_version``.
    Running migrations against it would try to create tables that are already
    there and fail on the first one — during a deploy, on somebody's server.
    """
    engine = scratch_engine("legacy")
    Base.metadata.create_all(engine)
    assert "alembic_version" not in inspect(engine).get_table_names()

    init_db(engine)

    with engine.connect() as connection:
        stamped = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    assert stamped == heads[0]


def test_starting_twice_changes_nothing(scratch_engine):
    """Startup runs this, and servers restart."""
    engine = scratch_engine("twice")

    init_db(engine)
    once = schema_of(engine)
    init_db(engine)

    assert schema_of(engine) == once


def test_the_url_is_not_committed_into_the_ini():
    """A URL in ``alembic.ini`` is one that gets copied between facilities, and
    pointing a migration at the wrong database is not undone by rolling back."""
    ini = (BACKEND / "alembic.ini").read_text(encoding="utf-8")

    assert "sqlalchemy.url =" not in ini
