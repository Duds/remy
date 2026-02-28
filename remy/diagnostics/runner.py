"""
DiagnosticsRunner — orchestrates health checks across all Remy subsystems.

Enhanced with performance monitoring for:
- Circuit breaker states (API resilience)
- Concurrency controls (extraction runners, per-user limits)
- Token usage and cache hit rate statistics
- Database retention and cleanup status
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
from datetime import datetime, timezone, timedelta
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
            # New performance monitoring checks
            ("Circuit Breakers", self._check_circuit_breakers),
            ("Concurrency Controls", self._check_concurrency),
            ("Token Usage (24h)", self._check_token_usage),
            ("Cache Performance", self._check_cache_performance),
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

    async def _check_circuit_breakers(self) -> CheckResult:
        """Check circuit breaker states for API resilience."""
        start = time.perf_counter()
        
        try:
            from ..utils.circuit_breaker import _circuit_breakers, CircuitState
            
            if not _circuit_breakers:
                return CheckResult(
                    name="Circuit Breakers",
                    status=CheckStatus.PASS,
                    message="No circuits registered (first request pending)",
                    duration_ms=(time.perf_counter() - start) * 1000,
                )
            
            states = {}
            open_circuits = []
            half_open_circuits = []
            
            for name, breaker in _circuit_breakers.items():
                states[name] = breaker.state.value
                if breaker.state == CircuitState.OPEN:
                    open_circuits.append(name)
                elif breaker.state == CircuitState.HALF_OPEN:
                    half_open_circuits.append(name)
            
            duration_ms = (time.perf_counter() - start) * 1000
            
            if open_circuits:
                return CheckResult(
                    name="Circuit Breakers",
                    status=CheckStatus.FAIL,
                    message=f"OPEN: {', '.join(open_circuits)}",
                    duration_ms=duration_ms,
                    details={"states": states, "open": open_circuits},
                )
            
            if half_open_circuits:
                return CheckResult(
                    name="Circuit Breakers",
                    status=CheckStatus.WARN,
                    message=f"HALF_OPEN: {', '.join(half_open_circuits)}",
                    duration_ms=duration_ms,
                    details={"states": states, "half_open": half_open_circuits},
                )
            
            return CheckResult(
                name="Circuit Breakers",
                status=CheckStatus.PASS,
                message=f"{len(_circuit_breakers)} circuits, all closed",
                duration_ms=duration_ms,
                details={"states": states},
            )
            
        except ImportError:
            return CheckResult(
                name="Circuit Breakers",
                status=CheckStatus.WARN,
                message="Module not available",
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name="Circuit Breakers",
                status=CheckStatus.FAIL,
                message=str(e),
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    async def _check_concurrency(self) -> CheckResult:
        """Check concurrency control status (extraction runners, per-user limits)."""
        start = time.perf_counter()
        
        try:
            from ..utils.concurrency import (
                _extraction_runner,
                _per_user_extraction_runner,
            )
            from ..bot.handlers.base import _user_active_requests
            from ..config import settings
            _MAX_CONCURRENT_PER_USER = settings.max_concurrent_per_user
            
            details = {}
            warnings = []
            
            # Check extraction runner
            if _extraction_runner is not None:
                details["extraction_active"] = _extraction_runner.active_count
                details["extraction_total"] = _extraction_runner.total_count
                if _extraction_runner.active_count >= 4:
                    warnings.append(f"Extraction runner near capacity ({_extraction_runner.active_count}/5)")
            
            # Check per-user extraction runner
            if _per_user_extraction_runner is not None:
                details["per_user_extraction_active"] = _per_user_extraction_runner.active_count
            
            # Check per-user active requests
            active_users = len(_user_active_requests)
            total_active = sum(_user_active_requests.values())
            details["users_with_active_requests"] = active_users
            details["total_active_requests"] = total_active
            details["max_per_user"] = _MAX_CONCURRENT_PER_USER
            
            # Check for users at limit
            users_at_limit = [
                uid for uid, count in _user_active_requests.items()
                if count >= _MAX_CONCURRENT_PER_USER
            ]
            if users_at_limit:
                warnings.append(f"{len(users_at_limit)} user(s) at concurrency limit")
                details["users_at_limit"] = len(users_at_limit)
            
            duration_ms = (time.perf_counter() - start) * 1000
            
            if warnings:
                return CheckResult(
                    name="Concurrency Controls",
                    status=CheckStatus.WARN,
                    message="; ".join(warnings),
                    duration_ms=duration_ms,
                    details=details,
                )
            
            msg_parts = []
            if total_active > 0:
                msg_parts.append(f"{total_active} active request(s)")
            if details.get("extraction_total", 0) > 0:
                msg_parts.append(f"{details['extraction_total']} extractions total")
            
            message = ", ".join(msg_parts) if msg_parts else "Idle"
            
            return CheckResult(
                name="Concurrency Controls",
                status=CheckStatus.PASS,
                message=message,
                duration_ms=duration_ms,
                details=details,
            )
            
        except ImportError as e:
            return CheckResult(
                name="Concurrency Controls",
                status=CheckStatus.WARN,
                message=f"Module not loaded: {e}",
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name="Concurrency Controls",
                status=CheckStatus.FAIL,
                message=str(e),
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    async def _check_token_usage(self) -> CheckResult:
        """Check token usage statistics for the last 24 hours."""
        start = time.perf_counter()
        
        if self._db is None:
            return CheckResult(
                name="Token Usage (24h)",
                status=CheckStatus.WARN,
                message="Database not configured",
                duration_ms=0,
            )
        
        try:
            async with self._db.get_connection() as conn:
                # Get token usage for last 24 hours
                cursor = await conn.execute(
                    """
                    SELECT 
                        COUNT(*) as call_count,
                        SUM(input_tokens) as total_input,
                        SUM(output_tokens) as total_output,
                        SUM(cache_creation_tokens) as cache_created,
                        SUM(cache_read_tokens) as cache_read,
                        AVG(latency_ms) as avg_latency,
                        SUM(fallback) as fallback_count
                    FROM api_calls
                    WHERE timestamp >= datetime('now', '-24 hours')
                    """
                )
                row = await cursor.fetchone()
                
                if row is None or row[0] == 0:
                    return CheckResult(
                        name="Token Usage (24h)",
                        status=CheckStatus.PASS,
                        message="No API calls in last 24h",
                        duration_ms=(time.perf_counter() - start) * 1000,
                    )
                
                call_count = row[0] or 0
                total_input = row[1] or 0
                total_output = row[2] or 0
                cache_created = row[3] or 0
                cache_read = row[4] or 0
                avg_latency = row[5] or 0
                fallback_count = row[6] or 0
                
                total_tokens = total_input + total_output
                
                # Estimate cost (rough: $3/M input, $15/M output for Sonnet)
                estimated_cost = (total_input * 3 + total_output * 15) / 1_000_000
                
                # Check against daily budget if configured
                daily_budget = 10.0  # Default $10/day
                if self._settings:
                    daily_budget = getattr(self._settings, 'max_cost_per_user_per_day_usd', 10.0)
                
                details = {
                    "calls": call_count,
                    "input_tokens": total_input,
                    "output_tokens": total_output,
                    "cache_created": cache_created,
                    "cache_read": cache_read,
                    "total_tokens": total_tokens,
                    "avg_latency_ms": round(avg_latency, 1),
                    "fallbacks": fallback_count,
                    "estimated_cost_usd": round(estimated_cost, 2),
                }
                
                duration_ms = (time.perf_counter() - start) * 1000
                
                # Format token count
                if total_tokens >= 1_000_000:
                    token_str = f"{total_tokens/1_000_000:.1f}M"
                elif total_tokens >= 1_000:
                    token_str = f"{total_tokens/1_000:.1f}K"
                else:
                    token_str = str(total_tokens)
                
                message = f"{call_count} calls, {token_str} tokens, ~${estimated_cost:.2f}"
                
                if estimated_cost > daily_budget * 0.8:
                    return CheckResult(
                        name="Token Usage (24h)",
                        status=CheckStatus.WARN,
                        message=f"{message} (>{int(daily_budget*0.8*100/daily_budget)}% of budget)",
                        duration_ms=duration_ms,
                        details=details,
                    )
                
                if fallback_count > call_count * 0.1:
                    return CheckResult(
                        name="Token Usage (24h)",
                        status=CheckStatus.WARN,
                        message=f"{message}, {fallback_count} fallbacks",
                        duration_ms=duration_ms,
                        details=details,
                    )
                
                return CheckResult(
                    name="Token Usage (24h)",
                    status=CheckStatus.PASS,
                    message=message,
                    duration_ms=duration_ms,
                    details=details,
                )
                
        except Exception as e:
            return CheckResult(
                name="Token Usage (24h)",
                status=CheckStatus.FAIL,
                message=str(e),
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    async def _check_cache_performance(self) -> CheckResult:
        """Check prompt cache hit rate and effectiveness."""
        start = time.perf_counter()
        
        if self._db is None:
            return CheckResult(
                name="Cache Performance",
                status=CheckStatus.WARN,
                message="Database not configured",
                duration_ms=0,
            )
        
        try:
            async with self._db.get_connection() as conn:
                # Get cache statistics for last 24 hours
                cursor = await conn.execute(
                    """
                    SELECT 
                        COUNT(*) as call_count,
                        SUM(input_tokens) as total_input,
                        SUM(cache_read_tokens) as cache_read,
                        SUM(cache_creation_tokens) as cache_created
                    FROM api_calls
                    WHERE timestamp >= datetime('now', '-24 hours')
                      AND provider = 'anthropic'
                    """
                )
                row = await cursor.fetchone()
                
                if row is None or row[0] == 0:
                    return CheckResult(
                        name="Cache Performance",
                        status=CheckStatus.PASS,
                        message="No Anthropic calls in last 24h",
                        duration_ms=(time.perf_counter() - start) * 1000,
                    )
                
                call_count = row[0] or 0
                total_input = row[1] or 0
                cache_read = row[2] or 0
                cache_created = row[3] or 0
                
                # Calculate cache hit rate
                total_cacheable = total_input + cache_read
                if total_cacheable > 0:
                    hit_rate = cache_read / total_cacheable
                else:
                    hit_rate = 0.0
                
                # Estimate savings (cache reads are 90% cheaper)
                tokens_saved = int(cache_read * 0.9)
                cost_saved = tokens_saved * 3 / 1_000_000  # $3/M input tokens
                
                details = {
                    "calls": call_count,
                    "cache_read_tokens": cache_read,
                    "cache_created_tokens": cache_created,
                    "hit_rate_percent": round(hit_rate * 100, 1),
                    "tokens_saved": tokens_saved,
                    "estimated_savings_usd": round(cost_saved, 2),
                }
                
                duration_ms = (time.perf_counter() - start) * 1000
                
                hit_rate_pct = hit_rate * 100
                
                if cache_read == 0 and call_count > 10:
                    return CheckResult(
                        name="Cache Performance",
                        status=CheckStatus.WARN,
                        message=f"0% cache hits across {call_count} calls",
                        duration_ms=duration_ms,
                        details=details,
                    )
                
                if hit_rate_pct < 30 and call_count > 20:
                    return CheckResult(
                        name="Cache Performance",
                        status=CheckStatus.WARN,
                        message=f"{hit_rate_pct:.0f}% hit rate (expected >50%)",
                        duration_ms=duration_ms,
                        details=details,
                    )
                
                message = f"{hit_rate_pct:.0f}% hit rate"
                if cost_saved > 0.01:
                    message += f", ~${cost_saved:.2f} saved"
                
                return CheckResult(
                    name="Cache Performance",
                    status=CheckStatus.PASS,
                    message=message,
                    duration_ms=duration_ms,
                    details=details,
                )
                
        except Exception as e:
            return CheckResult(
                name="Cache Performance",
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
    
    # Group checks by category
    core_checks = ["Database", "Memory/Embeddings", "Knowledge Store", "Conversation History", "File System"]
    ai_checks = ["Anthropic", "Mistral", "Moonshot", "Ollama"]
    system_checks = ["Tool Registry", "Scheduler", "Configuration"]
    perf_checks = ["Circuit Breakers", "Concurrency Controls", "Token Usage (24h)", "Cache Performance"]
    
    def format_check(check: CheckResult) -> str:
        if check.status == CheckStatus.PASS:
            icon = "✅"
        elif check.status == CheckStatus.WARN:
            icon = "⚠️"
        else:
            icon = "❌"
        
        if check.duration_ms < 1:
            duration_str = "<1ms"
        elif check.duration_ms < 1000:
            duration_str = f"{check.duration_ms:.0f}ms"
        else:
            duration_str = f"{check.duration_ms/1000:.1f}s"
        
        return f"{icon} *{check.name}* — {check.message} _({duration_str})_"
    
    checks_by_name = {c.name: c for c in result.checks}
    
    # Core Infrastructure
    lines.append("")
    lines.append("*Core Infrastructure*")
    for name in core_checks:
        if name in checks_by_name:
            lines.append(format_check(checks_by_name[name]))
    
    # AI Providers
    lines.append("")
    lines.append("*AI Providers*")
    for name in ai_checks:
        if name in checks_by_name:
            lines.append(format_check(checks_by_name[name]))
    
    # System Components
    lines.append("")
    lines.append("*System Components*")
    for name in system_checks:
        if name in checks_by_name:
            lines.append(format_check(checks_by_name[name]))
    
    # Performance & Resilience
    lines.append("")
    lines.append("*Performance & Resilience*")
    for name in perf_checks:
        if name in checks_by_name:
            lines.append(format_check(checks_by_name[name]))
    
    # Any remaining checks not in categories
    shown_names = set(core_checks + ai_checks + system_checks + perf_checks)
    remaining = [c for c in result.checks if c.name not in shown_names]
    if remaining:
        lines.append("")
        lines.append("*Other*")
        for check in remaining:
            lines.append(format_check(check))
    
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
