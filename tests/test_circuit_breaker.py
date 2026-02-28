"""
Tests for the circuit breaker pattern implementation.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock

from remy.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    get_circuit_breaker,
    reset_all_circuits,
)


class TestCircuitBreaker:
    """Test circuit breaker state transitions."""

    @pytest.fixture
    def breaker(self):
        """Create a fresh circuit breaker for each test."""
        return CircuitBreaker(
            name="test",
            failure_threshold=3,
            recovery_timeout=1.0,
            half_open_max_calls=2,
        )

    @pytest.mark.asyncio
    async def test_initial_state_closed(self, breaker):
        """Circuit starts in closed state."""
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed
        assert not breaker.is_open

    @pytest.mark.asyncio
    async def test_successful_call_stays_closed(self, breaker):
        """Successful calls keep circuit closed."""
        async def success():
            return "ok"
        
        result = await breaker.call(success())
        assert result == "ok"
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failures_open_circuit(self, breaker):
        """Enough failures open the circuit."""
        async def fail():
            raise ValueError("boom")
        
        # Record failures up to threshold
        for i in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail())
        
        assert breaker.state == CircuitState.OPEN
        assert breaker.is_open

    @pytest.mark.asyncio
    async def test_open_circuit_blocks_calls(self, breaker):
        """Open circuit raises CircuitOpenError."""
        # Force open state
        async def fail():
            raise ValueError("boom")
        
        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail())
        
        # Now calls should be blocked - circuit raises before coroutine is created
        success_called = False
        
        async def success():
            nonlocal success_called
            success_called = True
            return "ok"
        
        with pytest.raises(CircuitOpenError) as exc_info:
            # The circuit should raise before we even await the coroutine
            coro = success()
            try:
                await breaker.call(coro)
            finally:
                # Ensure coroutine is closed to avoid warning
                coro.close()
        
        assert exc_info.value.name == "test"
        assert exc_info.value.retry_after > 0
        assert not success_called  # Verify the function was never actually called

    @pytest.mark.asyncio
    async def test_circuit_transitions_to_half_open(self, breaker):
        """Circuit transitions to half-open after recovery timeout."""
        async def fail():
            raise ValueError("boom")
        
        # Open the circuit
        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail())
        
        assert breaker.state == CircuitState.OPEN
        
        # Wait for recovery timeout
        await asyncio.sleep(1.1)
        
        # Check state transition
        await breaker._check_state_transition()
        assert breaker.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_half_open_success_closes_circuit(self, breaker):
        """Successful call in half-open state closes circuit."""
        # Manually set to half-open
        breaker._state = CircuitState.HALF_OPEN
        
        async def success():
            return "ok"
        
        result = await breaker.call(success())
        assert result == "ok"
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens_circuit(self, breaker):
        """Failure in half-open state reopens circuit."""
        # Manually set to half-open
        breaker._state = CircuitState.HALF_OPEN
        
        async def fail():
            raise ValueError("boom")
        
        with pytest.raises(ValueError):
            await breaker.call(fail())
        
        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_reset_clears_state(self, breaker):
        """Manual reset returns circuit to closed state."""
        # Open the circuit
        async def fail():
            raise ValueError("boom")
        
        for _ in range(3):
            with pytest.raises(ValueError):
                await breaker.call(fail())
        
        assert breaker.state == CircuitState.OPEN
        
        # Reset
        breaker.reset()
        assert breaker.state == CircuitState.CLOSED
        assert breaker._failure_count == 0


class TestCircuitBreakerGlobals:
    """Test global circuit breaker management."""

    def test_get_circuit_breaker_creates_new(self):
        """get_circuit_breaker creates new breaker if not exists."""
        reset_all_circuits()
        
        breaker = get_circuit_breaker("new_service")
        assert breaker.name == "new_service"

    def test_get_circuit_breaker_returns_same(self):
        """get_circuit_breaker returns same instance for same name."""
        reset_all_circuits()
        
        breaker1 = get_circuit_breaker("same_service")
        breaker2 = get_circuit_breaker("same_service")
        assert breaker1 is breaker2

    def test_reset_all_circuits(self):
        """reset_all_circuits resets all breakers."""
        reset_all_circuits()
        
        breaker = get_circuit_breaker("reset_test")
        breaker._state = CircuitState.OPEN
        
        reset_all_circuits()
        
        # Get same breaker - should be reset
        breaker = get_circuit_breaker("reset_test")
        assert breaker.state == CircuitState.CLOSED
