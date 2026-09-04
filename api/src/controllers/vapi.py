"""Vapi routes."""
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_async_db
from src.middleware.auth_middleware import get_current_account
from src.models import Account
from src.services.vapi.client import get_vapi_client
from src.services.vapi.webhooks import handle_call_end, verify_vapi_signature

router = APIRouter(tags=["Vapi"])


@router.post("/assistants")
async def create_vapi_assistant(
    config: dict,
    db: AsyncSession = Depends(get_async_db),
    account: Account = Depends(get_current_account),
):
    client = get_vapi_client()
    
    # Build proper Vapi payload from config
    payload = {
        "name": config.get("name", "Untitled Agent"),
        "model": {
            "provider": config.get("model", {}).get("provider", "openai"),
            "model": config.get("model", {}).get("model", "gpt-4o"),
            "temperature": config.get("model", {}).get("temperature", 0.3),
        },
        "voice": {
            "provider": "11labs",
            "voiceId": config.get("voice", {}).get("voiceId", "21m00Tcm4TlvDq8ikWAM"),
        },
        "firstMessage": config.get("firstMessage", "Hello, how can I help you?"),
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-2",
        },
    }
    
    assistant = await client.create_assistant(payload)

    # Persist vapi_assistant_id in agent_voice_configs table
    agent_id = config.get("agent_id")
    if agent_id:
        from sqlalchemy import text
        # Get tenant_id from the agent row
        result = await db.execute(
            text("SELECT tenant_id FROM agents WHERE id = :agent_id"),
            {"agent_id": agent_id}
        )
        row = result.fetchone()
        tenant_id = str(row[0]) if row else str(account.id)
        
        try:
            await db.execute(
                text("""
                    INSERT INTO agent_voice_configs (agent_id, tenant_id, vapi_assistant_id, voice_provider, voice_id, model_provider, model_name, created_at, updated_at)
                    VALUES (:agent_id, :tenant_id, :vapi_assistant_id, 'elevenlabs', '21m00Tcm4TlvDq8ikWAM', 'openai', 'gpt-4o', NOW(), NOW())
                    ON CONFLICT (agent_id) DO UPDATE SET
                        vapi_assistant_id = EXCLUDED.vapi_assistant_id,
                        updated_at = NOW()
                """),
                {
                    "agent_id": agent_id,
                    "tenant_id": tenant_id,
                    "vapi_assistant_id": assistant["id"]
                }
            )
            await db.commit()
        except Exception as e:
            await db.rollback()
            await db.execute(
                text("UPDATE agent_voice_configs SET vapi_assistant_id = :vapi_id, updated_at = NOW() WHERE agent_id = :agent_id"),
                {"vapi_id": assistant["id"], "agent_id": agent_id}
            )
            await db.commit()
    
    return {"success": True, "assistant": assistant, "agent_id": agent_id}


@router.patch("/assistants/{assistant_id}")
async def update_vapi_assistant(
    assistant_id: str,
    config: dict,
    db: AsyncSession = Depends(get_async_db),
    account: Account = Depends(get_current_account),
):
    client = get_vapi_client()
    assistant = await client.update_assistant(assistant_id, config)
    return {"success": True, "assistant": assistant}


@router.delete("/assistants/{assistant_id}")
async def delete_vapi_assistant(
    assistant_id: str,
    db: AsyncSession = Depends(get_async_db),
    account: Account = Depends(get_current_account),
):
    client = get_vapi_client()
    await client.delete_assistant(assistant_id)
    return {"success": True}


@router.post("/phone-numbers")
async def buy_phone_number(
    area_code: str,
    db: AsyncSession = Depends(get_async_db),
    account: Account = Depends(get_current_account),
):
    client = get_vapi_client()
    number = await client.buy_phone_number(area_code)
    return {"success": True, "number": number}


@router.get("/phone-numbers")
async def list_phone_numbers(
    db: AsyncSession = Depends(get_async_db),
    account: Account = Depends(get_current_account),
):
    client = get_vapi_client()
    numbers = await client.get_phone_numbers()
    return {"success": True, "numbers": numbers}


@router.get("/calls")
async def list_calls(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_async_db),
    account: Account = Depends(get_current_account),
):
    client = get_vapi_client()
    calls = await client.get_calls(limit=limit, offset=offset)
    return {"success": True, "calls": calls}


@router.post("/webhooks")
async def webhook_handler(
    request: Request,
    x_vapi_signature: str | None = Header(None),
    db: AsyncSession = Depends(get_async_db),
):
    payload = await request.body()
    body = await request.json()

    if not verify_vapi_signature(payload, x_vapi_signature or ""):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    event_type = body.get("message", {}).get("type")
    if event_type == "end-of-call-report":
        await handle_call_end(body, db)

    return {"success": True}


