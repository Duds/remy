"""
Ollama local LLM client — fallback when Anthropic is unavailable.
Ported from my-agent/core/adapters_local.py with streaming support.
"""

import json
import logging
from typing import AsyncIterator

import httpx

from ..config import settings
from ..models import TokenUsage

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model = model or settings.ollama_fallback_model
        self.base_url = base_url or settings.ollama_base_url
        self.timeout = settings.ollama_timeout

    async def is_available(self) -> bool:
        """Check if Ollama is reachable (2s timeout)."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def stream_chat(self, messages: list[dict], usage_out: TokenUsage | None = None) -> AsyncIterator[str]:
        """Stream tokens from Ollama for the configured model using structured chat history."""
        url = f"{self.base_url}/api/chat"
        # Map Anthropic 'assistant' role to Ollama 'assistant' role
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    buffer = ""
                    async for chunk in response.aiter_text():
                        buffer += chunk
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                                if "message" in data:
                                    content = data["message"].get("content", "")
                                    if content:
                                        yield content
                                if data.get("done"):
                                    return
                            except json.JSONDecodeError:
                                continue
        except httpx.ConnectError:
            yield "[LOCAL] Could not connect to Ollama. Is `ollama serve` running?"
        except httpx.TimeoutException:
            yield f"[LOCAL] Ollama timed out loading {self.model}."
        except httpx.HTTPStatusError as e:
            yield f"[LOCAL] Ollama error: {e.response.status_code}"
        except Exception as e:
            yield f"[LOCAL] Unexpected error: {type(e).__name__}: {e}"
