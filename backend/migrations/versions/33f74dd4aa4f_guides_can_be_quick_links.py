"""Guides can be quick links

Adds ``guides.is_quick_link``: the flag that promotes a guide out of a list and
onto the front page or a category page as a picture-and-text block.

The column is added with a server default of false so that every guide already
in the database gets a value — the column is NOT NULL, and PostgreSQL cannot
add one to a table that already holds rows without being told what those rows
should say. The default is then dropped, because the models describe no server
default and a column carrying one the metadata does not know about is schema
drift that ``test_migrations`` reports on the next release.

Revision ID: 33f74dd4aa4f
Revises: b1cac76587e4
Create Date: 2026-08-02 08:17:03.818037

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Autogenerate renders the project's own column types by their full path -
# `app.db.UtcDateTime()` - and does not add the import that makes that name
# resolve. Without this line every generated migration raises NameError the
# first time it runs, which is on somebody's server during a deploy.
import app.db


# revision identifiers, used by Alembic.
revision: str = '33f74dd4aa4f'
down_revision: Union[str, Sequence[str], None] = 'b1cac76587e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('guides', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('is_quick_link', sa.Boolean(), nullable=False, server_default=sa.false())
        )

    # Separate from the block above on purpose: SQLite cannot drop a default in
    # place, so this one rebuilds the table, and asking one batch to both add a
    # column and rebuild around it would copy the existing rows before they had
    # a value to copy.
    with op.batch_alter_table('guides', schema=None) as batch_op:
        batch_op.alter_column(
            'is_quick_link',
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=None,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('guides', schema=None) as batch_op:
        batch_op.drop_column('is_quick_link')
