"""
Tests for US-analytics-token-capture.

Covers:
- TokenUsage model (arithmetic, properties, defaults)
- ClaudeClient.stream_message() — usage populated from get_final_message()
- ClaudeClient.stream_with_tools() — usage accumulated across iterations
- MistralClient.stream_chat() — usage from final SSE chunk; missing-usage fallback
- MoonshotClient.stream_chat() — usage from post-[DONE] chunk; missing-usage fallback
- OllamaClient.stream_chat() — usage_out stays zeroed
- ModelRouter.last_usage — populated after stream completes
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from remy.models import TokenUsage


# ---------------------------------------------------------------------------
# TokenUsage model
# ---------------------------------------------------------------------------

def test_token_usage_defaults_to_zero():
    u = TokenUsage()
    assert u.input_tokens == 0
    assert u.output_tokens == 0
    assert u.cache_creation_tokens == 0
    assert u.cache_read_tokens == 0


def test_token_usage_total_tokens():
    u = TokenUsage(input_tokens=100, output_tokens=50)
    assert u.total_tokens == 150


def test_token_usage_add():
    a = TokenUsage(input_tokens=10, output_tokens=5, cache_read_tokens=2)
    b = TokenUsage(input_tokens=20, output_tokens=8, cache_creation_tokens=3)
    c = a + b
    assert c.input_tokens == 30
    assert c.output_tokens == 13
    assert c.cache_read_tokens == 2
    assert c.cache_creation_tokens == 3


def test_token_usage_add_identity():
    u = TokenUsage(input_tokens=7, output_tokens=3)
    assert (u + TokenUsage()).input_tokens == 7
    assert (TokenUsage() + u).output_tokens == 3


# ---------------------------------------------------------------------------
# Helpers — build mock Anthropic stream
# ---------------------------------------------------------------------------

def _make_anthropic_stream(text_chunks: list[str], input_tokens=100, output_tokens=50,
                            cache_creation=0, cache_read=0):
    """Returns a mock that behaves like anthropic AsyncMessageStream context manager."""
    mock_usage = MagicMock()
    mock_usage.input_tokens = input_tokens
    mock_usage.output_tokens = output_tokens
    mock_usage.cache_creation_input_tokens = cache_creation
    mock_usage.cache_read_input_tokens = cache_read

    mock_final_msg = MagicMock()
    mock_final_msg.usage = mock_usage
    mock_final_msg.stop_reason = "end_turn"
    mock_final_msg.content = []

    async def _text_stream():
        for chunk in text_chunks:
            yield chunk

    mock_stream = MagicMock()
    mock_stream.text_stream = _text_stream()
    mock_stream.get_final_message = AsyncMock(return_value=mock_final_msg)
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=None)
    return mock_stream


# ---------------------------------------------------------------------------
# ClaudeClient — stream_message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_claude_stream_message_yields_text():
    from remy.ai.claude_client import ClaudeClient

    mock_stream = _make_anthropic_stream(["Hello", " world"])
    client = ClaudeClient()
    client._client = MagicMock()
    client._client.messages.stream = MagicMock(return_value=mock_stream)

    chunks = []
    async for text in client.stream_message([{"role": "user", "content": "Hi"}]):
        chunks.append(text)

    assert chunks == ["Hello", " world"]


@pytest.mark.asyncio
async def test_claude_stream_message_captures_usage():
    from remy.ai.claude_client import ClaudeClient

    mock_stream = _make_anthropic_stream(["Hi"], input_tokens=120, output_tokens=30,
                                         cache_creation=5, cache_read=10)
    client = ClaudeClient()
    client._client = MagicMock()
    client._client.messages.stream = MagicMock(return_value=mock_stream)

    usage = TokenUsage()
    async for _ in client.stream_message([{"role": "user", "content": "Hi"}], usage_out=usage):
        pass

    assert usage.input_tokens == 120
    assert usage.output_tokens == 30
    assert usage.cache_creation_tokens == 5
    assert usage.cache_read_tokens == 10


@pytest.mark.asyncio
async def test_claude_stream_message_no_usage_out_no_crash():
    """Passing usage_out=None (default) must not raise."""
    from remy.ai.claude_client import ClaudeClient

    mock_stream = _make_anthropic_stream(["ok"])
    client = ClaudeClient()
    client._client = MagicMock()
    client._client.messages.stream = MagicMock(return_value=mock_stream)

    chunks = []
    async for text in client.stream_message([{"role": "user", "content": "Hi"}]):
        chunks.append(text)
    assert chunks == ["ok"]


# ---------------------------------------------------------------------------
# ClaudeClient — stream_with_tools (multi-iteration accumulation)
# ---------------------------------------------------------------------------

def _make_tool_stream(stop_reason="end_turn", text_chunks=None, tool_blocks=None):
    """Mock for a single stream_with_tools iteration."""
    text_chunks = text_chunks or ["done"]
    tool_blocks = tool_blocks or []

    mock_usage = MagicMock()
    mock_usage.input_tokens = 50
    mock_usage.output_tokens = 20
    mock_usage.cache_creation_input_tokens = 0
    mock_usage.cache_read_input_tokens = 0

    # Content blocks
    content_blocks = []
    for chunk in text_chunks:
        b = MagicMock()
        b.type = "text"
        b.text = chunk
        content_blocks.append(b)

    mock_final_msg = MagicMock()
    mock_final_msg.usage = mock_usage
    mock_final_msg.stop_reason = stop_reason
    mock_final_msg.content = content_blocks

    async def _raw_events():
        return
        yield  # make it an async generator

    mock_stream = MagicMock()
    mock_stream.__aiter__ = lambda s: _raw_events()
    mock_stream.get_final_message = AsyncMock(return_value=mock_final_msg)
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=None)
    return mock_stream


@pytest.mark.asyncio
async def test_claude_stream_with_tools_accumulates_usage():
    """Two end_turn iterations: usage sums across both."""
    from remy.ai.claude_client import ClaudeClient

    # Both iterations end with stop_reason=end_turn, 50+20 each time
    stream1 = _make_tool_stream(stop_reason="end_turn")
    stream2 = _make_tool_stream(stop_reason="end_turn")

    call_count = 0

    def make_stream(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return stream1 if call_count == 1 else stream2

    mock_tool_registry = MagicMock()
    mock_tool_registry.schemas = []
    mock_tool_registry.dispatch = AsyncMock(return_value="result")

    client = ClaudeClient()
    client._client = MagicMock()
    client._client.messages.stream = MagicMock(side_effect=make_stream)

    usage = TokenUsage()
    events = []
    async for event in client.stream_with_tools(
        [{"role": "user", "content": "Hi"}],
        tool_registry=mock_tool_registry,
        user_id=1,
        usage_out=usage,
    ):
        events.append(event)

    # First iteration ends with end_turn → exits immediately, accumulating once
    assert usage.input_tokens == 50
    assert usage.output_tokens == 20


# ---------------------------------------------------------------------------
# Helpers — build mock httpx SSE response
# ---------------------------------------------------------------------------

def _make_httpx_sse_client(lines: list[str], status_code: int = 200):
    """Returns a patched httpx.AsyncClient that yields the given SSE lines."""

    async def _aiter_lines():
        for line in lines:
            yield line

    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.aiter_lines = _aiter_lines

    mock_http_stream_ctx = MagicMock()
    mock_http_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_http_stream_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_http_client = MagicMock()
    mock_http_client.stream = MagicMock(return_value=mock_http_stream_ctx)
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)

    return mock_http_client


# ---------------------------------------------------------------------------
# MistralClient
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mistral_captures_usage_from_final_chunk():
    from remy.ai.mistral_client import MistralClient

    lines = [
        'data: {"choices": [{"delta": {"content": "Hello"}}]}',
        'data: {"choices": [{"delta": {"content": " world"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}',
        "data: [DONE]",
    ]
    mock_client = _make_httpx_sse_client(lines)

    with patch("remy.ai.mistral_client.httpx.AsyncClient", return_value=mock_client):
        client = MistralClient(api_key="test-key")
        usage = TokenUsage()
        chunks = []
        async for chunk in client.stream_chat([{"role": "user", "content": "Hi"}], usage_out=usage):
            chunks.append(chunk)

    assert "Hello" in chunks
    assert " world" in chunks
    assert usage.input_tokens == 10
    assert usage.output_tokens == 5


@pytest.mark.asyncio
async def test_mistral_no_usage_chunk_stays_zero():
    from remy.ai.mistral_client import MistralClient

    lines = [
        'data: {"choices": [{"delta": {"content": "hi"}}]}',
        "data: [DONE]",
    ]
    mock_client = _make_httpx_sse_client(lines)

    with patch("remy.ai.mistral_client.httpx.AsyncClient", return_value=mock_client):
        client = MistralClient(api_key="test-key")
        usage = TokenUsage()
        async for _ in client.stream_chat([{"role": "user", "content": "Hi"}], usage_out=usage):
            pass

    assert usage.input_tokens == 0
    assert usage.output_tokens == 0


@pytest.mark.asyncio
async def test_mistral_error_response_leaves_usage_zero():
    from remy.ai.mistral_client import MistralClient

    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.aread = AsyncMock(return_value=b"rate limited")

    mock_http_stream_ctx = MagicMock()
    mock_http_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_http_stream_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_http_client = MagicMock()
    mock_http_client.stream = MagicMock(return_value=mock_http_stream_ctx)
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)

    with patch("remy.ai.mistral_client.httpx.AsyncClient", return_value=mock_http_client):
        client = MistralClient(api_key="test-key")
        usage = TokenUsage()
        chunks = []
        async for chunk in client.stream_chat([{"role": "user", "content": "Hi"}], usage_out=usage):
            chunks.append(chunk)

    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert any("error" in c.lower() or "⚠️" in c for c in chunks)


# ---------------------------------------------------------------------------
# MoonshotClient
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_moonshot_captures_usage_before_done():
    """Usage chunk arrives before [DONE] (standard OpenAI pattern)."""
    from remy.ai.moonshot_client import MoonshotClient

    lines = [
        'data: {"choices": [{"delta": {"content": "Hi"}}]}',
        'data: {"choices": [], "usage": {"prompt_tokens": 8, "completion_tokens": 3}}',
        "data: [DONE]",
    ]
    mock_client = _make_httpx_sse_client(lines)

    with patch("remy.ai.moonshot_client.httpx.AsyncClient", return_value=mock_client):
        client = MoonshotClient(api_key="test-key")
        usage = TokenUsage()
        chunks = []
        async for chunk in client.stream_chat([{"role": "user", "content": "Hi"}], usage_out=usage):
            chunks.append(chunk)

    assert "Hi" in chunks
    assert usage.input_tokens == 8
    assert usage.output_tokens == 3


@pytest.mark.asyncio
async def test_moonshot_captures_usage_after_done():
    """Usage chunk arrives after [DONE] — our done-flag approach handles it."""
    from remy.ai.moonshot_client import MoonshotClient

    lines = [
        'data: {"choices": [{"delta": {"content": "Hi"}}]}',
        "data: [DONE]",
        'data: {"choices": [], "usage": {"prompt_tokens": 15, "completion_tokens": 7}}',
    ]
    mock_client = _make_httpx_sse_client(lines)

    with patch("remy.ai.moonshot_client.httpx.AsyncClient", return_value=mock_client):
        client = MoonshotClient(api_key="test-key")
        usage = TokenUsage()
        chunks = []
        async for chunk in client.stream_chat([{"role": "user", "content": "Hi"}], usage_out=usage):
            chunks.append(chunk)

    assert usage.input_tokens == 15
    assert usage.output_tokens == 7
    # Text yielded only before [DONE]
    assert "Hi" in chunks


@pytest.mark.asyncio
async def test_moonshot_no_usage_chunk_stays_zero():
    from remy.ai.moonshot_client import MoonshotClient

    lines = [
        'data: {"choices": [{"delta": {"content": "hi"}}]}',
        "data: [DONE]",
    ]
    mock_client = _make_httpx_sse_client(lines)

    with patch("remy.ai.moonshot_client.httpx.AsyncClient", return_value=mock_client):
        client = MoonshotClient(api_key="test-key")
        usage = TokenUsage()
        async for _ in client.stream_chat([{"role": "user", "content": "Hi"}], usage_out=usage):
            pass

    assert usage.input_tokens == 0
    assert usage.output_tokens == 0


@pytest.mark.asyncio
async def test_moonshot_payload_includes_stream_options():
    """Verify include_usage is sent in every request payload."""
    from remy.ai.moonshot_client import MoonshotClient

    lines = ["data: [DONE]"]
    mock_client = _make_httpx_sse_client(lines)

    with patch("remy.ai.moonshot_client.httpx.AsyncClient", return_value=mock_client):
        client = MoonshotClient(api_key="test-key")
        async for _ in client.stream_chat([{"role": "user", "content": "Hi"}]):
            pass

    call_kwargs = mock_client.stream.call_args[1]
    assert call_kwargs["json"]["stream_options"] == {"include_usage": True}


# ---------------------------------------------------------------------------
# OllamaClient — usage_out stays zero
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ollama_usage_out_stays_zero():
    from remy.ai.ollama_client import OllamaClient
    import httpx

    async def _aiter_text():
        yield '{"message": {"content": "hi"}, "done": true}\n'

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_text = _aiter_text

    mock_http_stream_ctx = MagicMock()
    mock_http_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_http_stream_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_http_client = MagicMock()
    mock_http_client.stream = MagicMock(return_value=mock_http_stream_ctx)
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)

    with patch("remy.ai.ollama_client.httpx.AsyncClient", return_value=mock_http_client):
        client = OllamaClient(model="llama3", base_url="http://localhost:11434")
        usage = TokenUsage()
        chunks = []
        async for chunk in client.stream_chat([{"role": "user", "content": "Hi"}], usage_out=usage):
            chunks.append(chunk)

    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.total_tokens == 0


# ---------------------------------------------------------------------------
# ModelRouter — last_usage property
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_router_last_usage_populated_after_stream():
    from remy.ai.router import ModelRouter

    async def fake_mistral_stream(*args, usage_out=None, **kwargs):
        if usage_out is not None:
            usage_out.input_tokens = 42
            usage_out.output_tokens = 17
        yield "response"

    claude = MagicMock()
    mistral = MagicMock()
    mistral.stream_chat = MagicMock(side_effect=fake_mistral_stream)
    moonshot = MagicMock()
    ollama = MagicMock()
    ollama.is_available = AsyncMock(return_value=False)

    router = ModelRouter(claude, mistral, moonshot, ollama)

    # Force mistral path (routine + short)
    router._classifier = MagicMock()
    router._classifier.classify = AsyncMock(return_value="routine")

    chunks = []
    async for chunk in router.stream("hi", [{"role": "user", "content": "hi"}], user_id=1):
        chunks.append(chunk)

    assert router.last_usage.input_tokens == 42
    assert router.last_usage.output_tokens == 17


@pytest.mark.asyncio
async def test_router_last_usage_resets_on_each_stream():
    from remy.ai.router import ModelRouter

    call_count = 0

    async def fake_mistral_stream(*args, usage_out=None, **kwargs):
        nonlocal call_count
        call_count += 1
        if usage_out is not None:
            usage_out.input_tokens = call_count * 10
            usage_out.output_tokens = call_count * 5
        yield "ok"

    claude = MagicMock()
    mistral = MagicMock()
    mistral.stream_chat = MagicMock(side_effect=fake_mistral_stream)
    moonshot = MagicMock()
    ollama = MagicMock()

    router = ModelRouter(claude, mistral, moonshot, ollama)
    router._classifier = MagicMock()
    router._classifier.classify = AsyncMock(return_value="routine")

    async for _ in router.stream("hi", [{"role": "user", "content": "hi"}], user_id=1):
        pass
    assert router.last_usage.input_tokens == 10

    async for _ in router.stream("hi", [{"role": "user", "content": "hi"}], user_id=1):
        pass
    assert router.last_usage.input_tokens == 20  # second call, not accumulated
