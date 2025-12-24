"""
Circuit breaker pattern for downstream service protection.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from app.logging_config import get_logger
from app.metrics import CIRCUIT_BREAKER_STATE

logger = get_logger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = 0  # Normal operation
    OPEN = 1  # Failing, reject requests
    HALF_OPEN = 2  # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker for protecting against downstream failures.

    When failures exceed threshold, the circuit opens and rejects requests
    for a cooldown period. After cooldown, it enters half-open state to test
    if the downstream service has recovered.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_requests: int = 3,
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before trying again
            half_open_requests: Successful requests needed to close circuit
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_requests = half_open_requests

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._lock = asyncio.Lock()

        CIRCUIT_BREAKER_STATE.set(self._state.value)

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self._state == CircuitState.CLOSED

    async def can_execute(self) -> bool:
        """
        Check if a request can be executed.

        Returns:
            True if request should proceed, False if circuit is open
        """
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                # Check if recovery timeout has passed
                if self._last_failure_time:
                    elapsed = datetime.now(timezone.utc) - self._last_failure_time
                    if elapsed > timedelta(seconds=self.recovery_timeout):
                        self._state = CircuitState.HALF_OPEN
                        self._success_count = 0
                        CIRCUIT_BREAKER_STATE.set(self._state.value)
                        logger.info("circuit_breaker_half_open")
                        return True
                return False

            # Half-open: allow limited requests
            return True

    async def record_success(self) -> None:
        """Record a successful request."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.half_open_requests:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    CIRCUIT_BREAKER_STATE.set(self._state.value)
                    logger.info("circuit_breaker_closed")
            else:
                # Reset failure count on success in closed state
                self._failure_count = 0

    async def record_failure(self) -> None:
        """Record a failed request."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now(timezone.utc)

            if self._state == CircuitState.HALF_OPEN:
                # Immediately open on failure in half-open state
                self._state = CircuitState.OPEN
                CIRCUIT_BREAKER_STATE.set(self._state.value)
                logger.warning("circuit_breaker_reopened")

            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    CIRCUIT_BREAKER_STATE.set(self._state.value)
                    logger.warning(
                        "circuit_breaker_opened: failure_count=%d",
                        self._failure_count,
                    )


# Global circuit breaker instance
circuit_breaker = CircuitBreaker()
