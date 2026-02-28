"""
DiagnosticsRunner — orchestrates health checks across all Remy subsystems.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from ..ai.claude_client import ClaudeClient
    from ..ai.mistral_client import MistralClient
    from ..ai.moonshot_client import MoonshotClient
    from ..ai.ollama_client import OllamaClient
    from ..ai.tool_registry import ToolRegistry
    from ..config import Settings
    from ..memory.database import DatabaseManager
    from ..memory.embeddings import EmbeddingStore
    from ..memory.knowledge import KnowledgeStore
    from ..memory.conversations import ConversationStore
    from ..scheduler.proactive import ProactiveScheduler

logger = logging.getLogger(__name__)

# Process start time for uptime calculation
_PROCESS_START_TIME = time.time()


class CheckStatus(Enum):
    """Status of a diagnostic check."""
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class CheckResult:
    """Result of a single diagnostic check."""
    name: str
    status: CheckStatus
    message: str
    duration_ms: float
    details: dict[str, Any] | None = None


@dataclass
class DiagnosticsResult:
    """Complete diagnostics run result."""
    checks: list[CheckResult]
    overall_status: CheckStatus
    total_duration_ms: float
    version: str
    python_version: str
    uptime_seconds: float
    last_restart: datetime


class DiagnosticsRunner:
    """
    Runs comprehensive health checks across all Remy subsystems.
    
    Each check is isolated — if one crashes, the rest still run.
    Checks have a 10-second timeout to prevent blocking.
    """
    
    def __init__(
        self,
        db: "DatabaseManager | None" = None,
        embeddings: "EmbeddingStore | None" = None,
        knowledge_store: "KnowledgeStore | None" = None,
        conv_store: "ConversationStore | None" = None,
        claude_client: "ClaudeClient | None" = None,
        mistral_client: "MistralClient | None" = None,
        moonshot_client: "MoonshotClient | None" = None,
        ollama_client: "OllamaClient | None" = None,
        tool_registry: "ToolRegistry | None" = None,
        scheduler: "ProactiveScheduler | None" = None,
        settings: "Settings | None" = None,
    ) -> None:
        self._db = db
        self._embeddings = embeddings
        self._knowledge_store = knowledge_store
        self._conv_store = conv_store
        self._claude_client = claude_client
        self._mistral_client = mistral_client
        self._moonshot_client = moonshot_client
        self._ollama_client = ollama_client
        self._tool_registry = tool_registry
        self._scheduler = scheduler
        self._settings = settings
        
    async def run_all(self) -> DiagnosticsResult:
        """Run all diagnostic checks and return aggregated results."""
        from .. import __version__
        
        start_time = time.perf_counter()
        results: list[CheckResult] = []
        
        checks: list[tuple[str, Callable[[], Awaitable[CheckResult]]]] = [
            ("Database", self._check_database),
            ("Memory/Embeddings", self._check_embeddings),
            ("Knowledge Store", self._check_knowledge),
            ("Conversation History", self._check_conversations),
            ("Anthropic", self._check_anthropic),
            ("Mistral", self._check_mistral),
            ("Moonshot", self._check_moonshot),
            ("Ollama", self._check_ollama),
            ("Tool Registry", self._check_tools),
            ("Scheduler", self._check_scheduler),
            ("Configuration", self._check_config),
            ("File System", self._check_filesystem),
        ]
        
        for name, check_fn in checks:
            check_start = time.perf_counter()
            try:
                result = await asyncio.wait_for(check_fn(), timeout=10.0)
            except asyncio.TimeoutError:
                result = CheckResult(
                    name=name,
                    status=CheckStatus.FAIL,
                    message="Timed out (>10s)",
                    duration_ms=10000.0,
                )
            except Exception as e:
                duration_ms = (time.perf_counter() - check_start) * 1000
                result = CheckResult(
                    name=name,
                    status=CheckStatus.FAIL,
                    message=f"{type(e).__name__}: {e}",
                    duration_ms=duration_ms,
                )
                logger.exception("Diagnostic check %s crashed", name)
            results.append(result)
        
        total_duration_ms = (time.perf_counter() - start_time) * 1000
        
        # Determine overall status
        has_failures = any(r.status == CheckStatus.FAIL for r in results)
        has_warnings = any(r.status == CheckStatus.WARN for r in results)
        
        if has_failures:
            overall_status = CheckStatus.FAIL
        elif has_warnings:
            overall_status = CheckStatus.WARN
        else:
            overall_status = CheckStatus.PASS
        
        # Calculate uptime
        uptime_seconds = time.time() - _PROCESS_START_TIME
        last_restart = datetime.fromtimestamp(_PROCESS_START_TIME, tz=timezone.utc)
        
        return DiagnosticsResult(
            checks=results,
            overall_status=overall_status,
            total_duration_ms=total_duration_ms,
            version=__version__,
            python_version=platform.python_version(),
            uptime_seconds=uptime_seconds,
            last_restart=last_restart,
        )
    
    async def _check_database(self) -> CheckResult:
        """Check SQLite database connection and schema."""
        start = time.perf_counter()
        
        if self._db is None:
            return CheckResult(
                name="Database",
                status=CheckStatus.WARN,
                message="Not configured",
                duration_ms=0,
            )
        
        try:
            async with self._db.get_connection() as conn:
                # Check tables exist
                cursor = await conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                rows = await cursor.fetchall()
                table_names = {row[0] for row in rows}
                
                expected = {
                    "users", "conversations", "facts", "goals", "knowledge",
                    "embeddings", "api_calls", "automations", "background_jobs",
                }
                missing = expected - table_names
                
                # Get row counts for key tables
                counts = {}
                for table in ["knowledge", "facts", "goals", "conversations"]:
                    if table in table_names:
                        cursor = await conn.execute(f"SELECT COUNT(*) FROM {table}")
                        row = await cursor.fetchone()
                        counts[table] = row[0] if row else 0
                
                duration_ms = (time.perf_counter() - start) * 1000
                
                if missing:
                    return CheckResult(
                        name="Database",
                        status=CheckStatus.WARN,
                        message=f"Missing tables: {', '.join(sorted(missing))}",
                        duration_ms=duration_ms,
                        details={"tables": len(table_names), "missing": list(missing)},
                    )
                
                return CheckResult(
                    name="Database",
                    status=CheckStatus.PASS,
                    message=f"{len(table_names)} tables, {counts.get('knowledge', 0)} knowledge entries",
                    duration_ms=duration_ms,
                    details={"tables": len(table_names), "counts": counts},
                )
                
        except Exception as e:
            return CheckResult(
                name="Database",
                status=CheckStatus.FAIL,
                message=str(e),
                duration_ms=(time.perf_counter() - start) * 1000,
            )
    
    async def _check_embeddings(self) -> CheckResult:
        """Check embedding model and vector store."""
        start = time.perf_counter()
        
        if self._embeddings is None:
            return CheckResult(
                name="Memory/Embeddings",
                status=CheckStatus.WARN,
                message="Not configured",
                duration_ms=0,
            )
        
        try:
            from ..memory.database import SQLITE_VEC_AVAILABLE
            
            # Check if model is loaded (will trigger lazy load if not)
            model = self._embeddings._get_model()
            model_name = getattr(model, "model_name", "unknown")
            
            # Count embeddings
            vector_count = 0
            if self._db is not None:
                async with self._db.get_connection() as conn:
                    cursor = await conn.execute("SELECT COUNT(*) FROM embeddings")
                    row = await cursor.fetchone()
                    vector_count = row[0] if row else 0
            
            duration_ms = (time.perf_counter() - start) * 1000
            
            vec_status = "ANN enabled" if SQLITE_VEC_AVAILABLE else "FTS5 fallback"
            return CheckResult(
                name="Memory/Embeddings",
                status=CheckStatus.PASS,
                message=f"Model loaded, {vector_count:,} vectors ({vec_status})",
                duration_ms=duration_ms,
                details={
                    "model": model_name,
                    "vectors": vector_count,
                    "ann_available": SQLITE_VEC_AVAILABLE,
                },
            )
            
        except Exception as e:
            return CheckResult(
                name="Memory/Embeddings",
                status=CheckStatus.FAIL,
                message=str(e),
                duration_ms=(time.perf_counter() - start) * 1000,
            )
    
    async def _check_knowledge(self) -> CheckResult:
        """Check knowledge store read/write capability."""
        start = time.perf_counter()
        
        if self._knowledge_store is None:
            return CheckResult(
                name="Knowledge Store",
                status=CheckStatus.WARN,
                message="Not configured",
                duration_ms=0,
            )
        
        try:
            # Count entries (use user_id 0 for system-level check)
            if self._db is not None:
                async with self._db.get_connection() as conn:
                    cursor = await conn.execute("SELECT COUNT(*) FROM knowledge")
                    row = await cursor.fetchone()
                    count = row[0] if row else 0
                    
                    # Check entity types distribution
                    cursor = await conn.execute(
                        "SELECT entity_type, COUNT(*) FROM knowledge GROUP BY entity_type"
                    )
                    type_counts = {r[0]: r[1] for r in await cursor.fetchall()}
            else:
                count = 0
                type_counts = {}
            
            duration_ms = (time.perf_counter() - start) * 1000
            
            return CheckResult(
                name="Knowledge Store",
                status=CheckStatus.PASS,
                message=f"{count:,} entries, read OK",
                duration_ms=duration_ms,
                details={"total": count, "by_type": type_counts},
            )
            
        except Exception as e:
            return CheckResult(
                name="Knowledge Store",
                status=CheckStatus.FAIL,
                message=str(e),
                duration_ms=(time.perf_counter() - start) * 1000,
            )
    
    async def _check_conversations(self) -> CheckResult:
        """Check conversation history store."""
        start = time.perf_counter()
        
        if self._conv_store is None:
            return CheckResult(
                name="Conversation History",
                status=CheckStatus.WARN,
                message="Not configured",
                duration_ms=0,
            )
        
        try:
            # Count conversation files
            sessions_dir = self._conv_store.sessions_dir
            if os.path.exists(sessions_dir):
                files = [f for f in os.listdir(sessions_dir) if f.endswith(".jsonl")]
                count = len(files)
            else:
                count = 0
            
            duration_ms = (time.perf_counter() - start) * 1000
            
            return CheckResult(
                name="Conversation History",
                status=CheckStatus.PASS,
                message=f"{count} session files",
                duration_ms=duration_ms,
                details={"sessions": count},
            )
            
        except Exception as e:
            return CheckResult(
                name="Conversation History",
                status=CheckStatus.FAIL,
                message=str(e),
                duration_ms=(time.perf_counter() - start) * 1000,
            )
    
    async def _check_anthropic(self) -> CheckResult:
        """Check Anthropic Claude API connectivity."""
        start = time.perf_counter()
        
        if self._claude_client is None:
            return CheckResult(
                name="Anthropic",
                status=CheckStatus.WARN,
                message="Not configured",
                duration_ms=0,
            )
        
        try:
            available = await self._claude_client.ping()
            duration_ms = (time.perf_counter() - start) * 1000
            
            if available:
                return CheckResult(
                    name="Anthropic",
                    status=CheckStatus.PASS,
                    message="Connected (models list OK)",
                    duration_ms=duration_ms,
                )
            else:
                return CheckResult(
                    name="Anthropic",
                    status=CheckStatus.FAIL,
                    message="API unreachable",
                    duration_ms=duration_ms,
                )
                
        except Exception as e:
            error_msg = str(e)
            if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
                status = CheckStatus.FAIL
                message = "Invalid API key"
            else:
                status = CheckStatus.WARN
                message = f"Unreachable: {error_msg[:50]}"
            
            return CheckResult(
                name="Anthropic",
                status=status,
                message=message,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
    
    async def _check_mistral(self) -> CheckResult:
        """Check Mistral AI API connectivity."""
        start = time.perf_counter()
        
        if self._mistral_client is None:
            return CheckResult(
                name="Mistral",
                status=CheckStatus.WARN,
                message="Not configured",
                duration_ms=0,
            )
        
        try:
            available = await self._mistral_client.is_available()
            duration_ms = (time.perf_counter() - start) * 1000
            
            if available:
                return CheckResult(
                    name="Mistral",
                    status=CheckStatus.PASS,
                    message="Connected",
                    duration_ms=duration_ms,
                )
            else:
                # Check if API key is configured
                if not self._mistral_client._api_key:
                    return CheckResult(
                        name="Mistral",
                        status=CheckStatus.WARN,
                        message="Not configured",
                        duration_ms=duration_ms,
                    )
                return CheckResult(
                    name="Mistral",
                    status=CheckStatus.WARN,
                    message="API unreachable",
                    duration_ms=duration_ms,
                )
                
        except Exception as e:
            return CheckResult(
                name="Mistral",
                status=CheckStatus.WARN,
                message=f"Unreachable: {str(e)[:50]}",
                duration_ms=(time.perf_counter() - start) * 1000,
            )
    
    async def _check_moonshot(self) -> CheckResult:
        """Check Moonshot AI API connectivity."""
        start = time.perf_counter()
        
        if self._moonshot_client is None:
            return CheckResult(
                name="Moonshot",
                status=CheckStatus.WARN,
                message="Not configured",
                duration_ms=0,
            )
        
        try:
            available = await self._moonshot_client.is_available()
            duration_ms = (time.perf_counter() - start) * 1000
            
            if available:
                return CheckResult(
                    name="Moonshot",
                    status=CheckStatus.PASS,
                    message="Connected",
                    duration_ms=duration_ms,
                )
            else:
                # Check if API key is configured
                if not self._moonshot_client._api_key:
                    return CheckResult(
                        name="Moonshot",
                        status=CheckStatus.WARN,
                        message="Not configured",
                        duration_ms=duration_ms,
                    )
                return CheckResult(
                    name="Moonshot",
                    status=CheckStatus.WARN,
                    message="API unreachable",
                    duration_ms=duration_ms,
                )
                
        except Exception as e:
            return CheckResult(
                name="Moonshot",
                status=CheckStatus.WARN,
                message=f"Unreachable: {str(e)[:50]}",
                duration_ms=(time.perf_counter() - start) * 1000,
            )
    
    async def _check_ollama(self) -> CheckResult:
        """Check Ollama local LLM availability."""
        start = time.perf_counter()
        
        if self._ollama_client is None:
            return CheckResult(
                name="Ollama",
                status=CheckStatus.WARN,
                message="Not configured",
                duration_ms=0,
            )
        
        try:
            available = await self._ollama_client.is_available()
            duration_ms = (time.perf_counter() - start) * 1000
            
            if available:
                return CheckResult(
                    name="Ollama",
                    status=CheckStatus.PASS,
                    message=f"Available ({self._ollama_client.model})",
                    duration_ms=duration_ms,
                    details={"model": self._ollama_client.model},
                )
            else:
                return CheckResult(
                    name="Ollama",
                    status=CheckStatus.WARN,
                    message="Not running (fallback unavailable)",
                    duration_ms=duration_ms,
                )
                
        except Exception as e:
            return CheckResult(
                name="Ollama",
                status=CheckStatus.WARN,
                message=f"Unreachable: {str(e)[:50]}",
                duration_ms=(time.perf_counter() - start) * 1000,
            )
    
    async def _check_tools(self) -> CheckResult:
        """Check tool registry status."""
        start = time.perf_counter()
        
        if self._tool_registry is None:
            return CheckResult(
                name="Tool Registry",
                status=CheckStatus.WARN,
                message="Not configured",
                duration_ms=0,
            )
        
        try:
            schemas = self._tool_registry.schemas
            tool_count = len(schemas)
            tool_names = [s["name"] for s in schemas]
            
            duration_ms = (time.perf_counter() - start) * 1000
            
            return CheckResult(
                name="Tool Registry",
                status=CheckStatus.PASS,
                message=f"{tool_count} tools registered",
                duration_ms=duration_ms,
                details={"count": tool_count, "tools": tool_names},
            )
            
        except Exception as e:
            return CheckResult(
                name="Tool Registry",
                status=CheckStatus.FAIL,
                message=str(e),
                duration_ms=(time.perf_counter() - start) * 1000,
            )
    
    async def _check_scheduler(self) -> CheckResult:
        """Check proactive scheduler status."""
        start = time.perf_counter()
        
        if self._scheduler is None:
            return CheckResult(
                name="Scheduler",
                status=CheckStatus.WARN,
                message="Not configured",
                duration_ms=0,
            )
        
        try:
            scheduler = self._scheduler._scheduler
            running = scheduler.running if scheduler else False
            
            if not running:
                return CheckResult(
                    name="Scheduler",
                    status=CheckStatus.WARN,
                    message="Not running",
                    duration_ms=(time.perf_counter() - start) * 1000,
                )
            
            # Get next scheduled job
            jobs = scheduler.get_jobs()
            next_job = None
            next_run = None
            
            for job in jobs:
                if job.next_run_time:
                    if next_run is None or job.next_run_time < next_run:
                        next_run = job.next_run_time
                        next_job = job.id
            
            duration_ms = (time.perf_counter() - start) * 1000
            
            if next_run:
                # Calculate time until next job
                now = datetime.now(next_run.tzinfo)
                delta = next_run - now
                hours, remainder = divmod(int(delta.total_seconds()), 3600)
                minutes = remainder // 60
                
                return CheckResult(
                    name="Scheduler",
                    status=CheckStatus.PASS,
                    message=f"Running, {len(jobs)} jobs, next in {hours}h {minutes}m",
                    duration_ms=duration_ms,
                    details={
                        "running": True,
                        "job_count": len(jobs),
                        "next_job": next_job,
                        "next_run": next_run.isoformat() if next_run else None,
                    },
                )
            else:
                return CheckResult(
                    name="Scheduler",
                    status=CheckStatus.PASS,
                    message=f"Running, {len(jobs)} jobs",
                    duration_ms=duration_ms,
                    details={"running": True, "job_count": len(jobs)},
                )
                
        except Exception as e:
            return CheckResult(
                name="Scheduler",
                status=CheckStatus.FAIL,
                message=str(e),
                duration_ms=(time.perf_counter() - start) * 1000,
            )
    
    async def _check_config(self) -> CheckResult:
        """Check configuration and required environment variables."""
        start = time.perf_counter()
        
        if self._settings is None:
            return CheckResult(
                name="Configuration",
                status=CheckStatus.WARN,
                message="Settings not available",
                duration_ms=0,
            )
        
        try:
            missing = []
            warnings = []
            
            # Required vars
            if not self._settings.telegram_bot_token:
                missing.append("TELEGRAM_BOT_TOKEN")
            if not self._settings.anthropic_api_key:
                missing.append("ANTHROPIC_API_KEY")
            
            # Optional but recommended
            if not self._settings.telegram_allowed_users:
                warnings.append("No allowed users configured")
            
            # Check data directory
            if not os.path.exists(self._settings.data_dir):
                warnings.append(f"Data dir missing: {self._settings.data_dir}")
            
            duration_ms = (time.perf_counter() - start) * 1000
            
            if missing:
                return CheckResult(
                    name="Configuration",
                    status=CheckStatus.FAIL,
                    message=f"Missing: {', '.join(missing)}",
                    duration_ms=duration_ms,
                    details={"missing": missing, "warnings": warnings},
                )
            
            if warnings:
                return CheckResult(
                    name="Configuration",
                    status=CheckStatus.WARN,
                    message="; ".join(warnings),
                    duration_ms=duration_ms,
                    details={"warnings": warnings},
                )
            
            return CheckResult(
                name="Configuration",
                status=CheckStatus.PASS,
                message="All required vars present",
                duration_ms=duration_ms,
            )
            
        except Exception as e:
            return CheckResult(
                name="Configuration",
                status=CheckStatus.FAIL,
                message=str(e),
                duration_ms=(time.perf_counter() - start) * 1000,
            )
    
    async def _check_filesystem(self) -> CheckResult:
        """Check file system access and disk space."""
        start = time.perf_counter()
        
        try:
            data_dir = self._settings.data_dir if self._settings else "./data"
            
            # Check write access
            test_file = os.path.join(data_dir, ".diagnostics_test")
            try:
                os.makedirs(data_dir, exist_ok=True)
                with open(test_file, "w") as f:
                    f.write("test")
                os.remove(test_file)
                write_ok = True
            except Exception:
                write_ok = False
            
            # Check disk space
            try:
                usage = shutil.disk_usage(data_dir)
                free_gb = usage.free / (1024 ** 3)
                total_gb = usage.total / (1024 ** 3)
            except Exception:
                free_gb = 0
                total_gb = 0
            
            duration_ms = (time.perf_counter() - start) * 1000
            
            # Determine status
            if not write_ok:
                return CheckResult(
                    name="File System",
                    status=CheckStatus.FAIL,
                    message=f"Cannot write to {data_dir}",
                    duration_ms=duration_ms,
                )
            
            if free_gb < 1.0:
                return CheckResult(
                    name="File System",
                    status=CheckStatus.FAIL,
                    message=f"Critical: {free_gb:.1f} GB free",
                    duration_ms=duration_ms,
                    details={"free_gb": free_gb, "total_gb": total_gb},
                )
            
            if free_gb < 5.0:
                return CheckResult(
                    name="File System",
                    status=CheckStatus.WARN,
                    message=f"{free_gb:.1f} GB remaining",
                    duration_ms=duration_ms,
                    details={"free_gb": free_gb, "total_gb": total_gb},
                )
            
            return CheckResult(
                name="File System",
                status=CheckStatus.PASS,
                message=f"{free_gb:.1f} GB free, write OK",
                duration_ms=duration_ms,
                details={"free_gb": free_gb, "total_gb": total_gb, "write_ok": True},
            )
            
        except Exception as e:
            return CheckResult(
                name="File System",
                status=CheckStatus.FAIL,
                message=str(e),
                duration_ms=(time.perf_counter() - start) * 1000,
            )


def format_diagnostics_output(result: DiagnosticsResult, timezone_str: str = "Australia/Sydney") -> str:
    """
    Format diagnostics results for Telegram output.
    
    Uses Markdown formatting compatible with Telegram's parse_mode="Markdown".
    """
    from datetime import timezone as tz
    try:
        import zoneinfo
        local_tz = zoneinfo.ZoneInfo(timezone_str)
    except Exception:
        local_tz = tz.utc
    
    lines = ["🔬 *Remy Self-Diagnostics*", ""]
    
    # Overall status header
    if result.overall_status == CheckStatus.PASS:
        lines.append("🟢 *All systems operational*")
    elif result.overall_status == CheckStatus.WARN:
        lines.append("🟡 *Systems degraded*")
    else:
        lines.append("🔴 *Systems impaired*")
    
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    
    # Individual check results
    for check in result.checks:
        if check.status == CheckStatus.PASS:
            icon = "✅"
        elif check.status == CheckStatus.WARN:
            icon = "⚠️"
        else:
            icon = "❌"
        
        # Format duration
        if check.duration_ms < 1:
            duration_str = "<1ms"
        elif check.duration_ms < 1000:
            duration_str = f"{check.duration_ms:.0f}ms"
        else:
            duration_str = f"{check.duration_ms/1000:.1f}s"
        
        lines.append(f"{icon} *{check.name}* — {check.message} _({duration_str})_")
    
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    
    # System info
    lines.append("📊 *System Info*")
    lines.append(f"  Version: {result.version}")
    lines.append(f"  Python: {result.python_version}")
    
    # Format uptime
    uptime_secs = result.uptime_seconds
    days, remainder = divmod(int(uptime_secs), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    
    if days > 0:
        uptime_str = f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        uptime_str = f"{hours}h {minutes}m"
    else:
        uptime_str = f"{minutes}m"
    
    lines.append(f"  Uptime: {uptime_str}")
    
    # Format last restart in local timezone
    local_restart = result.last_restart.astimezone(local_tz)
    lines.append(f"  Last restart: {local_restart.strftime('%d/%m/%Y %H:%M')}")
    
    lines.append("")
    
    # Total time
    if result.total_duration_ms < 1000:
        total_str = f"{result.total_duration_ms:.0f}ms"
    else:
        total_str = f"{result.total_duration_ms/1000:.2f}s"
    
    lines.append(f"⏱️ Total diagnostics time: {total_str}")
    
    return "\n".join(lines)
