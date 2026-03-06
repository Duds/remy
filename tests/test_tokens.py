"""
Tests for remy.utils.tokens (zero-trust audit: character-based estimation only).

Covers estimate_tokens() and format_token_count(). Ensures count_tokens() is not
in the public API (removed to avoid blocking the event loop in async paths).
"""

from __future__ import annotations

import pytest

from remy.utils import tokens


class TestEstimateTokens:
    """estimate_tokens() — character-based heuristic."""

    def test_empty_string_returns_zero(self):
        assert tokens.estimate_tokens("") == 0

    def test_prose_uses_chars_per_token_prose(self):
        # Prose: no structured markers → ~4 chars/token
        text = "The quick brown fox jumps over the lazy dog."
        # 44 chars / 4 = 11
        assert tokens.estimate_tokens(text) == 11

    def test_structured_xml_uses_fewer_chars_per_token(self):
        text = "<xml><tag>content</tag></xml>"
        # Structured: has "<" → ~3.5 chars/token → more tokens for same length
        n = tokens.estimate_tokens(text)
        # 30 chars / 3.5 ≈ 8
        assert n == 8

    def test_structured_json(self):
        text = '{"key": "value", "n": 42}'
        assert tokens.estimate_tokens(text) == int(len(text) / 3.5)

    def test_structured_code_marker_def(self):
        text = "def hello(): pass"
        assert tokens.estimate_tokens(text) == int(len(text) / 3.5)

    def test_structured_code_marker_import(self):
        text = "import os\nfrom pathlib import Path"
        assert tokens.estimate_tokens(text) == int(len(text) / 3.5)

    def test_structured_code_backticks(self):
        text = "```python\nprint(1)\n```"
        assert tokens.estimate_tokens(text) == int(len(text) / 3.5)

    def test_first_marker_wins_prose_vs_structured(self):
        # Prose then structured: first marker in list that appears determines type
        text = "Hello world. Then <tag>."
        # Has "<" so structured
        assert tokens.estimate_tokens(text) == int(len(text) / 3.5)

    def test_public_api_has_no_count_tokens(self):
        """count_tokens() was removed; must not be in public API (zero-trust)."""
        assert hasattr(tokens, "estimate_tokens")
        assert hasattr(tokens, "format_token_count")
        assert not hasattr(tokens, "count_tokens"), (
            "count_tokens must not exist: it would block the event loop if used in async code."
        )


class TestFormatTokenCount:
    """format_token_count() — display formatting."""

    def test_zero(self):
        assert tokens.format_token_count(0) == "0 tokens"

    def test_small(self):
        assert tokens.format_token_count(42) == "42 tokens"

    def test_thousands_comma(self):
        assert tokens.format_token_count(1234) == "1,234 tokens"

    def test_large(self):
        assert tokens.format_token_count(1_234_567) == "1,234,567 tokens"
