"""a guide can be published and still staff-only

Revision ID: a307e0dfe4d8
Revises: 054bf164fdb8
Create Date: 2026-08-02 13:58:32.898054

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
revision: str = 'a307e0dfe4d8'
down_revision: Union[str, Sequence[str], None] = '054bf164fdb8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Every guide that already exists was readable by everyone.

    In two moves, and the second is the one autogenerate leaves out. The column
    is added with a server default so the rows already in the table get a value
    — a bare ``NOT NULL`` add fails outright against a populated ``guides``,
    which is every facility that has ever written one. The default is then
    dropped, because the application supplies the value on every insert and a
    default left behind is schema drift: ``compare_server_default`` reports it
    on the next autogenerate, and the next person has to work out whether it was
    deliberate.

    ``everyone`` is the right backfill and not merely the convenient one: until
    this column existed the only way to keep a guide internal was to leave it
    unpublished, so a published guide in an existing database is one somebody
    published to the whole institute on purpose.
    """
    op.add_column(
        'guides',
        sa.Column('visibility', sa.String(length=16), nullable=False, server_default='everyone'),
    )
    op.alter_column('guides', 'visibility', server_default=None)


def downgrade() -> None:
    """Drop the column, and with it the staff-only distinction.

    **A staff guide comes back readable by everyone**, because the older schema
    has no way to say otherwise and the guides themselves are published. Anybody
    rolling a release back across this migration has to unpublish those guides
    first; there is no version of this downgrade that keeps them internal, so it
    says so here rather than appearing to.
    """
    op.drop_column('guides', 'visibility')
