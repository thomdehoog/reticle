"""Import records: which vendor item became which Reticle row.

Revision ID: 0002
Revises: 0001

Added for the one-off content import (``python -m app.importer``). The table is
what makes that import re-runnable: a second run finds the row it wrote the
first time and updates it instead of creating a duplicate, and it can tell that
a guide was edited in Reticle since and must be left alone.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('import_records',
    sa.Column('id', sa.String(length=26), nullable=False),
    sa.Column('source', sa.String(length=200), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('vendor_id', sa.String(length=300), nullable=False),
    sa.Column('reticle_id', sa.String(length=26), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('imported_updated_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'kind', 'vendor_id', name='uq_import_record_source_item')
    )
    with op.batch_alter_table('import_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_import_records_reticle_id'), ['reticle_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('import_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_import_records_reticle_id'))

    op.drop_table('import_records')
