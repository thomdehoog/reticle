"""Readers are served the published snapshot; credentials get an epoch.

Revision ID: 0004
Revises: 0003

Until now a reader was shown the same rows the editor autosaves into, so an
edit to a published guide was live the moment it was typed. From this revision
on the rows are the working copy and readers get the snapshot written at the
last publish. That needs somewhere to ask "which published guides carry this
tag" without opening every snapshot, which is what the five ``published_*``
tables are: the listing columns, tags, search text and uploads of whatever is
currently published, written by each publish from then on.

**The backfill.** Everything already published has a snapshot — every publish
has always written one — so the tables are filled here from each item's latest
revision. ``snapshot_updated_at`` is set to the ``updatedAt`` recorded *inside*
that snapshot, which is the moment the working copy and the snapshot last
agreed. Where a guide was edited after its last publish the two timestamps
differ, the guide comes up as having unpublished changes, and readers are back
on the version that was actually published: the edits are not lost, they are
waiting in the editor for somebody to publish or discard them. An item marked
published that has no snapshot at all is left without a projection, so readers
stop seeing it until it is published again; no code path can have produced one.

``users.auth_epoch`` counts password changes, resets and deactivations. The
device cookie that marks a browser as known to an account is signed over it,
so raising it retires every such cookie. Existing accounts start at 0, and
cookies of the old format simply stop verifying, which costs their holders
nothing but the standing they would have re-earned at their next sign-in.

The helpers below are deliberately copies rather than imports from ``app``: a
migration has to keep doing what it did on the day it was written, whatever the
application's own functions turn into later.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


MEDIA_REFERENCE = re.compile(r"/api/media/([0-9A-Za-z]{26})(?![0-9A-Za-z])")


def _instant(value: object) -> datetime | None:
    """A wire timestamp as the naive UTC value the columns hold."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _search_text(document: dict) -> str:
    lines: list[str] = []
    for step in document.get("steps") or []:
        lines.append(str(step.get("title") or ""))
        lines.extend(str(bullet.get("text") or "") for bullet in step.get("bullets") or [])
    return "\n".join(line for line in lines if line.strip())


def _latest_revisions(connection: sa.Connection, table: str, owner: str) -> list[sa.Row]:
    """Each published item with the newest of its snapshots."""
    return connection.execute(
        sa.text(
            f"SELECT item.id AS item_id, item.updated_at AS updated_at, revision.id AS revision_id, "
            f"revision.document AS document "
            f"FROM {table} AS item JOIN {table[:-1]}_revisions AS revision ON revision.{owner} = item.id "
            f"WHERE item.status = 'published' AND revision.version = "
            f"(SELECT MAX(newest.version) FROM {table[:-1]}_revisions AS newest WHERE newest.{owner} = item.id)"
        )
    ).all()


