"""Alembic environment: run the migrations against Reticle's own database.

The engine comes from the application, not from ``alembic.ini``. That keeps one
source of truth for where the data lives and means SQLite is opened here with
the same settings the server uses — foreign keys on, write-ahead logging, and an
explicit ``BEGIN IMMEDIATE`` so a migration holds the write lock from its first
statement instead of discovering halfway that it cannot get it.

``render_as_batch`` is on because SQLite cannot alter most things in place.
Alembic's batch mode rebuilds the table instead, and on PostgreSQL the same
migration script runs as ordinary ``ALTER`` statements.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from app.db import WRITE_INTENT, build_engine
from app.models import Base  # imported from models, not db, so every table is registered on it
from app.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def run_migrations() -> None:
    engine = config.attributes.get("engine") or build_engine(get_settings().database_url)
    with engine.execution_options(**{WRITE_INTENT: True}).connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit(
        "Reticle's migrations run against a live database only. Use `python -m app.migrate`."
    )

run_migrations()
