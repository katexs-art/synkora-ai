"""Vapi webhook handler."""
import hashlib
import hmac
import os
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

VAPI_WEBHOOK_SECRET = os.getenv("VAPI_WEBHOOK_SECRET", "")


def verify_vapi_signature(payload: bytes, signature: str, secret: str | None = None) -> bool:
    secret = secret or VAPI_WEBHOOK_SECRET
    if not secret:
        return True  # dev only
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def handle_call_end(payload: dict[str, Any], db: AsyncSession) -> None:
    """Process Vapi end-of-call-report webhook. Parse and persist to vapi_calls."""
    from sqlalchemy import text
    
    # Vapi sends: { "message": { "type": "...", "call": { ... } } }
    # Handle both full body and message-only
    message = payload.get("message", payload)
    call = message.get("call", {})
    
    call_id = call.get("id")
    if not call_id:
        print("[VapiWebhook] No call ID in payload")
        return
    
    # Extract all fields
    vapi_assistant_id = call.get("assistantId")
    phone_number = call.get("phoneNumber", "")
    direction = call.get("type", "").replace("PhoneCall", "").lower() or "inbound"
    status = call.get("status", "unknown")
    started_at = call.get("startedAt")
    ended_at = call.get("endedAt")
    duration = call.get("duration")
    cost = call.get("cost")  # dollars
    transcript = call.get("transcript", "")
    recording_url = call.get("recordingUrl", "")
    ended_reason = call.get("endedReason", "")
    
    customer = call.get("customer", {}) or {}
    customer_phone = customer.get("number", "")
    customer_name = customer.get("name", "")
    
    analysis = call.get("analysis", {}) or {}
    summary = analysis.get("summary", "") if isinstance(analysis, dict) else ""
    
    # Determine outcome
    outcome = None
    if isinstance(analysis, dict):
        success = analysis.get("successEvaluation")
        if success == "true":
            outcome = "resolved"
        elif success == "false":
            outcome = "failed"
    if not outcome and ended_reason == "forwarded":
        outcome = "transferred"
    
    # Containment: true if AI handled it without human transfer
    containment = ended_reason != "forwarded" and outcome != "transferred"
    
    # Look up agent_id + tenant_id from vapi_assistant_id
    result = await db.execute(
        text("SELECT agent_id, tenant_id FROM agent_voice_configs WHERE vapi_assistant_id = :vapi_id"),
        {"vapi_id": vapi_assistant_id}
    )
    row = result.fetchone()
    if not row:
        print(f"[VapiWebhook] No agent found for assistant {vapi_assistant_id}")
        agent_id = None
        tenant_id = None
    else:
        agent_id = row[0]
        tenant_id = row[1]
    
    # Convert cost to cents
    cost_cents = int(float(cost) * 100) if cost else 0
    
    # Upsert into vapi_calls
    await db.execute(
        text("""
            INSERT INTO vapi_calls (
                workspace_id, agent_id, vapi_call_id, vapi_assistant_id,
                phone_number, direction, status, started_at, ended_at,
                duration_seconds, cost_cents, transcript, recording_url,
                customer_phone, customer_name, outcome, containment, summary
            ) VALUES (
                :workspace_id, :agent_id, :vapi_call_id, :vapi_assistant_id,
                :phone_number, :direction, :status, :started_at, :ended_at,
                :duration_seconds, :cost_cents, :transcript, :recording_url,
                :customer_phone, :customer_name, :outcome, :containment, :summary
            )
            ON CONFLICT (vapi_call_id) DO UPDATE SET
                status = EXCLUDED.status,
                ended_at = EXCLUDED.ended_at,
                duration_seconds = EXCLUDED.duration_seconds,
                cost_cents = EXCLUDED.cost_cents,
                transcript = EXCLUDED.transcript,
                recording_url = EXCLUDED.recording_url,
                outcome = EXCLUDED.outcome,
                containment = EXCLUDED.containment,
                summary = EXCLUDED.summary,
                updated_at = NOW()
        """),
        {
            "workspace_id": tenant_id,
            "agent_id": agent_id,
            "vapi_call_id": call_id,
            "vapi_assistant_id": vapi_assistant_id,
            "phone_number": phone_number,
            "direction": direction,
            "status": status,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": duration,
            "cost_cents": cost_cents,
            "transcript": transcript,
            "recording_url": recording_url,
            "customer_phone": customer_phone,
            "customer_name": customer_name,
            "outcome": outcome,
            "containment": containment,
            "summary": summary,
        }
    )
    await db.commit()
    
    print(f"[VapiWebhook] Call {call_id} persisted. Agent: {agent_id}, Duration: {duration}s, Cost: ${cost}, Outcome: {outcome}")
