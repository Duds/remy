"""Tests for MoonshotClient (stream_chat, get_balance)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_balance_returns_none_when_no_api_key():
    """When API key is empty, get_balance returns None."""
    from remy.ai.moonshot_client import MoonshotClient

    client = MoonshotClient(api_key="")
    assert await client.get_balance() is None


@pytest.mark.asyncio
async def test_get_balance_returns_float_on_success():
    """When API returns balance, get_balance returns float."""
    from remy.ai.moonshot_client import MoonshotClient

    client = MoonshotClient(api_key="sk-test")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"balance": 12.5}

    with patch("remy.ai.moonshot_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await client.get_balance()

    assert result == 12.5


@pytest.mark.asyncio
async def test_get_balance_accepts_remain_balance_field():
    """API may return remain_balance instead of balance."""
    from remy.ai.moonshot_client import MoonshotClient

    client = MoonshotClient(api_key="sk-test")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"remain_balance": 3.0}

    with patch("remy.ai.moonshot_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await client.get_balance()

    assert result == 3.0


@pytest.mark.asyncio
async def test_get_balance_returns_none_on_http_error():
    """On non-200 status, get_balance returns None (no exception)."""
    from remy.ai.moonshot_client import MoonshotClient

    client = MoonshotClient(api_key="sk-test")
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"

    with patch("remy.ai.moonshot_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        result = await client.get_balance()

    assert result is None


@pytest.mark.asyncio
async def test_get_balance_returns_none_on_exception():
    """On network/parse error, get_balance returns None."""
    from remy.ai.moonshot_client import MoonshotClient

    client = MoonshotClient(api_key="sk-test")

    with patch("remy.ai.moonshot_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value.get = AsyncMock(
            side_effect=Exception("Connection error")
        )
        mock_client_cls.return_value = mock_client

        result = await client.get_balance()

    assert result is None
