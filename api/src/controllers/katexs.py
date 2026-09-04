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

