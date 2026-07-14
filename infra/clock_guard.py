from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ClockCheck:
    skew_milliseconds: int
    acceptable: bool


class ClockGuard:
    def __init__(self, max_skew_milliseconds: int = 2000) -> None:
        if max_skew_milliseconds < 0:
            raise ValueError("max_skew_milliseconds must be non-negative")
        self.max_skew_milliseconds = max_skew_milliseconds

    def check(self, observed_at: datetime, reference_at: datetime) -> ClockCheck:
        skew = int(abs((observed_at - reference_at).total_seconds()) * 1000)
        return ClockCheck(skew, skew <= self.max_skew_milliseconds)

    def assert_acceptable(self, observed_at: datetime, reference_at: datetime) -> None:
        result = self.check(observed_at, reference_at)
        if not result.acceptable:
            raise RuntimeError(f"clock skew {result.skew_milliseconds}ms exceeds limit")
