"""
Katexs product endpoints (MVP): auto-build, stats, embed.
Sits on top of the core agent engine. Added 2026-09-04.
"""
import html
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
