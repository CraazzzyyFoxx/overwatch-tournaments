"""Lightweight async circuit breaker implementation.

The circuit breaker prevents cascading failures by temporarily blocking requests
to a failing service, allowing it time to recover.

State transitions:
- CLOSED -> OPEN: After failure_threshold consecutive failures
- OPEN -> HALF_OPEN: After recovery_timeout seconds
- HALF_OPEN -> CLOSED: After successful probe
- HALF_OPEN -> OPEN: After failed probe
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TypeVar

from loguru import logger

T = TypeVar("T")


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Blocking requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open."""

    def __init__(self, message: str = "Circuit breaker is open"):
        self.message = message
        super().__init__(self.message)


@dataclass
class CircuitBreaker:
    """Async circuit breaker for protecting against cascading failures.

    Example:
        ```python
        breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)

        try:
            result = await breaker.call(lambda: some_async_function())
        except CircuitBreakerOpen:
            # Handle circuit open case
            pass
        ```
    """

    failure_threshold: int = 5
    """Number of consecutive failures before opening the circuit."""

    recovery_timeout: float = 30.0
    """Seconds to wait in OPEN state before attempting recovery."""

    half_open_max_calls: int = 1
    """Maximum number of concurrent calls allowed in HALF_OPEN state."""

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: float | None = field(default=None, init=False)
    _half_open_calls: int = field(default=0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    @property
    def state(self) -> CircuitState:
        """Current state of the circuit breaker."""
        return self._state

    async def call(self, factory: Callable[[], Awaitable[T]]) -> T:
        """Execute an async operation through the circuit breaker.

        Args:
            factory: A zero-argument callable that returns the awaitable to run.
                A factory (rather than a ready coroutine) is required so nothing
                is created when the circuit is open — otherwise the un-awaited
                coroutine would leak and emit ``RuntimeWarning``.

        Returns:
            The result of the awaitable produced by ``factory``.

        Raises:
            CircuitBreakerOpen: If the circuit is open
            Exception: Any exception raised by the awaited operation
        """
        async with self._lock:
            # Check if we should transition from OPEN to HALF_OPEN
            if self._state == CircuitState.OPEN:
                if self._should_attempt_recovery():
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    logger.info(
                        "Circuit breaker entering half-open state, probing recovery",
                        state="half_open",
                        previous_state="open",
                    )
                else:
                    raise CircuitBreakerOpen()

            # Limit concurrent calls in HALF_OPEN state
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerOpen("Circuit breaker is in half-open state, max probes reached")
                self._half_open_calls += 1

        # Build and execute the operation outside the lock. The factory is only
        # invoked once the state check above has passed, so no coroutine is
        # created (and left un-awaited) when the circuit is open.
        try:
            result = await factory()
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise e

    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if self._last_failure_time is None:
            return True
        return time.time() - self._last_failure_time >= self.recovery_timeout

    async def _on_success(self) -> None:
        """Handle successful operation."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                # Recovery successful, close the circuit
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._half_open_calls = 0
                logger.info(
                    "Circuit breaker closed after successful probe",
                    state="closed",
                    previous_state="half_open",
                )
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0

    async def _on_failure(self) -> None:
        """Handle failed operation."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # Recovery failed, reopen the circuit
                self._state = CircuitState.OPEN
                self._half_open_calls = 0
                logger.warning(
                    "Circuit breaker reopened after failed probe",
                    state="open",
                    previous_state="half_open",
                )
            elif self._state == CircuitState.CLOSED:
                # Check if we should open the circuit
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    logger.error(
                        "Circuit breaker opened after consecutive failures",
                        state="open",
                        previous_state="closed",
                        failure_count=self._failure_count,
                        failure_threshold=self.failure_threshold,
                    )

    async def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED state."""
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = None
            self._half_open_calls = 0
