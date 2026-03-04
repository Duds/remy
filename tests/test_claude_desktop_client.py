"""Tests for remy.ai.claude_desktop_client (Bug 8: _extract_text preserves spacing)."""

import pytest

from remy.ai.claude_desktop_client import _extract_text


def test_extract_text_preserves_spacing_between_blocks():
    """Concatenates text blocks without inserting spaces (Bug 8)."""
    content = [
        {"type": "text", "text": "Hello"},
        {"type": "text", "text": " "},
        {"type": "text", "text": "world"},
    ]
    assert _extract_text(content) == "Hello world"


def test_extract_text_string_unchanged():
    """String content is returned as-is."""
    assert _extract_text("Hello world") == "Hello world"


def test_extract_text_empty_list():
    """Empty list returns empty string."""
    assert _extract_text([]) == ""


def test_extract_text_ignores_non_text_blocks():
    """Only text blocks are concatenated."""
    content = [
        {"type": "text", "text": "Hi"},
        {"type": "image", "source": {}},
        {"type": "text", "text": " there"},
    ]
    assert _extract_text(content) == "Hi there"
