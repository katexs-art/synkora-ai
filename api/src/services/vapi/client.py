"""Vapi API client."""
import os
from typing import Any

import httpx

VAPI_BASE_URL = "https://api.vapi.ai"
VAPI_API_KEY = os.getenv("VAPI_API_KEY", "")


class VapiClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or VAPI_API_KEY
        if not self.api_key:
            raise RuntimeError("VAPI_API_KEY not configured")
        self.client = httpx.AsyncClient(
            base_url=VAPI_BASE_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30.0,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    async def create_assistant(self, payload: dict[str, Any]) -> dict[str, Any]:
        r = await self.client.post("/assistant", json=payload)
        r.raise_for_status()
        return r.json()

    async def update_assistant(self, assistant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        r = await self.client.patch(f"/assistant/{assistant_id}", json=payload)
        r.raise_for_status()
        return r.json()

    async def delete_assistant(self, assistant_id: str) -> None:
        r = await self.client.delete(f"/assistant/{assistant_id}")
        r.raise_for_status()

    async def get_assistant(self, assistant_id: str) -> dict[str, Any]:
        r = await self.client.get(f"/assistant/{assistant_id}")
        r.raise_for_status()
        return r.json()

    async def buy_phone_number(self, area_code: str) -> dict[str, Any]:
        r = await self.client.post("/phone-number", json={"areaCode": area_code})
        r.raise_for_status()
        return r.json()

    async def get_phone_numbers(self) -> list[dict[str, Any]]:
        r = await self.client.get("/phone-number")
        r.raise_for_status()
        d = r.json(); return d.get("data", []) if isinstance(d, dict) else d

    async def delete_phone_number(self, phone_id: str) -> None:
        r = await self.client.delete(f"/phone-number/{phone_id}")
        r.raise_for_status()

    async def get_calls(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        r = await self.client.get("/call", params={"limit": limit, "offset": offset})
        r.raise_for_status()
        d = r.json(); return d.get("data", []) if isinstance(d, dict) else d

    async def get_call(self, call_id: str) -> dict[str, Any]:
        r = await self.client.get(f"/call/{call_id}")
        r.raise_for_status()
        return r.json()

    async def create_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        r = await self.client.post("/call", json=payload)
        try:
            r.raise_for_status()
        except Exception as e:
            body = r.text if r else "no response"
            print(f"[VapiClient] create_call 400. Payload: {payload}. Response: {body}")
            raise RuntimeError(f"Vapi 400: {body}") from e
        return r.json()


def get_vapi_client(api_key: str | None = None) -> VapiClient:
    return VapiClient(api_key=api_key)
