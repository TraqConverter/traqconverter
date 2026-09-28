"""baseline schema (squashes the 43 pre-2026-09 migrations; keeps the old head id so stamped DBs stay current)

Revision ID: d39e8a51bcaf
Revises: 
Create Date: 2026-09-25 16:17:54.942356

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd39e8a51bcaf'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('stripe_events',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('event_type', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_stripe_events_id'), 'stripe_events', ['id'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('email', sa.String(), nullable=False),
    sa.Column('password_hash', sa.String(), nullable=False),
    sa.Column('full_name', sa.String(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('subscription_status', sa.String(), nullable=True),
    sa.Column('stripe_customer_id', sa.String(), nullable=True),
    sa.Column('stripe_subscription_id', sa.String(), nullable=True),
    sa.Column('subscription_current_period_end', sa.DateTime(), nullable=True),
    sa.Column('subscription_plan', sa.String(), nullable=False),
    sa.Column('role', sa.String(), nullable=False),
    sa.Column('certification_file', sa.String(), nullable=True),
    sa.Column('logo_s3_key', sa.String(), nullable=True),
    sa.Column('token_version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_table('teams',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('address', sa.String(), nullable=True),
    sa.Column('stamp_s3_key', sa.String(), nullable=True),
    sa.Column('stamp_alignment', sa.String(), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('certifications',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('team_id', sa.UUID(), nullable=False),
    sa.Column('uploaded_by', sa.UUID(), nullable=True),
    sa.Column('file_name', sa.String(), nullable=False),
    sa.Column('file_path', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('file_hash', sa.String(length=64), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('mime_type', sa.String(), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('credit_wallets',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('team_id', sa.UUID(), nullable=True),
    sa.Column('subscription_credits', sa.Integer(), nullable=True),
    sa.Column('purchased_credits', sa.Integer(), nullable=True),
    sa.Column('plan_type', sa.String(), nullable=True),
    sa.Column('subscription_status', sa.String(), nullable=True),
    sa.Column('subscription_expires_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint('purchased_credits >= 0', name='check_purchased_credits_non_negative'),
    sa.CheckConstraint('subscription_credits >= 0', name='check_subscription_credits_non_negative'),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('glossary',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('team_id', sa.UUID(), nullable=False),
    sa.Column('source_language', sa.String(), nullable=False),
    sa.Column('target_language', sa.String(), nullable=False),
    sa.Column('source_term', sa.Text(), nullable=False),
    sa.Column('target_term', sa.Text(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('usage_count', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('jobs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('team_id', sa.UUID(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('source_language', sa.String(), nullable=False),
    sa.Column('target_language', sa.String(), nullable=False),
    sa.Column('page_count', sa.Integer(), nullable=False),
    sa.Column('credits_used', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('team_invites',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('team_id', sa.UUID(), nullable=False),
    sa.Column('email', sa.String(), nullable=False),
    sa.Column('role', sa.String(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('invited_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['invited_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_team_invites_email'), 'team_invites', ['email'], unique=False)
    op.create_table('team_members',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('team_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('role', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('team_id', 'user_id', name='uq_team_member')
    )
    op.create_table('translation_memory',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('team_id', sa.UUID(), nullable=False),
    sa.Column('source_language', sa.String(), nullable=False),
    sa.Column('target_language', sa.String(), nullable=False),
    sa.Column('source_text', sa.Text(), nullable=False),
    sa.Column('translated_text', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_tm_lookup', 'translation_memory', ['team_id', 'source_language', 'target_language', 'source_text'], unique=False)
    op.create_table('credit_transactions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('wallet_id', sa.UUID(), nullable=True),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('reference_id', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['wallet_id'], ['credit_wallets.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('translation_projects',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('team_id', sa.UUID(), nullable=False),
    sa.Column('assignee_id', sa.UUID(), nullable=True),
    sa.Column('file_name', sa.String(), nullable=False),
    sa.Column('file_path', sa.String(), nullable=False),
    sa.Column('output_file', sa.String(), nullable=True),
    sa.Column('page_count', sa.Integer(), nullable=False),
    sa.Column('credits_used', sa.Integer(), nullable=False),
    sa.Column('idempotency_key', sa.String(), nullable=True),
    sa.Column('status', sa.Enum('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', name='project_status_enum'), nullable=False),
    sa.Column('progress_percent', sa.Integer(), nullable=False),
    sa.Column('total_segments', sa.Integer(), nullable=False),
    sa.Column('translated_segments', sa.Integer(), nullable=False),
    sa.Column('retry_count', sa.Integer(), nullable=False),
    sa.Column('last_heartbeat', sa.DateTime(), nullable=True),
    sa.Column('add_certification', sa.Boolean(), nullable=False),
    sa.Column('use_tm', sa.Boolean(), nullable=False),
    sa.Column('apply_glossary', sa.Boolean(), nullable=False),
    sa.Column('source_language', sa.String(), nullable=False),
    sa.Column('target_language', sa.String(), nullable=False),
    sa.Column('model', sa.String(), nullable=False),
    sa.Column('review_status', sa.String(), nullable=False),
    sa.Column('source_kind', sa.String(), nullable=True),
    sa.Column('certification_override_text', sa.String(), nullable=True),
    sa.Column('certification_template_id', sa.UUID(), nullable=True),
    sa.Column('authored_docx_s3_key', sa.String(), nullable=True),
    sa.Column('edited_html', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['certification_template_id'], ['certifications.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_translation_projects_idempotency_key'), 'translation_projects', ['idempotency_key'], unique=True)
    op.create_table('translation_segments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('segment_index', sa.Integer(), nullable=False),
    sa.Column('source_text', sa.Text(), nullable=False),
    sa.Column('translated_text', sa.Text(), nullable=True),
    sa.Column('approved', sa.Boolean(), nullable=False),
    sa.Column('tm_pct', sa.Integer(), nullable=True),
    sa.Column('layout_meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['translation_projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('segment_comments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('segment_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('resolved', sa.Boolean(), nullable=True),
    sa.ForeignKeyConstraint(['segment_id'], ['translation_segments.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('translation_jobs',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('s3_key', sa.String(), nullable=False),
    sa.Column('status', sa.String(), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('locked_at', sa.DateTime(), nullable=True),
    sa.Column('locked_by', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['translation_projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_translation_jobs_pending', 'translation_jobs', ['created_at'], postgresql_where=sa.text("status = 'pending'"))
    op.create_index('idx_translation_jobs_project', 'translation_jobs', ['project_id', 'created_at'])


def downgrade() -> None:
    op.drop_table('translation_jobs')
    op.drop_table('segment_comments')
    op.drop_table('translation_segments')
    op.drop_index(op.f('ix_translation_projects_idempotency_key'), table_name='translation_projects')
    op.drop_table('translation_projects')
    sa.Enum(name='project_status_enum').drop(op.get_bind(), checkfirst=True)
    op.drop_table('credit_transactions')
    op.drop_index('idx_tm_lookup', table_name='translation_memory')
    op.drop_table('translation_memory')
    op.drop_table('team_members')
    op.drop_index(op.f('ix_team_invites_email'), table_name='team_invites')
    op.drop_table('team_invites')
    op.drop_table('jobs')
    op.drop_table('glossary')
    op.drop_table('credit_wallets')
    op.drop_table('certifications')
    op.drop_table('teams')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_stripe_events_id'), table_name='stripe_events')
    op.drop_table('stripe_events')
