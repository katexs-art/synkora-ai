"""Vapi SQLAlchemy Models"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, UUID, ForeignKey, Text, Float, Boolean, Integer, DateTime, Index
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class AgentVoiceConfig(Base):
    """Vapi voice agent configuration"""
    __tablename__ = "agent_voice_configs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, unique=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    vapi_assistant_id = Column(String(255))
    vapi_phone_number_id = Column(String(255))
    phone_number_e164 = Column(String(20))
    voice_provider = Column(String(50), default="elevenlabs")
    voice_id = Column(String(100), default="21m00Tcm4TlvDq8ikWAM")
    stability = Column(Float, default=0.5)
    similarity_boost = Column(Float, default=0.75)
    speed = Column(Float, default=1.0)
    filler_injection_enabled = Column(Boolean, default=True)
    model_provider = Column(String(50), default="openai")
    model_name = Column(String(50), default="gpt-4o")
    temperature = Column(Float, default=0.3)
    first_message = Column(Text)
    system_prompt = Column(Text)
    silence_timeout_seconds = Column(Integer, default=30)
    max_duration_seconds = Column(Integer, default=1800)
    background_sound = Column(String(20), default="off")
    transfer_phone_number = Column(String(20))
    business_hours_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_agent_voice_vapi_id", "vapi_assistant_id"),
        Index("idx_agent_voice_workspace", "workspace_id"),
    )

class VapiCall(Base):
    """Vapi call tracking"""
    __tablename__ = "vapi_calls"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    vapi_call_id = Column(String(255), nullable=False, unique=True)
    vapi_assistant_id = Column(String(255))
    phone_number = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)
    status = Column(String(20), nullable=False)
    started_at = Column(DateTime)
    ended_at = Column(DateTime)
    duration_seconds = Column(Integer)
    cost_cents = Column(Integer)
    transcript = Column(Text)
    recording_url = Column(Text)
    customer_phone = Column(String(20))
    customer_name = Column(String(255))
    outcome = Column(String(50))
    containment = Column(Boolean)
    summary = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_vapi_calls_workspace", "workspace_id", "created_at"),
        Index("idx_vapi_calls_agent", "agent_id", "created_at"),
        Index("idx_vapi_calls_outcome", "outcome"),
    )
