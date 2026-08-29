# --- circuit_breaker: prevents cascading failures from slow/unavailable APIs ---

import time
import logging

logger = logging.getLogger(__name__)


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open and rejecting requests."""
    pass


class CircuitBreaker:
    """
    Simple counter-based circuit breaker for async functions.

    States:
      - closed:    normal operation, requests pass through
      - open:      rejecting all requests (service is considered down)
      - half-open: testing with one request to see if service recovered

    Transitions:
      closed -> open:      after `failure_threshold` consecutive failures
      open -> half-open:   after `cooldown_seconds` elapse
      half-open -> closed: on success
      half-open -> open:   on failure
    """

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: int = 30):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.state = "closed"

    def record_success(self):
        """Reset failure tracking on success."""
        self.failure_count = 0
        self.state = "closed"

    def record_failure(self):
        """Track a failure and open the circuit if threshold is hit."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(
                f"Circuit breaker opened after {self.failure_count} consecutive failures. "
                f"Will retry in {self.cooldown_seconds}s."
            )

    async def call(self, func, *args, **kwargs):
        """
        Call an async function through the circuit breaker.
        Raises CircuitOpenError if the circuit is open.
        """
        if self.state == "open":
            elapsed = time.time() - self.last_failure_time
            if elapsed > self.cooldown_seconds:
                self.state = "half-open"
                logger.info("Circuit breaker transitioning to half-open — testing with one request")
            else:
                raise CircuitOpenError("Service temporarily unavailable (circuit breaker open)")

        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise
