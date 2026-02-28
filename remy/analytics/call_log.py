import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..memory.database import DatabaseManager
from ..models import TokenUsage

if TYPE_CHECKING:
    from .timing import RequestTiming

logger = logging.getLogger(__name__)

# Lazy import for Prometheus metrics (optional dependency)
_metrics_available = False
try:
    from .metrics import increment_api_call as _prom_increment_api_call
    from .metrics import observe_request_timing as _prom_observe_timing
    from .metrics import observe_cache_hit_rate as _prom_observe_cache_hit_rate
    _metrics_available = True
except ImportError:
    pass


def calculate_cache_hit_rate(usage: TokenUsage) -> float:
    """
    Calculate cache hit rate as a percentage (0.0 to 1.0).
    
    Cache hit rate = cache_read_tokens / (cache_read_tokens + non-cached input tokens)
    
    A rate of 1.0 means all cacheable content was served from cache.
    A rate of 0.0 means no cache hits (either first request or cache expired).
    """
    total_input = usage.input_tokens + usage.cache_read_tokens
    if total_input == 0:
        return 0.0
    return usage.cache_read_tokens / total_input


async def log_api_call(
    db: DatabaseManager,
    *,
    user_id: int,
    session_key: str,
    provider: str,
    model: str,
    category: str,
    call_site: str,
    usage: TokenUsage,
    latency_ms: int,
    fallback: bool = False,
    timing: "RequestTiming | None" = None,
) -> None:
    """
    Write one row to api_calls. Fire-and-forget — catches and logs all exceptions.

    If timing is provided, stores per-phase breakdown (memory_injection_ms, ttft_ms,
    tool_execution_ms, streaming_ms).

    Also records Prometheus metrics if prometheus-client is available.
    Calculates and logs cache hit rate for monitoring prompt caching effectiveness.
    """
    # Calculate cache hit rate for monitoring
    cache_hit_rate = calculate_cache_hit_rate(usage)
    if usage.cache_read_tokens > 0:
        logger.debug(
            "Cache hit rate: %.1f%% (read=%d, creation=%d, input=%d)",
            cache_hit_rate * 100,
            usage.cache_read_tokens,
            usage.cache_creation_tokens,
            usage.input_tokens,
        )

    # Record Prometheus metrics (non-blocking, best-effort)
    if _metrics_available:
        try:
            _prom_increment_api_call(
                provider=provider,
                model=model,
                call_site=call_site,
                latency_ms=latency_ms,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
            if timing is not None:
                _prom_observe_timing(timing)
            _prom_observe_cache_hit_rate(provider, model, cache_hit_rate, usage.cache_read_tokens)
        except Exception as e:
            logger.debug("Metrics recording failed (best-effort): %s", e)

    try:
        async with db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO api_calls
                  (user_id, session_key, timestamp, provider, model, category,
                   call_site, input_tokens, output_tokens, cache_creation_tokens,
                   cache_read_tokens, latency_ms, fallback,
                   memory_injection_ms, ttft_ms, tool_execution_ms, streaming_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, session_key,
                    datetime.now(timezone.utc).isoformat(),
                    provider, model, category, call_site,
                    usage.input_tokens, usage.output_tokens,
                    usage.cache_creation_tokens, usage.cache_read_tokens,
                    latency_ms, int(fallback),
                    timing.memory_injection_ms if timing else 0,
                    timing.ttft_ms if timing else 0,
                    timing.tool_execution_ms if timing else 0,
                    timing.streaming_ms if timing else 0,
                ),
            )
            await conn.commit()
    except Exception as e:
        logger.warning("Failed to write api_call log: %s", e)
