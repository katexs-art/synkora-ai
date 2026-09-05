"""
Katexs product endpoints (MVP): auto-build, stats, embed.
Sits on top of the core agent engine. Added 2026-09-04.
"""
import html
import json
import logging
import os
import re
import uuid
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_async_db
from src.middleware.auth_middleware import get_current_account, get_current_tenant_id
from src.models import Account
from src.models.agent import Agent
from src.models.agent_llm_config import AgentLLMConfig
from src.services.agents.security import encrypt_value
import secrets
from src.models.agent_widget import AgentWidget
from src.controllers.widgets import generate_api_key
from src.services.phone.phone_config_service import PhoneConfigService
from src.config.settings import settings as app_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["katexs"])

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
WIDGET_URL = os.environ.get("KATEXS_WIDGET_URL", "https://app.katexs.tech/widget.js")
APP_URL = os.environ.get("KATEXS_APP_URL", "https://app.katexs.tech")


class DescribeBuildRequest(BaseModel):
    description: str = Field(..., min_length=10, max_length=3000)
    lane: str | None = Field(default=None)


def _extract_lane(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(voice|phone calls?|callers?|inbound calls?|telephone|after-hours|after hours)\b", t):
        return "voice"
    return "chat"


class AutoBuildRequest(BaseModel):
    business_name: str = Field(..., min_length=2, max_length=120)
    industry: str = Field(default="General", max_length=80)
    website: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    lane: str = Field(default="chat", pattern="^(chat|voice)$")


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9-]", "-", name.lower())
    return re.sub(r"-+", "-", base).strip("-") or "agent"


async def _scrape_website(url: str) -> str:
    """Lightweight fetch + text extraction. Never throws."""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (KatexsBot)"})
            resp.raise_for_status()
        raw = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", resp.text, flags=re.I)
        raw = re.sub(r"<[^>]+>", " ", raw)
        text = html.unescape(re.sub(r"\s+", " ", raw)).strip()
        return text[:2500]
    except Exception as exc:  # noqa: BLE001 - scrape is best-effort
        logger.info("Website scrape failed (%s): %s", url, exc)
        return ""


def _build_system_prompt(business_name: str, industry: str, description: str, site_text: str, lane: str) -> str:
    facts = []
    if industry and industry.lower() != "general":
        facts.append(f"Industry: {industry}")
    if description:
        facts.append(f"What they do: {description}")
    if site_text:
        facts.append(f"Website info: {site_text[:1800]}")
    facts_block = "\n".join(facts) if facts else "Industry: General services business."
    medium = "phone calls" if lane == "voice" else "website chat"
    return f"""You are {business_name}'s AI assistant — a warm, professional, and highly capable front-line agent for their business.

### ABOUT THE BUSINESS
{facts_block}

### YOUR JOB
You handle {medium} for {business_name}. You help customers with questions, explain services, capture leads, and book or route requests — always moving the conversation toward a clear next step (appointment, callback, or message to the owner).

### RULES
1. Answer ONLY from the business facts above. Never invent services, prices, hours, or policies.
2. If you do not know something, say so honestly and offer to have the owner reach out: "I'll make sure the owner gets back to you on that — what's the best number or email?"
3. Keep replies warm, brief, and natural (1–3 sentences in chat, conversational for voice). No corporate stiffness.
4. Always collect a name and contact detail before ending a conversation where the customer needs follow-up.
5. Never claim to be human. You are {business_name}'s AI assistant, built by Katexs.
6. Stay in character as a member of {business_name}'s team at all times."""


async def _create_engine_agent(
    db: AsyncSession,
    tenant_id,
    account: Account,
    name: str,
    description: str,
    system_prompt: str,
    lane: str,
) -> Agent:
    exists = await db.execute(
        select(Agent).filter(Agent.tenant_id == tenant_id, Agent.agent_name == name)
    )
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"An agent named '{name}' already exists")

    api_key_raw = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key_raw:
        raise HTTPException(status_code=500, detail="Server LLM key not configured (ANTHROPIC_API_KEY)")

    llm_config = {
        "provider": "anthropic",
        "model": DEFAULT_MODEL,
        "api_key": encrypt_value(api_key_raw),
        "temperature": 0.6,
        "max_tokens": 2048,
        "additional_params": {},
    }
    is_voice = lane == "voice"
    agent = Agent(
        tenant_id=tenant_id,
        created_by=account.id,
        agent_name=name,
        agent_type="llm",
        description=description,
        system_prompt=system_prompt,
        llm_config=llm_config,
        agent_metadata={"katexs_lane": lane, "built_by": "katexs-autobuild"},
        status="ACTIVE",
        suggestion_prompts=[],
        voice_enabled=is_voice,
        voice_config={"provider": "vapi"} if is_voice else None,
        phone_config={"provider": "vapi", "enabled": False} if is_voice else None,
    )
    db.add(agent)
    agent.slug = _slugify(name)
    await db.flush()

    llm_entry = AgentLLMConfig(
        tenant_id=tenant_id,
        agent_id=agent.id,
        name=f"Primary {DEFAULT_MODEL}",
        provider="anthropic",
        model_name=DEFAULT_MODEL,
        api_key=encrypt_value(api_key_raw),
        temperature=0.6,
        max_tokens=2048,
        is_default=True,
        display_order=0,
        enabled=True,
    )
    db.add(llm_entry)
    await db.flush()
    return agent


async def _ensure_widget(db, agent):
    """Return existing widget for agent, or create one. plain_key only when newly created."""
    res = await db.execute(select(AgentWidget).where(AgentWidget.agent_id == agent.id).limit(1))
    w = res.scalar_one_or_none()
    if w:
        return w, None
    plain_key, enc_key, key_prefix = generate_api_key()
    w = AgentWidget(
        agent_id=agent.id,
        tenant_id=agent.tenant_id,
        widget_name="Website Widget",
        api_key=enc_key,
        key_prefix=key_prefix,
        allowed_domains=None,
        theme_config={},
        rate_limit=None,
        is_active=True,
        identity_secret=encrypt_value(secrets.token_urlsafe(32)),
        identity_verification_required=False,
        enable_agent_routing=False,
    )
    db.add(w)
    await db.flush()
    return w, plain_key


