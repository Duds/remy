"""Tests for remy.bot.handlers.base (Bug 8: space preservation when flattening content)."""

from remy.bot.handlers.base import _sanitize_messages_for_claude


def test_sanitize_messages_preserves_space_only_blocks():
    """Space-only and empty segments are preserved when flattening content blocks (Bug 8)."""
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Hello"},
                {"type": "text", "text": " "},
                {"type": "text", "text": "world"},
            ],
        },
    ]
    out = _sanitize_messages_for_claude(msgs)
    assert len(out) == 1
    assert out[0]["content"] == "Hello world"


def test_sanitize_messages_preserves_empty_segments():
    """Empty string segments are preserved in order so spacing is not collapsed."""
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "word1"},
                {"type": "text", "text": ""},
                {"type": "text", "text": " word2"},
            ],
        },
    ]
    out = _sanitize_messages_for_claude(msgs)
    assert len(out) == 1
    assert out[0]["content"] == "word1 word2"


def test_sanitize_messages_drops_tool_turns():
    """Messages containing tool_use or tool_result blocks are still dropped."""
    msgs = [
        {"role": "user", "content": "Hello"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Hi"},
                {"type": "tool_use", "id": "x", "name": "foo", "input": {}},
            ],
        },
    ]
    out = _sanitize_messages_for_claude(msgs)
    assert len(out) == 1
    assert out[0]["role"] == "user" and out[0]["content"] == "Hello"


def test_sanitize_messages_skips_whitespace_only_after_join():
    """Messages that become only whitespace after flattening are skipped."""
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": " "},
                {"type": "text", "text": ""},
            ],
        },
    ]
    out = _sanitize_messages_for_claude(msgs)
    assert len(out) == 0


def test_sanitize_messages_inserts_space_between_adjacent_words():
    """Adjacent text blocks without internal space get a space between them (Bug 43)."""
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "hello"},
                {"type": "text", "text": "world"},
            ],
        },
    ]
    out = _sanitize_messages_for_claude(msgs)
    assert len(out) == 1
    assert out[0]["content"] == "hello world"