# ==================================================================
# VOICE CONFIG (Items 4.3 + 4.4)
# ==================================================================

@router.get("/agents/{agent_id}/voice-config")
async def get_voice_config(
    agent_id: str,
    db: AsyncSession = Depends(get_async_db),
    account: Account = Depends(get_current_account),
):
    """Load saved voice configuration for an agent."""
    from sqlalchemy import text
    result = await db.execute(
        text("SELECT * FROM agent_voice_configs WHERE agent_id = :agent_id"),
        {"agent_id": agent_id}
    )
    row = result.mappings().fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Voice config not found")
    return {
        "success": True,
        "config": {
            "agent_id": row["agent_id"],
            "vapi_assistant_id": row["vapi_assistant_id"],
            "voice": {
                "provider": row["voice_provider"],
                "voiceId": row["voice_id"],
                "stability": row["stability"],
                "similarityBoost": row["similarity_boost"],
                "speed": row["speed"],
                "fillerInjection": row["filler_injection_enabled"],
            },
            "model": {
                "provider": row["model_provider"],
                "model": row["model_name"],
                "temperature": row["temperature"],
            },
            "firstMessage": row["first_message"],
            "systemPrompt": row["system_prompt"],
            "silenceTimeoutSeconds": row["silence_timeout_seconds"],
            "maxDurationSeconds": row["max_duration_seconds"],
            "backgroundSound": row["background_sound"],
            "transferPhoneNumber": row["transfer_phone_number"],
        }
    }


@router.patch("/agents/{agent_id}/voice-config")
async def update_voice_config(
    agent_id: str,
    config: dict,
    db: AsyncSession = Depends(get_async_db),
    account: Account = Depends(get_current_account),
):
    """Update voice config in DB and sync to Vapi if assistant exists."""
    from sqlalchemy import text
    from src.services.vapi.client import get_vapi_client
    
    # Extract fields from payload
    voice = config.get("voice", {})
    model = config.get("model", {})
    first_message = config.get("firstMessage", "Hello, how can I help you?")
    system_prompt = config.get("systemPrompt", "")
    silence_timeout = config.get("silenceTimeoutSeconds", 30)
    max_duration = config.get("maxDurationSeconds", 1800)
    background_sound = config.get("backgroundSound", "off")
    transfer_number = config.get("transferPhoneNumber")
    
    # Update DB
    await db.execute(
        text("""
            UPDATE agent_voice_configs SET
                voice_provider = :voice_provider,
                voice_id = :voice_id,
                stability = :stability,
                similarity_boost = :similarity_boost,
                speed = :speed,
                filler_injection_enabled = :filler_injection,
                model_provider = :model_provider,
                model_name = :model_name,
                temperature = :temperature,
                first_message = :first_message,
                system_prompt = :system_prompt,
                silence_timeout_seconds = :silence_timeout,
                max_duration_seconds = :max_duration,
                background_sound = :background_sound,
                transfer_phone_number = :transfer_number,
                updated_at = NOW()
            WHERE agent_id = :agent_id
        """),
        {
            "agent_id": agent_id,
            "voice_provider": voice.get("provider", "elevenlabs"),
            "voice_id": voice.get("voiceId", "21m00Tcm4TlvDq8ikWAM"),
            "stability": voice.get("stability", 0.5),
            "similarity_boost": voice.get("similarityBoost", 0.75),
            "speed": voice.get("speed", 1.0),
            "filler_injection": voice.get("fillerInjection", True),
            "model_provider": model.get("provider", "openai"),
            "model_name": model.get("model", "gpt-4o"),
            "temperature": model.get("temperature", 0.3),
            "first_message": first_message,
            "system_prompt": system_prompt,
            "silence_timeout": silence_timeout,
            "max_duration": max_duration,
            "background_sound": background_sound,
            "transfer_number": transfer_number,
        }
    )
    await db.commit()
    
    # Sync to Vapi if assistant exists
    result = await db.execute(
        text("SELECT vapi_assistant_id FROM agent_voice_configs WHERE agent_id = :agent_id"),
        {"agent_id": agent_id}
    )
    row = result.fetchone()
    vapi_assistant_id = row[0] if row else None
    
    if vapi_assistant_id:
        from src.services.vapi.client import VapiClient
        client = VapiClient()
        async with client:
            vapi_payload = {
                "name": config.get("name", "Untitled Agent"),
                "model": {
                    "provider": model.get("provider", "openai"),
                    "model": model.get("model", "gpt-4o"),
                    "temperature": model.get("temperature", 0.3),
                },
                "voice": {
                    "provider": "11labs",
                    "voiceId": voice.get("voiceId", "21m00Tcm4TlvDq8ikWAM"),
                },
                "firstMessage": first_message,
                "transcriber": {
                    "provider": "deepgram",
                    "model": "nova-2",
                },
                "silenceTimeoutSeconds": silence_timeout,
                "maxDurationSeconds": max_duration,
                "backgroundSound": background_sound,
            }
            if system_prompt:
                vapi_payload["model"]["systemPrompt"] = system_prompt
            if transfer_number:
                vapi_payload["forwardingPhoneNumber"] = transfer_number
            
            await client.update_assistant(vapi_assistant_id, vapi_payload)
    
    return {"success": True, "agent_id": agent_id, "vapi_synced": bool(vapi_assistant_id)}