def _backfill(connection: sa.Connection) -> None:
    published_guides = sa.table(
        "published_guides",
        sa.column("guide_id"), sa.column("revision_id"), sa.column("title"), sa.column("summary"),
        sa.column("category_id"), sa.column("difficulty"), sa.column("time_required_min_minutes"),
        sa.column("time_required_max_minutes"), sa.column("step_count"), sa.column("search_text"),
    )
    published_guide_tags = sa.table("published_guide_tags", sa.column("guide_id"), sa.column("tag_id"))
    published_guide_media = sa.table("published_guide_media", sa.column("guide_id"), sa.column("media_id"))
    published_pages = sa.table(
        "published_pages",
        sa.column("page_id"), sa.column("revision_id"), sa.column("title"), sa.column("summary"),
        sa.column("category_id"), sa.column("is_landing", sa.Boolean()), sa.column("body"),
    )
    published_page_media = sa.table("published_page_media", sa.column("page_id"), sa.column("media_id"))
    guides = sa.table("guides", sa.column("id"), sa.column("snapshot_updated_at", sa.DateTime()))
    pages = sa.table("pages", sa.column("id"), sa.column("snapshot_updated_at", sa.DateTime()))

    tag_ids = dict(connection.execute(sa.text("SELECT slug, id FROM tags")).all())
    media_ids = set(connection.execute(sa.text("SELECT id FROM media")).scalars())
    category_ids = set(connection.execute(sa.text("SELECT id FROM categories")).scalars())
    guide_categories = dict(connection.execute(sa.text("SELECT id, category_id FROM guides")).all())

    for row in _latest_revisions(connection, "guides", "guide_id"):
        document = json.loads(row.document)
        category_id = document.get("categoryId")
        if category_id not in category_ids:
            category_id = guide_categories[row.item_id]
        connection.execute(
            sa.insert(published_guides).values(
                guide_id=row.item_id,
                revision_id=row.revision_id,
                title=str(document.get("title") or "")[:240],
                summary=str(document.get("summary") or ""),
                category_id=category_id,
                difficulty=document.get("difficulty") or "moderate",
                time_required_min_minutes=document.get("timeRequiredMinMinutes"),
                time_required_max_minutes=document.get("timeRequiredMaxMinutes"),
                step_count=len(document.get("steps") or []),
                search_text=_search_text(document),
            )
        )
        for tag_id in sorted({tag_ids[slug] for slug in document.get("tags") or [] if slug in tag_ids}):
            connection.execute(sa.insert(published_guide_tags).values(guide_id=row.item_id, tag_id=tag_id))
        shown = {
            entry.get("id") for step in document.get("steps") or [] for entry in step.get("media") or []
        }
        for media_id in sorted(shown & media_ids):
            connection.execute(sa.insert(published_guide_media).values(guide_id=row.item_id, media_id=media_id))
        connection.execute(
            sa.update(guides)
            .where(guides.c.id == row.item_id)
            .values(snapshot_updated_at=_instant(document.get("updatedAt")))
        )

    for row in _latest_revisions(connection, "pages", "page_id"):
        document = json.loads(row.document)
        category_id = document.get("categoryId")
        body = str(document.get("body") or "")
        connection.execute(
            sa.insert(published_pages).values(
                page_id=row.item_id,
                revision_id=row.revision_id,
                title=str(document.get("title") or "")[:240],
                summary=str(document.get("summary") or ""),
                category_id=category_id if category_id in category_ids else None,
                is_landing=bool(document.get("isLanding")),
                body=body,
            )
        )
        shown = set(MEDIA_REFERENCE.findall(body))
        if document.get("heroMediaId"):
            shown.add(document["heroMediaId"])
        for media_id in sorted(shown & media_ids):
            connection.execute(sa.insert(published_page_media).values(page_id=row.item_id, media_id=media_id))
        connection.execute(
            sa.update(pages)
            .where(pages.c.id == row.item_id)
            .values(snapshot_updated_at=_instant(document.get("updatedAt")))
        )


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('auth_epoch', sa.Integer(), server_default='0', nullable=False))
    with op.batch_alter_table('guides', schema=None) as batch_op:
        batch_op.add_column(sa.Column('snapshot_updated_at', sa.DateTime(), nullable=True))
    with op.batch_alter_table('pages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('snapshot_updated_at', sa.DateTime(), nullable=True))

    op.create_table('published_guides',
    sa.Column('guide_id', sa.String(length=26), nullable=False),
    sa.Column('revision_id', sa.String(length=26), nullable=False),
    sa.Column('title', sa.String(length=240), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('category_id', sa.String(length=26), nullable=False),
    sa.Column('difficulty', sa.String(length=20), nullable=False),
    sa.Column('time_required_min_minutes', sa.Integer(), nullable=True),
    sa.Column('time_required_max_minutes', sa.Integer(), nullable=True),
    sa.Column('step_count', sa.Integer(), nullable=False),
    sa.Column('search_text', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ),
    sa.ForeignKeyConstraint(['guide_id'], ['guides.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['revision_id'], ['guide_revisions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('guide_id')
    )
    with op.batch_alter_table('published_guides', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_published_guides_category_id'), ['category_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_published_guides_revision_id'), ['revision_id'], unique=False)

    op.create_table('published_guide_tags',
    sa.Column('guide_id', sa.String(length=26), nullable=False),
    sa.Column('tag_id', sa.String(length=26), nullable=False),
    sa.ForeignKeyConstraint(['guide_id'], ['published_guides.guide_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('guide_id', 'tag_id')
    )
    with op.batch_alter_table('published_guide_tags', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_published_guide_tags_tag_id'), ['tag_id'], unique=False)

    op.create_table('published_guide_media',
    sa.Column('guide_id', sa.String(length=26), nullable=False),
    sa.Column('media_id', sa.String(length=26), nullable=False),
    sa.ForeignKeyConstraint(['guide_id'], ['published_guides.guide_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['media_id'], ['media.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('guide_id', 'media_id')
    )
    with op.batch_alter_table('published_guide_media', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_published_guide_media_media_id'), ['media_id'], unique=False)

    op.create_table('published_pages',
    sa.Column('page_id', sa.String(length=26), nullable=False),
    sa.Column('revision_id', sa.String(length=26), nullable=False),
    sa.Column('title', sa.String(length=240), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('category_id', sa.String(length=26), nullable=True),
    sa.Column('is_landing', sa.Boolean(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ),
    sa.ForeignKeyConstraint(['page_id'], ['pages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['revision_id'], ['page_revisions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('page_id')
    )
    with op.batch_alter_table('published_pages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_published_pages_category_id'), ['category_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_published_pages_revision_id'), ['revision_id'], unique=False)

    op.create_table('published_page_media',
    sa.Column('page_id', sa.String(length=26), nullable=False),
    sa.Column('media_id', sa.String(length=26), nullable=False),
    sa.ForeignKeyConstraint(['media_id'], ['media.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['page_id'], ['published_pages.page_id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('page_id', 'media_id')
    )
    with op.batch_alter_table('published_page_media', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_published_page_media_media_id'), ['media_id'], unique=False)

    _backfill(op.get_bind())


def downgrade() -> None:
    with op.batch_alter_table('published_page_media', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_published_page_media_media_id'))
    op.drop_table('published_page_media')

    with op.batch_alter_table('published_pages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_published_pages_revision_id'))
        batch_op.drop_index(batch_op.f('ix_published_pages_category_id'))
    op.drop_table('published_pages')

    with op.batch_alter_table('published_guide_media', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_published_guide_media_media_id'))
    op.drop_table('published_guide_media')

    with op.batch_alter_table('published_guide_tags', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_published_guide_tags_tag_id'))
    op.drop_table('published_guide_tags')

    with op.batch_alter_table('published_guides', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_published_guides_revision_id'))
        batch_op.drop_index(batch_op.f('ix_published_guides_category_id'))
    op.drop_table('published_guides')

    # Plain ALTER TABLE ... DROP COLUMN, not batch mode. Batch mode drops a
    # column on SQLite by rebuilding the table, and a rebuild of ``users`` —
    # which nearly every other table points at — is refused by the foreign keys
    # as soon as there is a single row. None of these columns is indexed or
    # constrained, which is all SQLite (3.35 and later) asks before dropping one.
    op.drop_column('pages', 'snapshot_updated_at')
    op.drop_column('guides', 'snapshot_updated_at')
    op.drop_column('users', 'auth_epoch')
