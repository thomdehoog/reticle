"""A section stacks its groups in an order it chooses

A section's page is a stack of groups and a group is a tag, so the order of the
groups is an order of tags — and it belongs to the section rather than to the
tags, because `Talos` comes first in the electron-microscopy section and means
nothing in the light-microscopy one.

Alphabetical was the fallback and is nobody's running order: start-up,
acquisition, shutdown is the sequence somebody works in, and sorting it gives
`acquisition, shutdown, start-up`.

A table rather than a list of slugs on the category, for the cascade: a tag that
stops existing leaves the orders it was in without anything having to remember
to tidy up after it.

Revision ID: e7c2b91f5d04
Revises: d4b7e0c81a52
Create Date: 2026-08-06

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7c2b91f5d04"
down_revision: Union[str, Sequence[str], None] = "d4b7e0c81a52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "category_tag_order",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("category_id", sa.String(length=26), nullable=False),
        sa.Column("tag_id", sa.String(length=26), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category_id", "tag_id", name="uq_category_tag_order"),
    )
    op.create_index(
        op.f("ix_category_tag_order_category_id"),
        "category_tag_order",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_category_tag_order_tag_id"), "category_tag_order", ["tag_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_category_tag_order_tag_id"), table_name="category_tag_order")
    op.drop_index(op.f("ix_category_tag_order_category_id"), table_name="category_tag_order")
    op.drop_table("category_tag_order")
