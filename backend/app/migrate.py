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
from alembic.util import CommandError
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


def known_revisions() -> set[str]:
    return {script.revision for script in ScriptDirectory.from_config(alembic_config()).walk_revisions()}


def newer_release_message(found: str) -> str:
    return (
        f"The database schema is at revision {found}, which this release (schema revision "
        f"{head_revision()}) does not know. It was written by a newer release of Reticle, and an "
        "older release cannot read it or take it back. Either run the newer release again, or "
        "restore the backup that was taken before the upgrade (deploy/restore.sh; see "
        "docs/MAINTENANCE.md, section 3)."
    )


def _refuse_a_schema_from_a_newer_release(engine: Engine) -> None:
    """Say what happened when the database is ahead of the code.

    Rolling back to an older image leaves the database at a revision that image
    has no migration file for. Alembic's own report of that is "Can't locate
    revision identified by '0007'", which is accurate and tells an operator
    nothing about what they did or what to do next.
    """
    found = current_revision(engine)
    if found is not None and found not in known_revisions():
        raise SchemaError(newer_release_message(found))


def upgrade(engine: Engine | None = None) -> str:
    """Bring the schema to the newest revision and return that revision."""
    target = engine if engine is not None else db.engine
    _refuse_an_unversioned_schema(target)
    _refuse_a_schema_from_a_newer_release(target)
    try:
        command.upgrade(alembic_config(target), "head")
    except CommandError as problem:
        # The check above covers the ordinary case. This is for whatever else
        # leaves Alembic unable to place the database in its history — a
        # version table holding two rows, say — so that it still surfaces as
        # this module's error and not as a traceback.
        if "Can't locate revision" not in str(problem):
            raise
        raise SchemaError(newer_release_message(current_revision_text(target))) from problem
    return head_revision()


def current_revision_text(engine: Engine) -> str:
    """Whatever the version table holds, for a message; never raises over it."""
    with engine.connect() as connection:
        heads = MigrationContext.configure(connection).get_current_heads()
    return ", ".join(sorted(heads)) or "unknown"


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
    if found not in known_revisions():
        # Not "run migrate": there is nothing to migrate to, the database is ahead.
        raise SchemaError(newer_release_message(found))
    raise SchemaError(
        f"The database schema is at revision {found} but this release expects {expected}. "
        "Run `python -m app.migrate` before starting the server."
    )


def main() -> None:
    try:
        revision = upgrade()
    except SchemaError as problem:
        # An operator reads this in `docker compose logs`; the sentence is the
        # whole diagnosis and a traceback above it would only bury it.
        raise SystemExit(f"reticle: {problem}") from None
    print(f"Database schema is up to date (revision {revision}).")


if __name__ == "__main__":
    main()
