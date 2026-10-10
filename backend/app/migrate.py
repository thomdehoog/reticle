"""Create or upgrade the database schema.

One command::

    python -m app.migrate

It reads ``RETICLE_DATABASE_URL`` like the server does, creates the schema on an
empty database and applies whatever migrations a newer release has added to an
existing one. It is safe to run on every deploy; when there is nothing to do it
does nothing.

The server does not do this for itself at start-up. With more than one worker
each would try, and "which process changed the schema, and did it finish" is not
a question to be asking at three in the morning. Instead the server checks, and
refuses to start with an instruction when the schema is not the one it expects.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect

from . import db

MIGRATIONS_DIRECTORY = Path(__file__).resolve().parent.parent / "migrations"

VERSION_TABLE = "alembic_version"


class SchemaError(RuntimeError):
    """The database is not in a state this release can run against."""


def alembic_config(engine: Engine | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIRECTORY))
    config.attributes["engine"] = engine
    return config


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _refuse_an_unversioned_schema(engine: Engine) -> None:
    """Stop before colliding with tables that no migration created.

    Early development builds created their tables directly. Running the
    baseline over one of those would fail on the first ``CREATE TABLE`` with a
    message about a table already existing, which says what went wrong and
    nothing about what to do.
    """
    tables = set(inspect(engine).get_table_names())
    if tables and VERSION_TABLE not in tables:
        raise SchemaError(
            "This database already has tables but no migration history, so it was created by a "
            "development build from before migrations existed. There is no upgrade path from it: "
            "move it aside (and the media directory with it) and run `python -m app.migrate` again "
            "to start from an empty database."
        )


def upgrade(engine: Engine | None = None) -> str:
    """Bring the schema to the newest revision and return that revision."""
    target = engine if engine is not None else db.engine
    _refuse_an_unversioned_schema(target)
    command.upgrade(alembic_config(target), "head")
    return head_revision()


def assert_current(engine: Engine) -> None:
    """Raise unless the database is at exactly the revision this code was written for."""
    expected = head_revision()
    found = current_revision(engine)
    if found == expected:
        return
    if found is None:
        raise SchemaError(
            "The database has not been initialised. Run `python -m app.migrate` (and then "
            "`python -m app.seed` on a first install) before starting the server."
        )
    raise SchemaError(
        f"The database schema is at revision {found} but this release expects {expected}. "
        "Run `python -m app.migrate` before starting the server. If you have just rolled back to "
        "an older release, restore the database backup taken before the upgrade instead."
    )


def main() -> None:
    revision = upgrade()
    print(f"Database schema is up to date (revision {revision}).")


if __name__ == "__main__":
    main()