def _embed_snippet(slug: str, agent_id, plain_key: str) -> str:
    return (
        "<!-- Katexs AI Chat Widget -->\n"
        f'<script src="{WIDGET_URL}" async></script>\n'
        "<script>\n"
        "  window.addEventListener('load', function () {\n"
        "    SynkoraWidget.init({\n"
        f"      widgetId: '{slug}',\n"
        f"      apiKey: '{plain_key}',\n"
        "      apiUrl: 'https://api.katexs.tech/api/v1'\n"
        "    });\n"
        "  });\n"
        "</script>\n"
        "<!-- End Katexs AI Chat Widget -->"
    )


@router.post("/auto-build")
async def auto_build(
    req: AutoBuildRequest,
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_async_db),
):
    name = f"{req.business_name.strip()} AI Agent"
    site_text = ""
    if req.website:
        site_text = await _scrape_website(req.website.strip())
    description = (req.description or "").strip()
    prompt = _build_system_prompt(req.business_name.strip(), req.industry.strip(), description, site_text, req.lane)
    try:
        agent = await _create_engine_agent(db, tenant_id, account, name, description or prompt[:200], prompt, req.lane)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.exception("auto-build failed")
        raise HTTPException(status_code=500, detail=f"Agent build failed: {exc}") from exc

    # Widget for website embed
    try:
        _, plain_key = await _ensure_widget(db, agent)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Widget creation failed: %s", exc)
        plain_key = ""

    voice_status = None
    if req.lane == "voice":
        vcfg = {
            "enabled": False,
            "provider": "vapi",
            "greeting": f"Hi, thanks for calling {req.business_name.strip()}! How can I help you today?",
            "end_call_message": "Thanks for calling — have a great day!",
            "voice_provider": "elevenlabs",
            "voice_id": "EXAVITQu4vr4xnSDxMaL",
            "language": "en",
            "max_duration_seconds": 300,
            "record_calls": False,
        }
        key = await PhoneConfigService.get_vapi_api_key(tenant_id, db)
        base = getattr(app_settings, "app_base_url", "") or ""
        if key and base:
            try:
                aid = await PhoneConfigService.register_webhook_with_vapi(agent.slug, key, base)
                if aid:
                    vcfg["enabled"] = True
                    vcfg["vapi_assistant_id"] = aid
            except Exception:  # noqa: BLE001
                logger.exception("voice auto-provision failed")
        agent.phone_config = vcfg
        voice_status = {
            "provisioned": bool(vcfg.get("vapi_assistant_id")),
            "vapi_assistant_id": vcfg.get("vapi_assistant_id"),
            "enabled": vcfg["enabled"],
        }

    await db.commit()
    await db.refresh(agent)

    return {
        "success": True,
        "agent": {
            "id": str(agent.id),
            "agent_name": agent.agent_name,
            "slug": agent.slug,
            "lane": req.lane,
            "status": agent.status,
            "created_at": agent.created_at.isoformat() if agent.created_at else None,
        },
        "preview_url": f"{APP_URL}/chat?agent_name={agent.slug}",
        "voice": voice_status,
        "embed": _embed_snippet(agent.slug, agent.id, plain_key) if plain_key else None,
    }


