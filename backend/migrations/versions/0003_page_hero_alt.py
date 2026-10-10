"""A description for a page's hero image.

Revision ID: 0003
Revises: 0002

A page could name its hero image but not describe it, so the picture at the top
of every landing page was announced to a screen reader as nothing at all. The
description belongs to the page rather than to the upload — the same picture
may head two pages — and existing pages start with an empty one, which is what
they effectively had.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('pages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('hero_alt', sa.Text(), server_default='', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('pages', schema=None) as batch_op:
        batch_op.drop_column('hero_alt')
