"""add_agent_voice_configs

Revision ID: 20260901_0001
Revises: 20260831_vapi
Create Date: 2026-09-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260901_0001"
down_revision = "20260831_vapi"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "agent_voice_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vapi_assistant_id", sa.String(length=255), nullable=True),
        sa.Column("vapi_phone_number_id", sa.String(length=255), nullable=True),
        sa.Column("phone_number_e164", sa.String(length=20), nullable=True),
        sa.Column("voice_provider", sa.String(length=50), server_default="elevenlabs", nullable=True),
        sa.Column("voice_id", sa.String(length=100), server_default="21m00Tcm4TlvDq8ikWAM", nullable=True),
        sa.Column("stability", sa.Float(), server_default="0.5", nullable=True),
        sa.Column("similarity_boost", sa.Float(), server_default="0.75", nullable=True),
        sa.Column("speed", sa.Float(), server_default="1.0", nullable=True),
        sa.Column("filler_injection_enabled", sa.Boolean(), server_default="true", nullable=True),
        sa.Column("model_provider", sa.String(length=50), server_default="openai", nullable=True),
        sa.Column("model_name", sa.String(length=50), server_default="gpt-4o", nullable=True),
        sa.Column("temperature", sa.Float(), server_default="0.3", nullable=True),
        sa.Column("first_message", sa.Text(), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("silence_timeout_seconds", sa.Integer(), server_default="30", nullable=True),
        sa.Column("max_duration_seconds", sa.Integer(), server_default="1800", nullable=True),
        sa.Column("background_sound", sa.String(length=20), server_default="off", nullable=True),
        sa.Column("transfer_phone_number", sa.String(length=20), nullable=True),
        sa.Column("business_hours_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_agent_voice_vapi_id", "agent_voice_configs", ["vapi_assistant_id"], unique=False)
    op.create_index("idx_agent_voice_tenant", "agent_voice_configs", ["tenant_id"], unique=False)

def downgrade():
    op.drop_index("idx_agent_voice_tenant", table_name="agent_voice_configs")
    op.drop_index("idx_agent_voice_vapi_id", table_name="agent_voice_configs")
    op.drop_table("agent_voice_configs")