@router.get("/stats")
async def katexs_stats(
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_async_db),
):
    total = (await db.execute(select(func.count(Agent.id)).filter(Agent.tenant_id == tenant_id))).scalar() or 0
    active = (await db.execute(select(func.count(Agent.id)).filter(Agent.tenant_id == tenant_id, Agent.status == "ACTIVE"))).scalar() or 0
    voice = (await db.execute(select(func.count(Agent.id)).filter(Agent.tenant_id == tenant_id, Agent.voice_enabled.is_(True)))).scalar() or 0
    recent_res = await db.execute(
        select(Agent).filter(Agent.tenant_id == tenant_id).order_by(Agent.created_at.desc()).limit(8)
    )
    recent = [
        {
            "id": str(a.id),
            "agent_name": a.agent_name,
            "slug": a.slug,
            "lane": (a.agent_metadata or {}).get("katexs_lane", "voice" if a.voice_enabled else "chat"),
            "status": a.status,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in recent_res.scalars()
    ]
    return {"success": True, "total_agents": total, "active_agents": active, "voice_agents": voice, "recent_agents": recent}


@router.get("/agents/{agent_id}/embed")
async def agent_embed(
    agent_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_async_db),
):
    agent = (
        await db.execute(select(Agent).filter(Agent.id == agent_id, Agent.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    widget, plain_key = await _ensure_widget(db, agent)
    if not plain_key:
        return {
            "success": True,
            "agent_name": agent.agent_name,
            "slug": agent.slug,
            "preview_url": f"{APP_URL}/chat?agent_name={agent.slug}",
            "widget_id": str(widget.id),
            "embed": None,
            "note": "A website widget already exists for this agent (its key was shown when created). Regenerate support is on the roadmap.",
        }
    await db.commit()
    return {
        "success": True,
        "agent_name": agent.agent_name,
        "slug": agent.slug,
        "preview_url": f"{APP_URL}/chat?agent_name={agent.slug}",
        "widget_id": str(widget.id),
        "embed": _embed_snippet(agent.slug, agent.id, plain_key),
    }


@router.post("/describe-build")
async def describe_build(
    req: DescribeBuildRequest,
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    account: Account = Depends(get_current_account),
    db: AsyncSession = Depends(get_async_db),
):
    """Sim.ai-style: user describes the agent they want -> Claude plans it -> we assemble it."""
    lane = req.lane if req.lane and req.lane in ("chat", "voice") else _extract_lane(req.description)
    api_key_raw = os.environ.get("ANTHROPIC_API_KEY")
    plan = None
    if api_key_raw:
        try:
            system = (
                "You plan AI agents for small businesses. Given a user's plain-English request, return STRICT JSON: "
                "{\"business_name\": string (best name for the business/agent, e.g. 'Sunshine Dental'), "
                "\"industry\": string, "
                "\"services\": string (short summary of what the agent should handle), "
                "\"agent_name\": string (short name for the agent, e.g. 'Sunshine Dental AI Assistant'), "
                "\"greeting\": string (one-line greeting for chat/phone), "
                "\"tools\": [string] (only from: booking, sms_reminders, crm_logging, faq_answers, qualify_leads), "
                "\"voice_notes\": string (1 sentence voice behavior note, empty if not voice)}"
            )
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key_raw,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": DEFAULT_MODEL,
                        "max_tokens": 1200,
                        "system": system,
                        "messages": [{"role": "user", "content": req.description}],
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = "".join(
                        b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
                    )
                    m = re.search(r"\{[\s\S]*\}", text)
                    if m:
                        plan = json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            logger.exception("describe-build planning failed")

    # Fallback plan if Claude failed
    if not plan:
        biz = re.sub(r"\s+", " ", req.description)[:80]
        plan = {
            "business_name": biz,
            "industry": "General",
            "services": req.description,
            "agent_name": None,
            "greeting": "Hi there! How can I help you today?",
            "tools": [],
            "voice_notes": "",
        }

    business_name = (plan.get("business_name") or "").strip() or "My Business"
    industry = (plan.get("industry") or "").strip() or "General"
    services = (plan.get("services") or req.description).strip()
    greeting = (plan.get("greeting") or "Hi there! How can I help you today?").strip()
    tools = plan.get("tools") or []
    voice_note = (plan.get("voice_notes") or "").strip()

    # Build a rich system prompt
    prompt_parts = [
        f"You are {business_name}'s AI assistant — warm, professional, capable.",
        f"### ABOUT THE BUSINESS\nIndustry: {industry}\nWhat they handle: {services}",
    ]
    if tools:
        tool_lines = []
        for t in tools:
            tlow = t.lower()
            if "booking" in tlow:
                tool_lines.append("- Booking: collect name, phone, service and preferred time; confirm the slot before finishing.")
            elif "sms" in tlow:
                tool_lines.append("- SMS reminders: offer to send a confirmation/reminder text after booking.")
            elif "crm" in tlow:
                tool_lines.append("- CRM: capture lead details (name, phone, need) and note them for follow-up.")
            elif "faq" in tlow:
                tool_lines.append("- FAQ: answer common questions from knowledge; never invent prices/policies.")
            elif "qualif" in tlow:
                tool_lines.append("- Lead qualification: ask what they need, urgency, and best contact info.")
        if tool_lines:
            prompt_parts.append("### CAPABILITIES\n" + "\n".join(tool_lines))
    if lane == "voice" and voice_note:
        prompt_parts.append("### VOICE\nKeep replies short and natural for phone. " + voice_note)
    prompt_parts.append(
        "### RULES\n1. Only state facts you know; otherwise offer to have the owner follow up (capture contact). "
        "2. Always collect name + phone/email when follow-up or booking is needed. "
        "3. Never claim to be human. Stay in character as a member of the team. "
        "4. Be brief, warm and natural."
    )
    system_prompt = "\n\n".join(prompt_parts)

    agent_name = (plan.get("agent_name") or "").strip() or f"{business_name} AI Agent"
    try:
        agent = await _create_engine_agent(db, tenant_id, account, agent_name, services[:400], system_prompt, lane)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.exception("describe-build create failed")
        raise HTTPException(status_code=500, detail=f"Agent build failed: {exc}") from exc

    # voice provisioning
    voice_status = None
    if lane == "voice":
        vcfg = {
            "enabled": False, "provider": "vapi",
            "greeting": greeting,
            "end_call_message": "Thanks for calling — have a great day!",
            "voice_provider": "elevenlabs", "voice_id": "EXAVITQu4vr4xnSDxMaL",
            "language": "en", "max_duration_seconds": 300, "record_calls": False,
        }
        key = await PhoneConfigService.get_vapi_api_key(tenant_id, db)
        base = getattr(app_settings, "app_base_url", "") or ""
        if key and base:
            try:
                aid = await PhoneConfigService.register_webhook_with_vapi(agent.slug, key, base)
                if aid:
                    vcfg["enabled"] = True
                    vcfg["vapi_assistant_id"] = aid
            except Exception:  # noqa: BLE001
                logger.exception("voice provisioning failed")
        agent.phone_config = vcfg
        voice_status = {"provisioned": bool(vcfg.get("vapi_assistant_id")), "vapi_assistant_id": vcfg.get("vapi_assistant_id"), "enabled": vcfg["enabled"]}

    # widget
    try:
        _, plain_key = await _ensure_widget(db, agent)
    except Exception as exc:  # noqa: BLE001
        logger.warning("widget creation failed: %s", exc)
        plain_key = ""

    await db.commit()
    await db.refresh(agent)

    return {
        "success": True,
        "plan": {"business_name": business_name, "industry": industry, "tools": tools, "lane": lane},
        "agent": {
            "id": str(agent.id), "agent_name": agent.agent_name, "slug": agent.slug,
            "lane": lane, "status": agent.status,
        },
        "preview_url": f"{APP_URL}/chat?agent_name={agent.slug}",
        "voice": voice_status,
        "embed": _embed_snippet(agent.slug, agent.id, plain_key) if plain_key else None,
    }


@router.get("/voice-overview")
async def voice_overview(
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_async_db),
):
    """Voice section data: voice agents, phone numbers, recent calls."""
    from src.models.phone_call import PhoneCall
    from src.models.phone_number import PhoneNumber

    # voice agents (voice_enabled or phone_config set)
    agents_res = await db.execute(
        select(Agent).filter(Agent.tenant_id == tenant_id).order_by(Agent.created_at.desc()).limit(50)
    )
    agents = []
    for a in agents_res.scalars():
        pc = a.phone_config or {}
        is_voice = bool(a.voice_enabled) or pc.get("provider") == "vapi" or (a.agent_metadata or {}).get("katexs_lane") == "voice"
        if not is_voice:
            continue
        agents.append({
            "id": str(a.id),
            "agent_name": a.agent_name,
            "slug": a.slug,
            "status": a.status,
            "greeting": pc.get("greeting") or "",
            "enabled": bool(pc.get("enabled")),
            "vapi_assistant_id": pc.get("vapi_assistant_id") or "",
            "phone_provisioned": bool(pc.get("vapi_assistant_id")),
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        })

    numbers_res = await db.execute(
        select(PhoneNumber).filter(PhoneNumber.tenant_id == tenant_id).order_by(PhoneNumber.created_at.desc()).limit(20)
    )
    numbers = [
        {
            "id": str(n.id),
            "phone_number": n.phone_number,
            "agent_id": str(n.agent_id) if n.agent_id else None,
            "provider": n.provider,
            "is_active": n.is_active,
        }
        for n in numbers_res.scalars()
    ]

    calls_res = await db.execute(
        select(PhoneCall)
        .filter(PhoneCall.tenant_id == tenant_id)
        .order_by(PhoneCall.started_at.desc())
        .limit(15)
    )
    calls = []
    for c in calls_res.scalars():
        agent_name = ""
        if c.agent_id:
            ares = await db.execute(select(Agent).filter(Agent.id == c.agent_id))
            aa = ares.scalar_one_or_none()
            if aa:
                agent_name = aa.agent_name
        calls.append({
            "id": str(c.id),
            "caller_number": c.caller_number or "",
            "agent_name": agent_name,
            "status": c.status.value if hasattr(c.status, "value") else str(c.status),
            "duration_seconds": c.duration_seconds,
            "started_at": c.started_at.isoformat() if c.started_at else None,
            "recording_url": c.recording_url or "",
        })

    return {
        "success": True,
        "agents": agents,
        "numbers": numbers,
        "calls": calls,
    }


# ---------------------------------------------------------------------------
# Voice Agent Studio — full Vapi assistant configuration surface
# (voice / model / transcriber / call behavior / analysis), synced live
# to the Vapi assistant AND persisted to the engine agent.
# ---------------------------------------------------------------------------

_VOICE_CACHE: dict = {"ts": 0.0, "voices": []}
_VOICE_CACHE_TTL = 900  # 15 min

VOICE_PROVIDERS = [
    {"value": "11labs", "label": "ElevenLabs"},
    {"value": "openai", "label": "OpenAI"},
    {"value": "deepgram", "label": "Deepgram"},
    {"value": "azure", "label": "Azure"},
    {"value": "playht", "label": "PlayHT"},
    {"value": "rime", "label": "Rime"},
    {"value": "cartesia", "label": "Cartesia"},
]

MODEL_CATALOG = {
    "anthropic": [
        "claude-opus-4-6",
        "claude-sonnet-4-5-20250929",
        "claude-3-7-sonnet-20250219",
        "claude-3-5-haiku-20241022",
    ],
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"],
}

TRANSCRIBER_CATALOG = {
    "deepgram": ["nova-2", "nova-3"],
    "openai": ["whisper-1"],
}

SPOKEN_LANGUAGES = [
    {"value": "en", "label": "English"},
    {"value": "es", "label": "Spanish"},
    {"value": "fr", "label": "French"},
    {"value": "de", "label": "German"},
    {"value": "pt", "label": "Portuguese"},
    {"value": "it", "label": "Italian"},
    {"value": "nl", "label": "Dutch"},
    {"value": "ja", "label": "Japanese"},
    {"value": "zh", "label": "Chinese"},
]


class VoiceAssistantVoice(BaseModel):
    provider: str | None = None
    voice_id: str | None = None
    speed: float | None = Field(default=None, ge=0.5, le=2.0)
    stability: float | None = Field(default=None, ge=0.0, le=1.0)
    similarity_boost: float | None = Field(default=None, ge=0.0, le=1.0)
    language: str | None = None


class VoiceAssistantTranscriber(BaseModel):
    provider: str | None = None
    model: str | None = None
    language: str | None = None


class VoiceAssistantModel(BaseModel):
    provider: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=64, le=8192)
    api_key: str | None = Field(default=None, min_length=8, max_length=400)  # BYO LLM key (never echoed)


class VoiceAssistantAdvanced(BaseModel):
    silence_timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    max_duration_seconds: int | None = Field(default=None, ge=30, le=7200)
    recording_enabled: bool | None = None
    background_denoising_enabled: bool | None = None
    num_words_to_interrupt_assistant: int | None = Field(default=None, ge=1, le=50)
    interruption_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    end_call_phrases: list[str] | None = None


class VoiceAssistantAnalysis(BaseModel):
    summary_enabled: bool | None = None
    structured_data_enabled: bool | None = None


class VoiceAssistantUpdate(BaseModel):
    first_message: str | None = None
    end_call_message: str | None = None
    language: str | None = None
    system_prompt: str | None = None
    voice: VoiceAssistantVoice | None = None
    transcriber: VoiceAssistantTranscriber | None = None
    model: VoiceAssistantModel | None = None
    advanced: VoiceAssistantAdvanced | None = None
    analysis: VoiceAssistantAnalysis | None = None


async def _katexs_vapi_key(db: AsyncSession, tenant_id) -> str:
    key = None
    try:
        key = await PhoneConfigService.get_vapi_api_key(tenant_id, db)
    except Exception:
        key = None
    if not key:
        key = os.environ.get("VAPI_API_KEY")
    if not key:
        raise HTTPException(status_code=400, detail="Vapi credential not configured for this tenant")
    return key


async def _resolve_agent(db, tenant_id, agent_key: str) -> Agent:
    agent = None
    try:
        agent = await db.get(Agent, uuid.UUID(agent_key))
    except Exception:
        agent = None
    if agent is None or str(agent.tenant_id) != str(tenant_id):
        res = await db.execute(
            select(Agent).filter(Agent.tenant_id == tenant_id, Agent.slug == agent_key)
        )
        agent = res.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def _fetch_vapi_assistant_raw(db, tenant_id, assistant_id: str) -> dict:
    key = await _katexs_vapi_key(db, tenant_id)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"https://api.vapi.ai/assistant/{assistant_id}",
            headers={"Authorization": f"Bearer {key}"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Vapi assistant fetch failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json()


async def _voice_catalog(db, tenant_id) -> list[dict]:
    import time as _time
    now = _time.time()
    if _VOICE_CACHE["voices"] and (now - _VOICE_CACHE["ts"]) < _VOICE_CACHE_TTL:
        return _VOICE_CACHE["voices"]
    voices: list[dict] = []
    try:
        key = await _katexs_vapi_key(db, tenant_id)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.vapi.ai/voice?limit=300",
                headers={"Authorization": f"Bearer {key}"},
            )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                voices = [
                    {
                        "voiceId": v.get("voiceId", ""),
                        "name": v.get("name") or v.get("voiceId", ""),
                        "provider": v.get("provider", ""),
                        "language": v.get("language", ""),
                    }
                    for v in data
                    if v.get("voiceId")
                ]
    except Exception:
        voices = []
    if not voices:
        # curated fallback catalog (covers providers even before users connect keys)
        voices = [
            # ElevenLabs
            {"voiceId": "EXAVITQu4vr4xnSDxMaL", "name": "Rachel", "provider": "11labs", "language": "en"},
            {"voiceId": "21m00Tcm4TlvDq8ikWAM", "name": "Bella", "provider": "11labs", "language": "en"},
            {"voiceId": "onwK4e9ZLuTAKqWW03F9", "name": "Domi", "provider": "11labs", "language": "en"},
            {"voiceId": "TX3LPaxmHKxFdv7VOQHJ", "name": "Elli", "provider": "11labs", "language": "en"},
            {"voiceId": "VR6AewLTigWG4xSOukaG", "name": "Arnold", "provider": "11labs", "language": "en"},
            {"voiceId": "pNInz6obpgDQGcFmaJgB", "name": "Adam", "provider": "11labs", "language": "en"},
            {"voiceId": "yoZ06aMxZJJ28mfd3POQ", "name": "Sam", "provider": "11labs", "language": "en"},
            {"voiceId": "jBpfuIE2acCO8z3wKNLl", "name": "Gigi", "provider": "11labs", "language": "en"},
            {"voiceId": "cgSgspJ2msm6clMCkdW9", "name": "Jessica", "provider": "11labs", "language": "en"},
            {"voiceId": "iP95p4xoKVk53GoZ742B", "name": "Chris", "provider": "11labs", "language": "en"},
            {"voiceId": "nPczCjzmy2RZSJ5utkTA", "name": "Daniel", "provider": "11labs", "language": "en"},
            {"voiceId": "XUeQJ7N7CJ0V4VfHn5nN", "name": "Grace", "provider": "11labs", "language": "en"},
            {"voiceId": "8rHn0g2vWzQ5aXkL9mBp", "name": "Sarah", "provider": "11labs", "language": "en"},
            {"voiceId": "pqHfZKP75CvOlQylNhV4", "name": "Bill", "provider": "11labs", "language": "en"},
            {"voiceId": "flq6f7yk4E4fJM5XTYuZ", "name": "Michael", "provider": "11labs", "language": "en"},
            {"voiceId": "zrHiDhphv9ZnV2qEzyhW", "name": "Judy", "provider": "11labs", "language": "en"},
            {"voiceId": "K6aYv9s8Yc7O6mWxQz3D", "name": "Alex", "provider": "11labs", "language": "en"},
            # OpenAI
            {"voiceId": "alloy", "name": "Alloy (Neutral)", "provider": "openai", "language": "en"},
            {"voiceId": "echo", "name": "Echo (Male)", "provider": "openai", "language": "en"},
            {"voiceId": "fable", "name": "Fable (British)", "provider": "openai", "language": "en"},
            {"voiceId": "onyx", "name": "Onyx (Deep Male)", "provider": "openai", "language": "en"},
            {"voiceId": "nova", "name": "Nova (Female)", "provider": "openai", "language": "en"},
            {"voiceId": "shimmer", "name": "Shimmer (Soft Female)", "provider": "openai", "language": "en"},
            # Deepgram
            {"voiceId": "aura-asteria-en", "name": "Asteria (Female)", "provider": "deepgram", "language": "en"},
            {"voiceId": "aura-orion-en", "name": "Orion (Male)", "provider": "deepgram", "language": "en"},
            {"voiceId": "aura-luna-en", "name": "Luna (Female)", "provider": "deepgram", "language": "en"},
            {"voiceId": "aura-arcas-en", "name": "Arcas (Male)", "provider": "deepgram", "language": "en"},
        ]
    return voices


def _pick(d: dict, keys: list[str]) -> dict:
    return {k: d[k] for k in keys if k in d and d[k] is not None}


@router.get("/voice-assistant/{agent_key}")
async def get_voice_assistant(
    agent_key: str,
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_async_db),
):
    agent = await _resolve_agent(db, tenant_id, agent_key)
    pc = agent.phone_config or {}
    assistant_id = pc.get("vapi_assistant_id") or ""
    live: dict = {}
    if assistant_id:
        try:
            live = await _fetch_vapi_assistant_raw(db, tenant_id, assistant_id)
        except HTTPException:
            live = {}
    live_model = live.get("model") or {}
    live_voice = live.get("voice") or {}
    live_transcriber = live.get("transcriber") or {}
    live_analysis = live.get("analysisPlan") or {}
    live_artifact = live.get("artifactPlan") or {}
    summary_plan = live_analysis.get("summaryPlan") or {}
    structured_plan = live_analysis.get("structuredDataPlan") or {}

    # brain (engine default LLM config)
    brain_res = await db.execute(
        select(AgentLLMConfig).filter(
            AgentLLMConfig.agent_id == agent.id, AgentLLMConfig.is_default == True  # noqa: E712
        ).limit(1)
    )
    brain = brain_res.scalar_one_or_none()

    voices = await _voice_catalog(db, tenant_id)
    return {
        "success": True,
        "agent": {
            "id": str(agent.id),
            "name": agent.agent_name,
            "slug": agent.slug,
            "assistant_id": assistant_id,
            "provisioned": bool(assistant_id),
        },
        "brain": {
            "system_prompt": agent.system_prompt or "",
            "provider": brain.provider if brain else (agent.llm_config or {}).get("provider", "anthropic"),
            "model": brain.model_name if brain else (agent.llm_config or {}).get("model", DEFAULT_MODEL),
            "temperature": brain.temperature if brain else (agent.llm_config or {}).get("temperature", 0.6),
            "max_tokens": brain.max_tokens if brain else (agent.llm_config or {}).get("max_tokens", 2048),
            "uses_platform_key": bool(not (brain and getattr(brain, "uses_platform_key", True) is False) and not (agent.llm_config or {}).get("uses_platform_key") is False),
        },
        "call": {
            "first_message": pc.get("greeting") or live.get("firstMessage") or "",
            "end_call_message": pc.get("end_call_message") or "",
            "language": pc.get("language") or live_transcriber.get("language") or "en",
            "phone_enabled": bool(pc.get("enabled")),
        },
        "vapi": {
            "voice": _pick(live_voice, ["provider", "voiceId", "speed", "stability", "similarityBoost"]),
            "transcriber": _pick(live_transcriber, ["provider", "model", "language"]),
            "model": _pick(live_model, ["provider", "model", "temperature", "maxTokens"]),
            "firstMessage": live.get("firstMessage", ""),
            "silenceTimeoutSeconds": live.get("silenceTimeoutSeconds"),
            "maxDurationSeconds": live.get("maxDurationSeconds"),
            "recordingEnabled": live.get("recordingEnabled"),
            "backgroundDenoisingEnabled": live.get("backgroundDenoisingEnabled"),
            "numWordsToInterruptAssistant": live.get("numWordsToInterruptAssistant"),
            "interruptionThreshold": live.get("interruptionThreshold"),
            "endCallPhrases": live.get("endCallPhrases") or [],
            "analysis": {
                "summary_enabled": bool((summary_plan or {}).get("enabled")),
                "structured_data_enabled": bool((structured_plan or {}).get("enabled")),
                "transcript_enabled": bool((live_artifact or {}).get("recordingTranscript")),
            },
            "serverUrlSecretSet": bool(live.get("isServerUrlSecretSet")),
            "raw": live,
        },
        "catalog": {
            "voices": voices,
            "voice_providers": VOICE_PROVIDERS,
            "models": MODEL_CATALOG,
            "transcribers": TRANSCRIBER_CATALOG,
            "languages": SPOKEN_LANGUAGES,
        },
    }


