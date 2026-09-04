from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    """LLM model configuration."""
    provider: str = Field(default="openai", description="Model provider (openai, anthropic, etc)")
    name: str = Field(default="gpt-4o", description="Model name")
    temperature: float = Field(default=0.3, ge=0, le=2)


class VoiceConfig(BaseModel):
    """Voice generation configuration."""
    provider: str = Field(default="elevenlabs", description="Voice provider")
    voice_id: str = Field(default="21m00Tcm4TlvDq8ikWAM", description="Voice ID")
    stability: float = Field(default=0.5, ge=0, le=1)
    similarity_boost: float = Field(default=0.75, ge=0, le=1)
    speed: float = Field(default=1.0, ge=0.5, le=2)


class TranscriberConfig(BaseModel):
    """Speech-to-text configuration."""
    provider: str = Field(default="deepgram", description="Transcriber provider")
    language: Optional[str] = None


class VapiAssistantConfig(BaseModel):
    """Configuration for creating/updating a Vapi assistant."""
    name: str = Field(description="Assistant name")
    system_prompt: Optional[str] = None
    model: ModelConfig
    voice: VoiceConfig
    first_message: str = Field(description="First message the assistant sends")
    transcriber: TranscriberConfig
    tools: List[dict] = Field(default_factory=list)
    silence_timeout_seconds: int = Field(default=30, ge=5, le=300)
    max_duration_seconds: int = Field(default=1800, ge=60, le=3600)
    background_sound: str = Field(default="off", pattern="^(off|office|cafe)$")
    transfer_phone_number: Optional[str] = None


class AgentVoiceConfigResponse(BaseModel):
    """Voice configuration response for an agent."""
    agent_id: str
    vapi_assistant_id: Optional[str] = None
    vapi_phone_number_id: Optional[str] = None
    phone_number_e164: Optional[str] = None
    voice_provider: str = "elevenlabs"
    voice_id: str
    stability: float
    similarity_boost: float
    speed: float
    filler_injection_enabled: bool = True
    model_provider: str = "openai"
    model_name: str
    temperature: float
    first_message: Optional[str] = None
    system_prompt: Optional[str] = None
    silence_timeout_seconds: int
    max_duration_seconds: int
    background_sound: str
    transfer_phone_number: Optional[str] = None
    business_hours_json: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
