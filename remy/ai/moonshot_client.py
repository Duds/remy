"""
Moonshot AI client for Remy.
"""

import logging
from typing import AsyncIterator

import httpx
from ..config import settings

logger = logging.getLogger(__name__)


class MoonshotClient:
    """Client for interacting with the Moonshot AI API."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = (api_key or settings.moonshot_api_key).strip()
        self._base_url = "https://api.moonshot.ai/v1"

    async def stream_chat(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3, # Lower temperature for reasoning/planning
    ) -> AsyncIterator[str]:
        """Stream a chat completion from Moonshot."""
        if not self._api_key:
            logger.warning("Moonshot API key not configured")
            yield "⚠️ _Moonshot API key not configured._"
            return

        model = model or settings.moonshot_model_v1
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                async with client.stream(
                    "POST", f"{self._base_url}/chat/completions", json=payload, headers=headers
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        logger.error("Moonshot API error (%d): %s", response.status_code, error_text)
                        yield f"⚠️ _Moonshot API error ({response.status_code})_"
                        return

                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                break
                            
                            import json
                            try:
                                data = json.loads(data_str)
                                if delta := data["choices"][0].get("delta", {}).get("content"):
                                    yield delta
                            except (json.JSONDecodeError, KeyError, IndexError) as e:
                                logger.debug("Error parsing Moonshot stream chunk: %s", e)
            except Exception as e:
                logger.error("Moonshot stream failed: %s", e)
                yield f"⚠️ _Moonshot connection failed: {e}_"

    async def is_available(self) -> bool:
        """Check if Moonshot API is available."""
        if not self._api_key:
            return False
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                headers = {"Authorization": f"Bearer {self._api_key}"}
                response = await client.get(f"{self._base_url}/models", headers=headers)
                if response.status_code != 200:
                    logger.error("Moonshot availability check failed with status %d: %s", response.status_code, response.text)
                    return False
                return True
            except Exception as e:
                logger.error("Moonshot availability check failed: %s", e)
                return False
