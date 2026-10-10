"""Baseline: the whole schema as of the first release with migrations.

Revision ID: 0001
Revises:

There was no production data before this revision, so it creates every table
outright instead of describing a path from the development builds that came
before it. Column types are spelled out in plain SQLAlchemy rather than imported
from the application: a migration is a record of what the schema *was*, and it
must keep meaning the same thing after ``app.db`` has moved on.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('categories',
    sa.Column('id', sa.String(length=26), nullable=False),
    sa.Column('slug', sa.String(length=200), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('parent_id', sa.String(length=26), nullable=True),
    sa.Column('order_index', sa.Integer(), nullable=False),
    sa.Column('is_hidden', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['parent_id'], ['categories.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('categories', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_categories_parent_id'), ['parent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_categories_slug'), ['slug'], unique=True)

    op.create_table('login_attempts',
    sa.Column('id', sa.String(length=26), nullable=False),
    sa.Column('scope', sa.String(length=8), nullable=False),
    sa.Column('key', sa.String(length=370), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('login_attempts', schema=None) as batch_op:
        batch_op.create_index('ix_login_attempts_created_at', ['created_at'], unique=False)
        batch_op.create_index('ix_login_attempts_scope_key_time', ['scope', 'key', 'created_at'], unique=False)

    op.create_table('tags',
    sa.Column('id', sa.String(length=26), nullable=False),
    sa.Column('slug', sa.String(length=60), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('tags', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tags_slug'), ['slug'], unique=True)

    op.create_table('users',
    sa.Column('id', sa.String(length=26), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    op.create_table('audit_log',
    sa.Column('id', sa.String(length=26), nullable=False),
    sa.Column('actor_id', sa.String(length=26), nullable=True),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('entity_type', sa.String(length=40), nullable=False),
    sa.Column('entity_id', sa.String(length=26), nullable=True),
    sa.Column('detail', sa.Text(), nullable=False),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_log_action'), ['action'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_log_actor_id'), ['actor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_log_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_log_entity_id'), ['entity_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_log_entity_type'), ['entity_type'], unique=False)

    op.create_table('guides',
    sa.Column('category_id', sa.String(length=26), nullable=False),
    sa.Column('difficulty', sa.String(length=20), nullable=False),
    sa.Column('time_required_min_minutes', sa.Integer(), nullable=True),
    sa.Column('time_required_max_minutes', sa.Integer(), nullable=True),
    sa.Column('introduction', sa.Text(), nullable=False),
    sa.Column('conclusion', sa.Text(), nullable=False),
    sa.Column('id', sa.String(length=26), nullable=False),
    sa.Column('slug', sa.String(length=240), nullable=False),
    sa.Column('title', sa.String(length=240), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('view_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('published_at', sa.DateTime(), nullable=True),
    sa.Column('author_id', sa.String(length=26), nullable=False),
    sa.Column('last_edited_by_id', sa.String(length=26), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ),
    sa.ForeignKeyConstraint(['last_edited_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('guides', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_guides_author_id'), ['author_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_guides_category_id'), ['category_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_guides_slug'), ['slug'], unique=True)
        batch_op.create_index(batch_op.f('ix_guides_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_guides_updated_at'), ['updated_at'], unique=False)

    op.create_table('media',
    sa.Column('id', sa.String(length=26), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('storage_path', sa.String(length=300), nullable=False),
    sa.Column('content_type', sa.String(length=60), nullable=False),
    sa.Column('byte_size', sa.BigInteger(), nullable=False),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('alt', sa.Text(), nullable=False),
    sa.Column('original_filename', sa.String(length=300), nullable=False),
    sa.Column('uploaded_by_id', sa.String(length=26), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('storage_path')
    )
    op.create_table('sessions',
    sa.Column('id', sa.String(length=26), nullable=False),
    sa.Column('user_id', sa.String(length=26), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('csrf_token', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(), nullable=True),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('user_agent', sa.String(length=400), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sessions_expires_at'), ['expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_sessions_token_hash'), ['token_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_sessions_user_id'), ['user_id'], unique=False)

    op.create_table('guide_contributors',
    sa.Column('guide_id', sa.String(length=26), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('user_id', sa.String(length=26), nullable=False),
    sa.ForeignKeyConstraint(['guide_id'], ['guides.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('guide_id', 'user_id')
    )
    op.create_table('guide_revisions',
    sa.Column('guide_id', sa.String(length=26), nullable=False),
    sa.Column('id', sa.String(length=26), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('published_at', sa.DateTime(), nullable=False),
    sa.Column('document', sa.Text(), nullable=False),
    sa.Column('published_by_id', sa.String(length=26), nullable=False),
    sa.ForeignKeyConstraint(['guide_id'], ['guides.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['published_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('guide_id', 'version', name='uq_guide_revision_version')
    )
    with op.batch_alter_table('guide_revisions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_guide_revisions_guide_id'), ['guide_id'], unique=False)

    op.create_table('guide_tags',
    sa.Column('guide_id', sa.String(length=26), nullable=False),
    sa.Column('tag_id', sa.String(length=26), nullable=False),
    sa.ForeignKeyConstraint(['guide_id'], ['guides.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('guide_id', 'tag_id')
    )
    with op.batch_alter_table('guide_tags', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_guide_tags_tag_id'), ['tag_id'], unique=False)

    op.create_table('pages',
    sa.Column('category_id', sa.String(length=26), nullable=True),
    sa.Column('is_landing', sa.Boolean(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('hero_media_id', sa.String(length=26), nullable=True),
    sa.Column('id', sa.String(length=26), nullable=False),
    sa.Column('slug', sa.String(length=240), nullable=False),
    sa.Column('title', sa.String(length=240), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('view_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('published_at', sa.DateTime(), nullable=True),
    sa.Column('author_id', sa.String(length=26), nullable=False),
    sa.Column('last_edited_by_id', sa.String(length=26), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ),
    sa.ForeignKeyConstraint(['hero_media_id'], ['media.id'], ),
    sa.ForeignKeyConstraint(['last_edited_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('pages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_pages_author_id'), ['author_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pages_category_id'), ['category_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pages_hero_media_id'), ['hero_media_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_pages_slug'), ['slug'], unique=True)
        batch_op.create_index(batch_op.f('ix_pages_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_pages_updated_at'), ['updated_at'], unique=False)
        batch_op.create_index('uq_pages_one_landing_per_category', ['category_id'], unique=True, sqlite_where=sa.text("is_landing = 1 AND status != 'archived'"), postgresql_where=sa.text("is_landing AND status != 'archived'"))

    op.create_table('steps',
    sa.Column('id', sa.String(length=26), nullable=False),
    sa.Column('guide_id', sa.String(length=26), nullable=False),
    sa.Column('order_index', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=400), nullable=False),
    sa.ForeignKeyConstraint(['guide_id'], ['guides.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('steps', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_steps_guide_id'), ['guide_id'], unique=False)

    op.create_table('bullets',
    sa.Column('id', sa.String(length=26), nullable=False),
    sa.Column('step_id', sa.String(length=26), nullable=False),
    sa.Column('order_index', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('color', sa.String(length=16), nullable=False),
    sa.Column('icon', sa.String(length=16), nullable=True),
    sa.Column('level', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['step_id'], ['steps.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('bullets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bullets_step_id'), ['step_id'], unique=False)

    op.create_table('page_contributors',
    sa.Column('page_id', sa.String(length=26), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('user_id', sa.String(length=26), nullable=False),
    sa.ForeignKeyConstraint(['page_id'], ['pages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('page_id', 'user_id')
    )
    op.create_table('page_media',
    sa.Column('page_id', sa.String(length=26), nullable=False),
    sa.Column('media_id', sa.String(length=26), nullable=False),
    sa.ForeignKeyConstraint(['media_id'], ['media.id'], ),
    sa.ForeignKeyConstraint(['page_id'], ['pages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('page_id', 'media_id')
    )
    with op.batch_alter_table('page_media', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_page_media_media_id'), ['media_id'], unique=False)

    op.create_table('page_revisions',
    sa.Column('page_id', sa.String(length=26), nullable=False),
    sa.Column('id', sa.String(length=26), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('published_at', sa.DateTime(), nullable=False),
    sa.Column('document', sa.Text(), nullable=False),
    sa.Column('published_by_id', sa.String(length=26), nullable=False),
    sa.ForeignKeyConstraint(['page_id'], ['pages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['published_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('page_id', 'version', name='uq_page_revision_version')
    )
    with op.batch_alter_table('page_revisions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_page_revisions_page_id'), ['page_id'], unique=False)

    op.create_table('step_media',
    sa.Column('id', sa.String(length=26), nullable=False),
    sa.Column('step_id', sa.String(length=26), nullable=False),
    sa.Column('media_id', sa.String(length=26), nullable=False),
    sa.Column('order_index', sa.Integer(), nullable=False),
    sa.Column('alt', sa.Text(), nullable=False),
    sa.Column('annotations', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['media_id'], ['media.id'], ),
    sa.ForeignKeyConstraint(['step_id'], ['steps.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('step_id', 'media_id', name='uq_step_media')
    )
    with op.batch_alter_table('step_media', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_step_media_media_id'), ['media_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_step_media_step_id'), ['step_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('step_media', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_step_media_step_id'))
        batch_op.drop_index(batch_op.f('ix_step_media_media_id'))

    op.drop_table('step_media')
    with op.batch_alter_table('page_revisions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_page_revisions_page_id'))

    op.drop_table('page_revisions')
    with op.batch_alter_table('page_media', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_page_media_media_id'))

    op.drop_table('page_media')
    op.drop_table('page_contributors')
    with op.batch_alter_table('bullets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bullets_step_id'))

    op.drop_table('bullets')
    with op.batch_alter_table('steps', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_steps_guide_id'))

    op.drop_table('steps')
    with op.batch_alter_table('pages', schema=None) as batch_op:
        batch_op.drop_index('uq_pages_one_landing_per_category', sqlite_where=sa.text("is_landing = 1 AND status != 'archived'"), postgresql_where=sa.text("is_landing AND status != 'archived'"))
        batch_op.drop_index(batch_op.f('ix_pages_updated_at'))
        batch_op.drop_index(batch_op.f('ix_pages_status'))
        batch_op.drop_index(batch_op.f('ix_pages_slug'))
        batch_op.drop_index(batch_op.f('ix_pages_hero_media_id'))
        batch_op.drop_index(batch_op.f('ix_pages_category_id'))
        batch_op.drop_index(batch_op.f('ix_pages_author_id'))

    op.drop_table('pages')
    with op.batch_alter_table('guide_tags', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_guide_tags_tag_id'))

    op.drop_table('guide_tags')
    with op.batch_alter_table('guide_revisions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_guide_revisions_guide_id'))

    op.drop_table('guide_revisions')
    op.drop_table('guide_contributors')
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sessions_user_id'))
        batch_op.drop_index(batch_op.f('ix_sessions_token_hash'))
        batch_op.drop_index(batch_op.f('ix_sessions_expires_at'))

    op.drop_table('sessions')
    op.drop_table('media')
    with op.batch_alter_table('guides', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_guides_updated_at'))
        batch_op.drop_index(batch_op.f('ix_guides_status'))
        batch_op.drop_index(batch_op.f('ix_guides_slug'))
        batch_op.drop_index(batch_op.f('ix_guides_category_id'))
        batch_op.drop_index(batch_op.f('ix_guides_author_id'))

    op.drop_table('guides')
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_log_entity_type'))
        batch_op.drop_index(batch_op.f('ix_audit_log_entity_id'))
        batch_op.drop_index(batch_op.f('ix_audit_log_created_at'))
        batch_op.drop_index(batch_op.f('ix_audit_log_actor_id'))
        batch_op.drop_index(batch_op.f('ix_audit_log_action'))

    op.drop_table('audit_log')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
    with op.batch_alter_table('tags', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tags_slug'))

    op.drop_table('tags')
    with op.batch_alter_table('login_attempts', schema=None) as batch_op:
        batch_op.drop_index('ix_login_attempts_scope_key_time')
        batch_op.drop_index('ix_login_attempts_created_at')

    op.drop_table('login_attempts')
    with op.batch_alter_table('categories', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_categories_slug'))
        batch_op.drop_index(batch_op.f('ix_categories_parent_id'))

    op.drop_table('categories')
