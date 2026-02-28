"""
AI model pricing table for cost estimation.

Prices in USD per 1,000,000 tokens.
Last updated: February 2026 — update when provider prices change.

Sources:
- Anthropic: https://www.anthropic.com/pricing
- Mistral: https://mistral.ai/technology/#pricing
- Moonshot: https://platform.moonshot.cn/docs/pricing
"""

PRICES: dict[str, dict[str, float]] = {
    # Anthropic Claude models
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.00,
        "cache_read": 0.08,
        "cache_write": 1.00,
    },
    "claude-haiku-4-5": {
        "input": 0.80,
        "output": 4.00,
        "cache_read": 0.08,
        "cache_write": 1.00,
    },
    "claude-opus-4-6": {
        "input": 15.00,
        "output": 75.00,
        "cache_read": 1.50,
        "cache_write": 18.75,
    },
    # Mistral models
    "mistral-medium-3": {
        "input": 0.40,
        "output": 2.00,
    },
    "mistral-large-2411": {
        "input": 2.00,
        "output": 6.00,
    },
    "mistral-large-latest": {
        "input": 2.00,
        "output": 6.00,
    },
    # Moonshot models
    "moonshot-v1-8k": {
        "input": 0.15,
        "output": 0.15,
    },
    "moonshot-v1-32k": {
        "input": 0.23,
        "output": 0.23,
    },
    "moonshot-v1-128k": {
        "input": 0.60,
        "output": 0.60,
    },
    "kimi-k2-thinking": {
        "input": 2.00,
        "output": 8.00,
    },
}

_FALLBACK_PRICE: dict[str, float] = {"input": 0.0, "output": 0.0}

PRICE_TABLE_DATE = "Feb 2026"


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    """
    Return estimated USD cost for a call.

    Returns 0.0 for unknown models (including Ollama local models).
    """
    p = PRICES.get(model, _FALLBACK_PRICE)
    mtok = 1_000_000
    cost = (
        input_tokens / mtok * p.get("input", 0)
        + output_tokens / mtok * p.get("output", 0)
        + cache_read_tokens / mtok * p.get("cache_read", 0)
        + cache_creation_tokens / mtok * p.get("cache_write", 0)
    )
    return round(cost, 4)


def estimate_cache_savings(
    model: str,
    cache_read_tokens: int,
) -> float:
    """
    Return estimated USD savings from cache reads.

    Savings = (full input price - cache read price) × tokens.
    """
    p = PRICES.get(model, _FALLBACK_PRICE)
    if "cache_read" not in p or "input" not in p:
        return 0.0
    mtok = 1_000_000
    full_cost = cache_read_tokens / mtok * p["input"]
    cache_cost = cache_read_tokens / mtok * p["cache_read"]
    return round(full_cost - cache_cost, 4)
