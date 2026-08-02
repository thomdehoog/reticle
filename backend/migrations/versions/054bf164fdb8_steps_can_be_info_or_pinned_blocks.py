"""steps can be info or pinned blocks

Revision ID: 054bf164fdb8
Revises: 33f74dd4aa4f
Create Date: 2026-08-02 12:50:23.291552

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
revision: str = '054bf164fdb8'
down_revision: Union[str, Sequence[str], None] = '33f74dd4aa4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Every step that already exists is a numbered step.

    In two moves, and the second is the one autogenerate leaves out. The column
    is added with a server default so the rows already in the table get a value
    — a bare ``NOT NULL`` add fails outright against a populated ``steps``, which
    is every facility that has ever written a guide. The default is then dropped,
    because the application supplies the value on every insert and a default left
    behind is schema drift: ``compare_server_default`` reports it on the next
    autogenerate, and the next person has to work out whether it was deliberate.
    """
    op.add_column(
        "steps",
        sa.Column("kind", sa.String(length=8), nullable=False, server_default="step"),
    )
    op.alter_column("steps", "kind", server_default=None)


def downgrade() -> None:
    """Drop the column, and with it any info or pinned block's kind.

    The blocks themselves survive as ordinary steps, which is the honest
    outcome: the text, the pictures and the shapes drawn on them are all still
    there, and only the distinction between a numbered step and a callout is
    lost. Nothing else in the schema depends on it.
    """
    op.drop_column("steps", "kind")