@router.put("/voice-assistant/{agent_key}")
async def update_voice_assistant(
    agent_key: str,
    body: VoiceAssistantUpdate,
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_async_db),
):
    agent = await _resolve_agent(db, tenant_id, agent_key)
    pc = dict(agent.phone_config or {})
    assistant_id = pc.get("vapi_assistant_id") or ""
    if not assistant_id:
        raise HTTPException(status_code=400, detail="This agent has no Vapi assistant provisioned yet. Rebuild the voice agent or register one first.")

    live = await _fetch_vapi_assistant_raw(db, tenant_id, assistant_id)
    patch: dict = {}
    vapi_voice: dict = {}
    vapi_transcriber: dict = {}
    vapi_model: dict = {}

    if body.first_message is not None:
        patch["firstMessage"] = body.first_message
        pc["greeting"] = body.first_message
    if body.end_call_message is not None:
        pc["end_call_message"] = body.end_call_message
    if body.language is not None:
        pc["language"] = body.language
        vapi_transcriber["language"] = body.language

    if body.voice is not None:
        v = body.voice
        if v.provider is not None:
            vapi_voice["provider"] = v.provider
            pc["voice_provider"] = v.provider
        if v.voice_id is not None:
            vapi_voice["voiceId"] = v.voice_id
            pc["voice_id"] = v.voice_id
        if v.speed is not None:
            vapi_voice["speed"] = v.speed
        if v.stability is not None:
            vapi_voice["stability"] = v.stability
        if v.similarity_boost is not None:
            vapi_voice["similarityBoost"] = v.similarity_boost
        if v.language is not None:
            vapi_voice["language"] = v.language

    if body.transcriber is not None:
        t = body.transcriber
        if t.provider is not None:
            vapi_transcriber["provider"] = t.provider
        if t.model is not None:
            vapi_transcriber["model"] = t.model
        if t.language is not None:
            vapi_transcriber["language"] = t.language

    if vapi_voice:
        merged_voice = dict(live.get("voice") or {})
        merged_voice.update(vapi_voice)
        patch["voice"] = merged_voice
    if vapi_transcriber:
        merged_tr = dict(live.get("transcriber") or {})
        merged_tr.update(vapi_transcriber)
        patch["transcriber"] = merged_tr

    if body.model is not None:
        m = body.model
        merged_model = dict(live.get("model") or {})
        if m.provider is not None:
            merged_model["provider"] = m.provider
        if m.model is not None:
            merged_model["model"] = m.model
        if m.temperature is not None:
            merged_model["temperature"] = m.temperature
        if m.max_tokens is not None:
            merged_model["maxTokens"] = m.max_tokens
        # keep the assistant persona aligned with the engine brain prompt
        if body.system_prompt is not None:
            merged_model["messages"] = [{"role": "system", "content": body.system_prompt}]
        patch["model"] = merged_model

    if body.advanced is not None:
        adv = body.advanced
        if adv.silence_timeout_seconds is not None:
            patch["silenceTimeoutSeconds"] = adv.silence_timeout_seconds
        if adv.max_duration_seconds is not None:
            patch["maxDurationSeconds"] = adv.max_duration_seconds
            pc["max_duration_seconds"] = adv.max_duration_seconds
        if adv.recording_enabled is not None:
            patch["recordingEnabled"] = adv.recording_enabled
            pc["record_calls"] = adv.recording_enabled
        if adv.background_denoising_enabled is not None:
            patch["backgroundDenoisingEnabled"] = adv.background_denoising_enabled
        if adv.num_words_to_interrupt_assistant is not None:
            patch["numWordsToInterruptAssistant"] = adv.num_words_to_interrupt_assistant
        if adv.interruption_threshold is not None:
            patch["interruptionThreshold"] = adv.interruption_threshold
        if adv.end_call_phrases is not None:
            patch["endCallPhrases"] = adv.end_call_phrases

    if body.analysis is not None:
        ana = body.analysis
        ap = dict(live.get("analysisPlan") or {})
        if ana.summary_enabled is not None:
            sp = dict(ap.get("summaryPlan") or {})
            sp["enabled"] = ana.summary_enabled
            ap["summaryPlan"] = sp
        if ana.structured_data_enabled is not None:
            sdp = dict(ap.get("structuredDataPlan") or {})
            sdp["enabled"] = ana.structured_data_enabled
            ap["structuredDataPlan"] = sdp
        if ap:
            patch["analysisPlan"] = ap

    # Vapi PATCH (whitelist only — webhook/secret untouched)
    key = await _katexs_vapi_key(db, tenant_id)
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.patch(
            f"https://api.vapi.ai/assistant/{assistant_id}",
            headers={"Authorization": f"Bearer {key}"},
            json=patch,
        )
    if resp.status_code not in (200, 201, 202):
        raise HTTPException(status_code=502, detail=f"Vapi update failed ({resp.status_code}): {resp.text[:300]}")
    updated = resp.json()

    # ---- persist engine-side mirrors ----
    if body.system_prompt is not None:
        agent.system_prompt = body.system_prompt

    if body.model is not None and (body.model.model is not None or body.model.provider is not None):
        llm_res = await db.execute(
            select(AgentLLMConfig).filter(
                AgentLLMConfig.agent_id == agent.id, AgentLLMConfig.is_default == True  # noqa: E712
            ).limit(1)
        )
        llm = llm_res.scalar_one_or_none()
        if llm:
            if body.model.provider is not None:
                llm.provider = body.model.provider
            if body.model.model is not None:
                llm.model_name = body.model.model
                llm.name = f"Primary {body.model.model}"
            if body.model.temperature is not None:
                llm.temperature = body.model.temperature
            if body.model.max_tokens is not None:
                llm.max_tokens = body.model.max_tokens
            if body.model.api_key:
                llm.api_key = encrypt_value(body.model.api_key)
                llm.uses_platform_key = False
        lc = dict(agent.llm_config or {})
        if body.model.provider is not None:
            lc["provider"] = body.model.provider
        if body.model.model is not None:
            lc["model"] = body.model.model
        if body.model.temperature is not None:
            lc["temperature"] = body.model.temperature
        if body.model.max_tokens is not None:
            lc["max_tokens"] = body.model.max_tokens
        if body.model.api_key:
            lc["api_key"] = encrypt_value(body.model.api_key)
            lc["uses_platform_key"] = False
        agent.llm_config = lc

    pc.setdefault("provider", "vapi")
    agent.phone_config = pc
    agent.voice_enabled = True
    if agent.voice_config is None:
        agent.voice_config = {"provider": "vapi"}
    await db.commit()

    return {"success": True, "assistant_id": assistant_id, "updated": True, "message": "Voice assistant configuration synced to Vapi"}


