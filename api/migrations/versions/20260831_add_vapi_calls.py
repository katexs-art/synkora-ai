"""Add vapi_calls and voice fields

Revision ID: 20260831_vapi
Revises: 20260824_0001
Create Date: 2026-08-31

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260831_vapi'
down_revision = '20260824_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Vapi calls table - references tenants (not workspaces) and agents
    op.create_table(
        'vapi_calls',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('vapi_call_id', sa.String(255), nullable=False, unique=True),
        sa.Column('phone_number', sa.String(20), nullable=False),
        sa.Column('direction', sa.String(10), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('cost_cents', sa.Integer(), nullable=True),
        sa.Column('transcript', sa.Text(), nullable=True),
        sa.Column('recording_url', sa.String(500), nullable=True),
        sa.Column('customer_phone', sa.String(20), nullable=True),
        sa.Column('customer_name', sa.String(255), nullable=True),
        sa.Column('outcome', sa.String(50), nullable=True),
        sa.Column('containment', sa.Boolean(), nullable=True),
        sa.Column('extracted_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('vapi_call_id')
    )
    
    op.create_index('idx_vapi_calls_tenant', 'vapi_calls', ['tenant_id', 'created_at'])
    op.create_index('idx_vapi_calls_agent', 'vapi_calls', ['agent_id', 'created_at'])
    op.create_index('idx_vapi_calls_outcome', 'vapi_calls', ['outcome'])
    
    # Add voice fields to agents table
    op.add_column('agents', sa.Column('vapi_assistant_id', sa.String(255), nullable=True))
    op.add_column('agents', sa.Column('voice_provider', sa.String(50), nullable=True))
    op.add_column('agents', sa.Column('voice_id', sa.String(255), nullable=True))
    op.add_column('agents', sa.Column('voice_stability', sa.Float(), nullable=True))
    op.add_column('agents', sa.Column('voice_similarity_boost', sa.Float(), nullable=True))
    op.add_column('agents', sa.Column('filler_injection_enabled', sa.Boolean(), nullable=True))
    op.add_column('agents', sa.Column('phone_number_id', sa.String(255), nullable=True))
    op.add_column('agents', sa.Column('phone_number', sa.String(20), nullable=True))
    op.add_column('agents', sa.Column('business_hours', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('agents', sa.Column('transfer_rules', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('agents', sa.Column('vapi_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_table('vapi_calls')
    op.drop_column('agents', 'vapi_assistant_id')
    op.drop_column('agents', 'voice_provider')
    op.drop_column('agents', 'voice_id')
    op.drop_column('agents', 'voice_stability')
    op.drop_column('agents', 'voice_similarity_boost')
    op.drop_column('agents', 'filler_injection_enabled')
    op.drop_column('agents', 'phone_number_id')
    op.drop_column('agents', 'phone_number')
    op.drop_column('agents', 'business_hours')
    op.drop_column('agents', 'transfer_rules')
    op.drop_column('agents', 'vapi_config')
