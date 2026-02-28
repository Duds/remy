"""Tests for the diagnostics runner, including new performance checks."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remy.diagnostics.runner import (
    CheckResult,
    CheckStatus,
    DiagnosticsResult,
    DiagnosticsRunner,
    format_diagnostics_output,
)


class TestCheckResult:
    """Tests for CheckResult dataclass."""

    def test_pass_result(self):
        result = CheckResult(
            name="Test",
            status=CheckStatus.PASS,
            message="All good",
            duration_ms=10.5,
        )
        assert result.status == CheckStatus.PASS
        assert result.duration_ms == 10.5

    def test_fail_result_with_details(self):
        result = CheckResult(
            name="Test",
            status=CheckStatus.FAIL,
            message="Something broke",
            duration_ms=100.0,
            details={"error_code": 500},
        )
        assert result.status == CheckStatus.FAIL
        assert result.details["error_code"] == 500


class TestDiagnosticsRunner:
    """Tests for DiagnosticsRunner."""

    @pytest.fixture
    def runner(self):
        return DiagnosticsRunner()

    @pytest.mark.asyncio
    async def test_run_all_returns_result(self, runner):
        result = await runner.run_all()
        assert isinstance(result, DiagnosticsResult)
        assert result.overall_status in [CheckStatus.PASS, CheckStatus.WARN, CheckStatus.FAIL]
        assert len(result.checks) > 0

    @pytest.mark.asyncio
    async def test_check_filesystem_passes_with_valid_dir(self, runner):
        result = await runner._check_filesystem()
        assert result.name == "File System"
        assert result.status in [CheckStatus.PASS, CheckStatus.WARN]

    @pytest.mark.asyncio
    async def test_check_config_warns_without_settings(self, runner):
        result = await runner._check_config()
        assert result.name == "Configuration"
        assert result.status == CheckStatus.WARN
        assert "not available" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_database_warns_without_db(self, runner):
        result = await runner._check_database()
        assert result.name == "Database"
        assert result.status == CheckStatus.WARN

    @pytest.mark.asyncio
    async def test_check_embeddings_warns_without_store(self, runner):
        result = await runner._check_embeddings()
        assert result.name == "Memory/Embeddings"
        assert result.status == CheckStatus.WARN


class TestCircuitBreakerCheck:
    """Tests for circuit breaker diagnostics."""

    @pytest.fixture
    def runner(self):
        return DiagnosticsRunner()

    @pytest.mark.asyncio
    async def test_no_circuits_registered(self, runner):
        with patch.dict("remy.utils.circuit_breaker._circuit_breakers", {}, clear=True):
            result = await runner._check_circuit_breakers()
            assert result.status == CheckStatus.PASS
            assert "no circuits" in result.message.lower()

    @pytest.mark.asyncio
    async def test_all_circuits_closed(self, runner):
        from remy.utils.circuit_breaker import CircuitBreaker, CircuitState

        mock_breaker = MagicMock(spec=CircuitBreaker)
        mock_breaker.state = CircuitState.CLOSED

        with patch.dict(
            "remy.utils.circuit_breaker._circuit_breakers",
            {"anthropic": mock_breaker},
            clear=True,
        ):
            result = await runner._check_circuit_breakers()
            assert result.status == CheckStatus.PASS
            assert "closed" in result.message.lower()

    @pytest.mark.asyncio
    async def test_circuit_open_fails(self, runner):
        from remy.utils.circuit_breaker import CircuitBreaker, CircuitState

        mock_breaker = MagicMock(spec=CircuitBreaker)
        mock_breaker.state = CircuitState.OPEN

        with patch.dict(
            "remy.utils.circuit_breaker._circuit_breakers",
            {"anthropic": mock_breaker},
            clear=True,
        ):
            result = await runner._check_circuit_breakers()
            assert result.status == CheckStatus.FAIL
            assert "OPEN" in result.message

    @pytest.mark.asyncio
    async def test_circuit_half_open_warns(self, runner):
        from remy.utils.circuit_breaker import CircuitBreaker, CircuitState

        mock_breaker = MagicMock(spec=CircuitBreaker)
        mock_breaker.state = CircuitState.HALF_OPEN

        with patch.dict(
            "remy.utils.circuit_breaker._circuit_breakers",
            {"anthropic": mock_breaker},
            clear=True,
        ):
            result = await runner._check_circuit_breakers()
            assert result.status == CheckStatus.WARN
            assert "HALF_OPEN" in result.message


class TestConcurrencyCheck:
    """Tests for concurrency control diagnostics."""

    @pytest.fixture
    def runner(self):
        return DiagnosticsRunner()

    @pytest.mark.asyncio
    async def test_idle_state(self, runner):
        import remy.bot.handlers.base as handlers_base
        
        with patch("remy.utils.concurrency._extraction_runner", None), \
             patch("remy.utils.concurrency._per_user_extraction_runner", None), \
             patch.object(handlers_base, "_user_active_requests", {}):
            result = await runner._check_concurrency()
            assert result.status == CheckStatus.PASS
            assert "idle" in result.message.lower()

    @pytest.mark.asyncio
    async def test_active_requests_shown(self, runner):
        from remy.utils.concurrency import BoundedTaskRunner
        import remy.bot.handlers.base as handlers_base

        mock_runner = MagicMock(spec=BoundedTaskRunner)
        mock_runner.active_count = 2
        mock_runner.total_count = 50

        with patch("remy.utils.concurrency._extraction_runner", mock_runner), \
             patch("remy.utils.concurrency._per_user_extraction_runner", None), \
             patch.object(handlers_base, "_user_active_requests", {123: 1}):
            result = await runner._check_concurrency()
            assert result.status == CheckStatus.PASS
            assert "active" in result.message.lower() or "extraction" in result.message.lower()


class TestTokenUsageCheck:
    """Tests for token usage diagnostics."""

    @pytest.fixture
    def runner(self):
        return DiagnosticsRunner()

    @pytest.mark.asyncio
    async def test_no_db_warns(self, runner):
        result = await runner._check_token_usage()
        assert result.status == CheckStatus.WARN
        assert "not configured" in result.message.lower()

    @pytest.mark.asyncio
    async def test_with_mock_db(self, runner):
        mock_conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(100, 50000, 10000, 5000, 20000, 500.0, 2))
        mock_conn.execute = AsyncMock(return_value=mock_cursor)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)

        mock_db = MagicMock()
        mock_db.get_connection = MagicMock(return_value=mock_conn)

        runner._db = mock_db
        result = await runner._check_token_usage()
        assert result.status in [CheckStatus.PASS, CheckStatus.WARN]
        assert "calls" in result.message.lower()


class TestCachePerformanceCheck:
    """Tests for cache performance diagnostics."""

    @pytest.fixture
    def runner(self):
        return DiagnosticsRunner()

    @pytest.mark.asyncio
    async def test_no_db_warns(self, runner):
        result = await runner._check_cache_performance()
        assert result.status == CheckStatus.WARN
        assert "not configured" in result.message.lower()


class TestFormatDiagnosticsOutput:
    """Tests for output formatting."""

    def test_pass_status_shows_green(self):
        result = DiagnosticsResult(
            checks=[
                CheckResult("Test", CheckStatus.PASS, "OK", 10.0),
            ],
            overall_status=CheckStatus.PASS,
            total_duration_ms=100.0,
            version="1.0.0",
            python_version="3.11.0",
            uptime_seconds=3600,
            last_restart=datetime.now(timezone.utc),
        )
        output = format_diagnostics_output(result)
        assert "🟢" in output
        assert "operational" in output.lower()

    def test_warn_status_shows_yellow(self):
        result = DiagnosticsResult(
            checks=[
                CheckResult("Test", CheckStatus.WARN, "Degraded", 10.0),
            ],
            overall_status=CheckStatus.WARN,
            total_duration_ms=100.0,
            version="1.0.0",
            python_version="3.11.0",
            uptime_seconds=3600,
            last_restart=datetime.now(timezone.utc),
        )
        output = format_diagnostics_output(result)
        assert "🟡" in output
        assert "degraded" in output.lower()

    def test_fail_status_shows_red(self):
        result = DiagnosticsResult(
            checks=[
                CheckResult("Test", CheckStatus.FAIL, "Down", 10.0),
            ],
            overall_status=CheckStatus.FAIL,
            total_duration_ms=100.0,
            version="1.0.0",
            python_version="3.11.0",
            uptime_seconds=3600,
            last_restart=datetime.now(timezone.utc),
        )
        output = format_diagnostics_output(result)
        assert "🔴" in output
        assert "impaired" in output.lower()

    def test_groups_checks_by_category(self):
        result = DiagnosticsResult(
            checks=[
                CheckResult("Database", CheckStatus.PASS, "OK", 10.0),
                CheckResult("Anthropic", CheckStatus.PASS, "OK", 10.0),
                CheckResult("Circuit Breakers", CheckStatus.PASS, "OK", 10.0),
            ],
            overall_status=CheckStatus.PASS,
            total_duration_ms=100.0,
            version="1.0.0",
            python_version="3.11.0",
            uptime_seconds=3600,
            last_restart=datetime.now(timezone.utc),
        )
        output = format_diagnostics_output(result)
        assert "Core Infrastructure" in output
        assert "AI Providers" in output
        assert "Performance & Resilience" in output

    def test_uptime_formatting_days(self):
        result = DiagnosticsResult(
            checks=[],
            overall_status=CheckStatus.PASS,
            total_duration_ms=100.0,
            version="1.0.0",
            python_version="3.11.0",
            uptime_seconds=90061,  # 1d 1h 1m
            last_restart=datetime.now(timezone.utc),
        )
        output = format_diagnostics_output(result)
        assert "1d" in output

    def test_uptime_formatting_hours(self):
        result = DiagnosticsResult(
            checks=[],
            overall_status=CheckStatus.PASS,
            total_duration_ms=100.0,
            version="1.0.0",
            python_version="3.11.0",
            uptime_seconds=3660,  # 1h 1m
            last_restart=datetime.now(timezone.utc),
        )
        output = format_diagnostics_output(result)
        assert "1h" in output
