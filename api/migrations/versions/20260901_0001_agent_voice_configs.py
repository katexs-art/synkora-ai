"""Agent voice configs and vapi calls tables"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260901_0001'
down_revision = '20260831_vapi'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'agent_voice_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('vapi_assistant_id', sa.String(255)),
        sa.Column('vapi_phone_number_id', sa.String(255)),
        sa.Column('phone_number_e164', sa.String(20)),
        sa.Column('voice_provider', sa.String(50), server_default='elevenlabs'),
        sa.Column('voice_id', sa.String(100), server_default='21m00Tcm4TlvDq8ikWAM'),
        sa.Column('stability', sa.Float(), server_default='0.5'),
        sa.Column('similarity_boost', sa.Float(), server_default='0.75'),
        sa.Column('speed', sa.Float(), server_default='1.0'),
        sa.Column('filler_injection_enabled', sa.Boolean(), server_default='true'),
        sa.Column('model_provider', sa.String(50), server_default='openai'),
        sa.Column('model_name', sa.String(50), server_default='gpt-4o'),
        sa.Column('temperature', sa.Float(), server_default='0.3'),
        sa.Column('first_message', sa.Text()),
        sa.Column('system_prompt', sa.Text()),
        sa.Column('silence_timeout_seconds', sa.Integer(), server_default='30'),
        sa.Column('max_duration_seconds', sa.Integer(), server_default='1800'),
        sa.Column('background_sound', sa.String(20), server_default='off'),
        sa.Column('transfer_phone_number', sa.String(20)),
        sa.Column('business_hours_json', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_id')
    )
    op.create_index('idx_agent_voice_vapi_id', 'agent_voice_configs', ['vapi_assistant_id'])
    op.create_index('idx_agent_voice_workspace', 'agent_voice_configs', ['workspace_id'])

def downgrade():
    op.drop_table('agent_voice_configs')