# ---------------------------------------------------------------------------
# Voice previews, test calls, and minute billing (Katexs voice product)
# ---------------------------------------------------------------------------

VOICE_MINUTE_SELL_CENTS = 35  # sell price per voice minute (admin-tunable later)
_PREVIEW_DIR = "/tmp/katexs-voice-previews"


class TestCallRequest(BaseModel):
    customer_number: str = Field(..., min_length=5, max_length=25, pattern=r"^\+?[0-9]{5,20}$")


class VoiceTopupRequest(BaseModel):
    minutes: int = Field(..., ge=30, le=100000)


def _voice_preview_cache_path(provider: str, voice_id: str) -> str:
    import hashlib
    safe = hashlib.sha1(f"{provider}:{voice_id}".encode()).hexdigest()[:16]
    return f"{_PREVIEW_DIR}/{safe}.mp3"


@router.get("/voice-preview")
async def voice_preview(voice_id: str, provider: str = "11labs"):
    """Synthesize a short voice sample (MP3) for the voice picker."""
    from fastapi import Response as FastResponse
    import os as _os

    os.makedirs(_PREVIEW_DIR, exist_ok=True)
    cache = _voice_preview_cache_path(provider, voice_id)
    if _os.path.exists(cache) and (_os.path.getmtime(cache) > _os.path.getmtime(__file__) - 7 * 86400):
        return FastResponse(open(cache, "rb").read(), media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=604800"})

    sample_text = "Hi, I'm your AI voice agent from Katexs. How can I help you today?"
    audio = None

    if provider == "openai":
        key = _os.environ.get("OPENAI_API_KEY")
        if not key:
            raise HTTPException(status_code=503, detail="Voice previews for OpenAI need a server OpenAI key (not configured).")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": "tts-1", "voice": voice_id, "input": sample_text, "response_format": "mp3"},
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"OpenAI TTS failed: {resp.text[:200]}")
        audio = resp.content
    elif provider == "11labs":
        key = _os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            raise HTTPException(status_code=503, detail="ElevenLabs previews need the Katexs ElevenLabs API key (not configured yet).")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": key, "Content-Type": "application/json"},
                json={"text": sample_text, "model_id": "eleven_turbo_v2_5", "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}},
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"ElevenLabs TTS failed: {resp.text[:200]}")
        audio = resp.content
    else:
        raise HTTPException(status_code=501, detail=f"Preview synthesis not supported yet for provider '{provider}'. Pick ElevenLabs or OpenAI to hear samples.")

    with open(cache, "wb") as f:
        f.write(audio)
    return FastResponse(audio, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=604800"})


@router.post("/voice-assistant/{agent_key}/test-call")
async def voice_test_call(
    agent_key: str,
    body: TestCallRequest,
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_async_db),
):
    """Ring a phone from the agent's number so the user can test the live agent."""
    from src.models.phone_number import PhoneNumber

    agent = await _resolve_agent(db, tenant_id, agent_key)
    pc = agent.phone_config or {}
    assistant_id = pc.get("vapi_assistant_id") or ""
    if not assistant_id:
        raise HTTPException(status_code=400, detail="Agent has no voice assistant provisioned yet.")

    num_res = await db.execute(
        select(PhoneNumber).filter(PhoneNumber.agent_id == agent.id, PhoneNumber.is_active == True)  # noqa: E712
    )
    phone = num_res.scalars().first()
    provider_number_id = (phone.provider_number_id if phone else None) or ""
    if not provider_number_id:
        raise HTTPException(status_code=400, detail="Agent has no phone number attached. Add one in Phone settings first.")

    key = await _katexs_vapi_key(db, tenant_id)
    async with httpx.AsyncClient(timeout=25) as client:
        resp = await client.post(
            "https://api.vapi.ai/call",
            headers={"Authorization": f"Bearer {key}"},
            json={"assistantId": assistant_id, "phoneNumberId": provider_number_id, "customer": {"number": body.customer_number}},
        )
    if resp.status_code not in (200, 201, 202):
        raise HTTPException(status_code=502, detail=f"Test call failed ({resp.status_code}): {resp.text[:250]}")
    data = resp.json()
    return {"success": True, "call_id": data.get("id"), "status": data.get("status", "queued"), "calling": body.customer_number, "from": phone.phone_number if phone else ""}