# ==================================================================
# TEST CALL (Item 4.6)
# ==================================================================

@router.post("/agents/{agent_id}/test-call")
async def test_call(
    agent_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_async_db),
    account: Account = Depends(get_current_account),
):
    """Place a test outbound call via Vapi."""
    from sqlalchemy import text
    from src.services.vapi.client import VapiClient
    
    result = await db.execute(
        text("SELECT vapi_assistant_id, vapi_phone_number_id, phone_number_e164 FROM agent_voice_configs WHERE agent_id = :agent_id"),
        {"agent_id": agent_id}
    )
    row = result.fetchone()
    if not row or not row[0]:
        raise HTTPException(status_code=400, detail="Agent has no Vapi assistant. Create one first.")
    
    vapi_assistant_id, phone_id, phone_e164 = row[0], row[1], row[2]
    customer_number = payload.get("customer_number")
    if not customer_number:
        raise HTTPException(status_code=400, detail="customer_number is required")
    
    vapi_payload = {
        "assistantId": vapi_assistant_id,
        "customer": {"number": customer_number}
    }
    if phone_id:
        vapi_payload["phoneNumberId"] = phone_id
    
    client = VapiClient()
    try:
        async with client:
            call = await client.create_call(vapi_payload)
    except Exception as e:
        import traceback
        print(f"[TestCall] Vapi error: {e}")
        print(f"[TestCall] Payload: {vapi_payload}")
        raise HTTPException(status_code=502, detail=f"Vapi error: {str(e)}")

    return {
        "success": True,
        "call_id": call.get("id"),
        "status": call.get("status", "queued"),
        "customer_number": customer_number,
        "from_number": phone_e164 or phone_id
    }


# ==================================================================
# DEPLOY (Item 4.5)
# ==================================================================

@router.post("/agents/{agent_id}/deploy")
async def deploy_agent(
    agent_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_async_db),
    account: Account = Depends(get_current_account),
):
    """Link a phone number to an agent's Vapi assistant."""
    from sqlalchemy import text
    from src.services.vapi.client import VapiClient
    import os
    
    phone_number_id = payload.get("phone_number_id")
    if not phone_number_id:
        raise HTTPException(status_code=400, detail="phone_number_id is required")
    
    # Get agent's vapi_assistant_id
    result = await db.execute(
        text("SELECT vapi_assistant_id FROM agent_voice_configs WHERE agent_id = :agent_id"),
        {"agent_id": agent_id}
    )
    row = result.fetchone()
    if not row or not row[0]:
        raise HTTPException(status_code=400, detail="Agent has no Vapi assistant. Create one first.")
    
    vapi_assistant_id = row[0]
    
    # Assign in Vapi
    vapi_key = os.getenv("VAPI_API_KEY")
    import httpx
    async with httpx.AsyncClient() as client:
        r = await client.patch(
            f"https://api.vapi.ai/phone-number/{phone_number_id}",
            headers={"Authorization": f"Bearer {vapi_key}"},
            json={"assistantId": vapi_assistant_id}
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Vapi error: {r.text}")
        phone_data = r.json()
    
    # Update DB
    await db.execute(
        text("UPDATE agent_voice_configs SET vapi_phone_number_id = :phone_id, phone_number_e164 = :e164, updated_at = NOW() WHERE agent_id = :agent_id"),
        {"phone_id": phone_number_id, "e164": phone_data.get("number", ""), "agent_id": agent_id}
    )
    await db.commit()
    
    return {
        "success": True,
        "agent_id": agent_id,
        "phone_number": phone_data.get("number"),
        "phone_number_id": phone_number_id,
        "vapi_assistant_id": vapi_assistant_id
    }
