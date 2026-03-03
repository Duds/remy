"""
Tests for Anthropic prompt caching implementation.
"""

from unittest.mock import MagicMock


class TestPromptCachingHelpers:
    """Test the cache control helper methods in ClaudeClient."""

    def test_should_cache_long_prompt(self):
        """Long prompts (1024+ tokens) should be cached."""
        from remy.ai.claude_client import ClaudeClient
        
        client = ClaudeClient.__new__(ClaudeClient)
        client._client = MagicMock()
        
        # 1024 tokens * 4 chars/token = 4096 chars minimum
        long_prompt = "x" * 5000
        assert client._should_cache(long_prompt) is True

    def test_should_not_cache_short_prompt(self):
        """Short prompts should not be cached."""
        from remy.ai.claude_client import ClaudeClient
        
        client = ClaudeClient.__new__(ClaudeClient)
        client._client = MagicMock()
        
        short_prompt = "Hello, how are you?"
        assert client._should_cache(short_prompt) is False

    def test_wrap_system_with_cache_long(self):
        """Long system prompts should be wrapped with cache_control."""
        from remy.ai.claude_client import ClaudeClient
        
        client = ClaudeClient.__new__(ClaudeClient)
        client._client = MagicMock()
        
        long_prompt = "x" * 5000
        result = client._wrap_system_with_cache(long_prompt)
        
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert result[0]["text"] == long_prompt
        assert result[0]["cache_control"] == {"type": "ephemeral"}

    def test_wrap_system_with_cache_short(self):
        """Short system prompts should be returned as-is."""
        from remy.ai.claude_client import ClaudeClient
        
        client = ClaudeClient.__new__(ClaudeClient)
        client._client = MagicMock()
        
        short_prompt = "Be helpful."
        result = client._wrap_system_with_cache(short_prompt)
        
        assert result == short_prompt

    def test_wrap_tools_with_cache(self):
        """Tool schemas should have cache_control on the last item."""
        from remy.ai.claude_client import ClaudeClient
        
        client = ClaudeClient.__new__(ClaudeClient)
        client._client = MagicMock()
        
        tools = [
            {"name": "tool1", "description": "First tool"},
            {"name": "tool2", "description": "Second tool"},
        ]
        result = client._wrap_tools_with_cache(tools)
        
        assert len(result) == 2
        assert "cache_control" not in result[0]
        assert result[1]["cache_control"] == {"type": "ephemeral"}

    def test_wrap_tools_with_cache_none(self):
        """None tools should return None."""
        from remy.ai.claude_client import ClaudeClient
        
        client = ClaudeClient.__new__(ClaudeClient)
        client._client = MagicMock()
        
        assert client._wrap_tools_with_cache(None) is None

    def test_wrap_tools_with_cache_empty(self):
        """Empty tools list should return None."""
        from remy.ai.claude_client import ClaudeClient
        
        client = ClaudeClient.__new__(ClaudeClient)
        client._client = MagicMock()
        
        assert client._wrap_tools_with_cache([]) is None