@router.get("/voice-billing")
async def voice_billing(
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_async_db),
):
    """Minutes balance + spend for the tenant."""
    from sqlalchemy import text as sqltext

    row = (await db.execute(sqltext("SELECT total_credits, used_credits, available_credits FROM credit_balances WHERE tenant_id = :t"), {"t": str(tenant_id)})).fetchone()
    total = int(row[0]) if row else 0
    used = int(row[1]) if row else 0
    available = int(row[2]) if row else 0
    stripe_enabled = bool(os.environ.get("STRIPE_SECRET_KEY"))
    return {
        "success": True,
        "currency": "usd",
        "sell_price_per_min_cents": VOICE_MINUTE_SELL_CENTS,
        "minutes": {"total": total, "used": used, "available": available},
        "stripe_enabled": stripe_enabled,
        "packs": [
            {"minutes": 100, "price_cents": 3500},
            {"minutes": 500, "price_cents": 15750},
            {"minutes": 1000, "price_cents": 28000},
            {"minutes": 5000, "price_cents": 122500},
        ],
    }


@router.post("/voice-topup")
async def voice_topup(
    body: VoiceTopupRequest,
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_async_db),
):
    """Purchase voice minutes. Stripe checkout when configured; quote otherwise."""
    import secrets as _secrets
    from sqlalchemy import text as sqltext

    secret_key = os.environ.get("STRIPE_SECRET_KEY")
    amount_cents = body.minutes * VOICE_MINUTE_SELL_CENTS
    if not secret_key:
        return {
            "success": True,
            "checkout_url": None,
            "stripe_enabled": False,
            "message": "Payments are being enabled — quote below. Minutes activate the moment checkout goes live.",
            "quote": {"minutes": body.minutes, "amount_cents": amount_cents},
        }

    import uuid as _uuid
    topup_id = str(_uuid.uuid4())
    await db.execute(
        sqltext(
            "INSERT INTO credit_topups (id, tenant_id, credits, amount, status, payment_provider, created_at, updated_at) "
            "VALUES (:id, :t, :credits, :amount, 'pending', 'stripe', now(), now())"
        ),
        {"id": topup_id, "t": str(tenant_id), "credits": body.minutes, "amount": amount_cents / 100.0},
    )
    await db.commit()

    try:
        import stripe as stripe_lib
        stripe_lib.api_key = secret_key
        session = stripe_lib.checkout.Session.create(
            mode="payment",
            success_url=f"{APP_URL}/voice?purchase=success",
            cancel_url=f"{APP_URL}/voice?purchase=cancelled",
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"Katexs Voice Minutes — {body.minutes} min"},
                    "unit_amount": amount_cents,
                },
                "quantity": 1,
            }],
            metadata={"topup_id": topup_id, "tenant_id": str(tenant_id), "kind": "voice_minutes"},
            client_reference_id=str(tenant_id),
        )
        return {"success": True, "checkout_url": session.url, "stripe_enabled": True, "quote": {"minutes": body.minutes, "amount_cents": amount_cents}}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Checkout creation failed: {str(e)[:200]}")
