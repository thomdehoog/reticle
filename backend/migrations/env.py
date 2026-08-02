"""How Alembic finds the database and the models.

The one thing worth knowing before editing this file: **the URL is not
configured here and must never be.** ``alembic.ini`` ships with no
``sqlalchemy.url``, and this module asks the application's own settings for it
instead. A URL written into the ini is a URL that gets committed, gets copied
between facilities, and eventually points a migration at the wrong database —
the one mistake in this area that rolling back does not undo.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401  -- importing registers every mapper
from app.db import Base, build_engine
from app.settings import get_settings

config = context.config

# Only when Alembic is the program. ``fileConfig`` reconfigures logging
# process-wide, so doing it unconditionally would let an in-process call from
# ``init_db`` silently replace the application's own logging setup at startup —
# and the symptom of that is request logs disappearing, which nobody notices
# until they are needed.
if config.config_file_name is not None and config.attributes.get("connection") is None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    """The URL the application itself would use.

    ``-x url=...`` overrides it, which is how CI points these migrations at a
    PostgreSQL container without inventing a second settings file, and how a
    hosted deployment loops one migration run over a database per facility.
    """
    override = context.get_x_argument(as_dictionary=True).get("url")
    return override or get_settings().database_url


# Both configurations share these. ``render_as_batch`` matters most: SQLite
# cannot ALTER a column, so Alembic rebuilds the table instead. Without it the
# first migration that alters a column fails at the least convenient possible
# moment — on a facility's server, mid-deploy. PostgreSQL ignores it.
#
# The two ``compare_*`` flags only affect autogenerate, and they are on because
# the alternative is autogenerate quietly omitting a changed column type and the
# difference being discovered later by a query returning the wrong thing.
OPTIONS = {
    "target_metadata": target_metadata,
    "render_as_batch": True,
    "compare_type": True,
    "compare_server_default": True,
}


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it.

    This is how a DBA reviews what a release will do before it does it, and it
    needs no database driver at all.
    """
    context.configure(
        url=database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **OPTIONS,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # ``init_db`` calls Alembic in-process and hands over the engine it already
    # has. Honouring that matters for more than tidiness: an in-memory SQLite
    # database exists only inside the connection that made it, so building a
    # second engine here would migrate a different, empty database and leave
    # the real one untouched.
    supplied = config.attributes.get("connection")
    if supplied is not None:
        with supplied.connect() as connection:
            context.configure(connection=connection, **OPTIONS)
            with context.begin_transaction():
                context.run_migrations()
        return

    engine = build_engine(database_url())
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, **OPTIONS)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        # A migration run is a short-lived process. Leaving the pool open holds
        # connections against a database somebody may be about to restart.
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
