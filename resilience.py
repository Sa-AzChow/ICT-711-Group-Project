from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic, sleep
from typing import Callable, TypeVar


T = TypeVar("T")


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    reset_timeout_s: float = 2.0
    _failures: int = 0
    _opened_at: float | None = None
    state: str = field(default="CLOSED", init=False)

    def allow_request(self) -> bool:
        if self.state == "OPEN":
            assert self._opened_at is not None
            if monotonic() - self._opened_at >= self.reset_timeout_s:
                self.state = "HALF_OPEN"
                return True
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self.state = "CLOSED"

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self.state = "OPEN"
            self._opened_at = monotonic()


def retry_with_backoff(func: Callable[[], T], attempts: int = 3, base_delay_s: float = 0.01) -> T:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return func()
        except Exception as exc:  # noqa: PERF203
            last_error = exc
            if attempt < attempts - 1:
                sleep(base_delay_s * (2**attempt))
    assert last_error is not None
    raise last_error

