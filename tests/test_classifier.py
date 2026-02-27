"""Tests for remy/ai/classifier.py — no network required."""

import pytest
from remy.ai.classifier import MessageClassifier


@pytest.fixture
def classifier():
    # No claude_client — only tests fast-path heuristics
    return MessageClassifier(claude_client=None)


@pytest.mark.asyncio
async def test_greeting_is_simple(classifier):
    assert await classifier.classify("hi") == "simple"
    assert await classifier.classify("Hello!") == "simple"
    assert await classifier.classify("thanks") == "simple"


@pytest.mark.asyncio
async def test_short_no_keywords_is_simple(classifier):
    assert await classifier.classify("What time is it?") == "simple"
    assert await classifier.classify("How are you?") == "simple"


@pytest.mark.asyncio
async def test_code_keywords_are_complex(classifier):
    assert await classifier.classify("Write a Python function to sort a list") == "complex"
    assert await classifier.classify("Refactor this module") == "complex"
    assert await classifier.classify("Debug this error in my code") == "complex"


@pytest.mark.asyncio
async def test_file_extensions_are_complex(classifier):
    assert await classifier.classify("Update app.py to add logging") == "complex"
    assert await classifier.classify("Fix the bug in index.ts") == "complex"


@pytest.mark.asyncio
async def test_code_fence_is_complex(classifier):
    assert await classifier.classify("```python\nprint('hi')\n```") == "complex"


@pytest.mark.asyncio
async def test_git_keywords_are_complex(classifier):
    assert await classifier.classify("git commit all changes") == "complex"
    assert await classifier.classify("Deploy to production") == "complex"


@pytest.mark.asyncio
async def test_ambiguous_long_message_defaults_complex(classifier):
    # No client + ambiguous → defaults to "complex"
    long_msg = "I was wondering if you could help me think through my strategy " * 5
    result = await classifier.classify(long_msg)
    assert result == "complex"
