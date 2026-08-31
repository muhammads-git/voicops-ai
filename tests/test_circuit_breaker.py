# tests/test_circuit_breaker.py — tests for the circuit breaker state machine

import time
import pytest
from unittest.mock import AsyncMock
from app.services.circuit_breaker import CircuitBreaker, CircuitOpenError


class TestCircuitBreakerInit:
    def test_default_state_is_closed(self):
        cb = CircuitBreaker()
        assert cb.state == "closed"
        assert cb.failure_count == 0

    def test_custom_threshold_and_cooldown(self):
        cb = CircuitBreaker(failure_threshold=10, cooldown_seconds=60)
        assert cb.failure_threshold == 10
        assert cb.cooldown_seconds == 60


class TestRecordSuccess:
    def test_resets_failure_count(self):
        cb = CircuitBreaker()
        cb.failure_count = 3
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == "closed"

    def test_resets_state_from_half_open(self):
        cb = CircuitBreaker()
        cb.state = "half-open"
        cb.record_success()
        assert cb.state == "closed"


class TestRecordFailure:
    def test_increments_failure_count(self):
        cb = CircuitBreaker(failure_threshold=5)
        cb.record_failure()
        assert cb.failure_count == 1
        assert cb.state == "closed"

    def test_opens_circuit_at_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == "open"
        assert cb.failure_count == 3

    def test_does_not_open_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.state == "closed"

    def test_records_last_failure_time(self):
        cb = CircuitBreaker()
        before = time.time()
        cb.record_failure()
        after = time.time()
        assert before <= cb.last_failure_time <= after


class TestCircuitBreakerCall:
    @pytest.mark.asyncio
    async def test_successful_call_returns_result(self):
        cb = CircuitBreaker()
        func = AsyncMock(return_value="hello")
        result = await cb.call(func, "arg1", kwarg1="val")
        assert result == "hello"
        func.assert_called_once_with("arg1", kwarg1="val")
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_failed_call_increments_failure(self):
        cb = CircuitBreaker(failure_threshold=5)
        func = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            await cb.call(func)
        assert cb.failure_count == 1

    @pytest.mark.asyncio
    async def test_raises_circuit_open_when_open(self):
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=999)
        # Trip the circuit
        func = AsyncMock(side_effect=ValueError("fail"))
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(func)
        assert cb.state == "open"

        # Next call should get CircuitOpenError
        with pytest.raises(CircuitOpenError):
            await cb.call(func)

    @pytest.mark.asyncio
    async def test_half_open_after_cooldown(self):
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0)
        func = AsyncMock(side_effect=ValueError("fail"))
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(func)
        assert cb.state == "open"

        # cooldown_seconds=0 so it immediately transitions to half-open
        func = AsyncMock(return_value="recovered")
        result = await cb.call(func)
        assert result == "recovered"
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_half_open_failure_returns_to_open(self):
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0)
        func = AsyncMock(side_effect=ValueError("fail"))
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(func)
        assert cb.state == "open"

        # Half-open attempt that fails
        func2 = AsyncMock(side_effect=ValueError("still failing"))
        with pytest.raises(ValueError):
            await cb.call(func2)
        assert cb.state == "open"
        assert cb.failure_count == 3

    @pytest.mark.asyncio
    async def test_success_after_recovery_resets_count(self):
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0)
        fail_func = AsyncMock(side_effect=ValueError("fail"))
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(fail_func)

        ok_func = AsyncMock(return_value="ok")
        result = await cb.call(ok_func)
        assert result == "ok"
        assert cb.failure_count == 0
        assert cb.state == "closed"
