"""The facility's name, tagline and picture become data

A front page that can only be changed by editing a file on the server and
restarting is a front page the facility cannot change. The environment keeps the
same variables and they become the values a fresh installation starts with,
filled into this row the first time anything asks for them.

Revision ID: c9a1f4e27b30
Revises: a307e0dfe4d8
Create Date: 2026-08-06

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9a1f4e27b30"
down_revision: Union[str, Sequence[str], None] = "a307e0dfe4d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organisation",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        # No `server_default`. The models do not declare one, and a default that
        # exists only in the database is drift the autogenerate check reports on
        # every run afterwards. The row is written by `organisation.load`, which
        # supplies every column.
        sa.Column("short_name", sa.String(length=40), nullable=False),
        sa.Column("url", sa.String(length=300), nullable=True),
        sa.Column("tagline", sa.Text(), nullable=False),
        sa.Column("hero_media_id", sa.String(length=26), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["hero_media_id"], ["media.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_organisation_hero_media_id"), "organisation", ["hero_media_id"], unique=False
    )
    # No row is inserted here. The values a facility starts with come from its
    # environment, and a migration cannot read the running process's settings —
    # so the row is written the first time the configuration is asked for, by
    # code that can.


def downgrade() -> None:
    op.drop_index(op.f("ix_organisation_hero_media_id"), table_name="organisation")
    op.drop_table("organisation")
