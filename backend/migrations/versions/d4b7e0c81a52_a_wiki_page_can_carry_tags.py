"""A wiki page can carry tags, as a guide does

A section's page is a stack of groups, and a group is rows pointing at an
endpoint — a guide or a wiki, and a reader has no reason to care which. Until
now only guides could be grouped: every wiki in a section landed in one lump
called "Wikis", not because that was useful but because a page had nothing to be
grouped by.

Deliberately the same shape as ``guide_tags``, down to the ordering column and
the unique constraint. Two ways of belonging to a tag is how the two kinds of
document start behaving differently again.

Revision ID: d4b7e0c81a52
Revises: c9a1f4e27b30
Create Date: 2026-08-06

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4b7e0c81a52"
down_revision: Union[str, Sequence[str], None] = "c9a1f4e27b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "page_tags",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("page_id", sa.String(length=26), nullable=False),
        sa.Column("tag_id", sa.String(length=26), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["page_id"], ["pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("page_id", "tag_id", name="uq_page_tag"),
    )
    op.create_index(op.f("ix_page_tags_page_id"), "page_tags", ["page_id"], unique=False)
    op.create_index(op.f("ix_page_tags_tag_id"), "page_tags", ["tag_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_page_tags_tag_id"), table_name="page_tags")
    op.drop_index(op.f("ix_page_tags_page_id"), table_name="page_tags")
    op.drop_table("page_tags")
