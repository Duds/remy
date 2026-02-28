import logging
from datetime import datetime, timezone

from ..memory.database import DatabaseManager
from ..models import TokenUsage

logger = logging.getLogger(__name__)

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
) -> None:
    """Write one row to api_calls. Fire-and-forget — catches and logs all exceptions."""
    try:
        async with db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO api_calls
                  (user_id, session_key, timestamp, provider, model, category,
                   call_site, input_tokens, output_tokens, cache_creation_tokens,
                   cache_read_tokens, latency_ms, fallback)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, session_key,
                    datetime.now(timezone.utc).isoformat(),
                    provider, model, category, call_site,
                    usage.input_tokens, usage.output_tokens,
                    usage.cache_creation_tokens, usage.cache_read_tokens,
                    latency_ms, int(fallback),
                ),
            )
            await conn.commit()
    except Exception as e:
        logger.warning("Failed to write api_call log: %s", e)
