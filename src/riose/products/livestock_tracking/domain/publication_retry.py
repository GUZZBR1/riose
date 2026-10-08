"""Small, bounded retry schedule for durable publication work."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class PublicationRetryPolicy:
    """Bound automatic retries while keeping ambiguous sends recoverable."""

    max_retries: int = 5
    initial_delay_s: float = 2.0
    max_delay_s: float = 300.0
    jitter_ratio: float = 0.2

    def __post_init__(self) -> None:
        if type(self.max_retries) is not int or not 1 <= self.max_retries <= 20:
            raise ValueError("max_retries must be between 1 and 20")
        if (type(self.initial_delay_s) not in (int, float)
                or not math.isfinite(self.initial_delay_s)
                or self.initial_delay_s <= 0):
            raise ValueError("initial_delay_s must be finite and positive")
        if (type(self.max_delay_s) not in (int, float)
                or not math.isfinite(self.max_delay_s)
                or self.max_delay_s < self.initial_delay_s):
            raise ValueError("max_delay_s must be finite and at least initial_delay_s")
        if (type(self.jitter_ratio) not in (int, float)
                or not math.isfinite(self.jitter_ratio)
                or not 0 <= self.jitter_ratio <= 0.5):
            raise ValueError("jitter_ratio must be between 0 and 0.5")

    def delay(self, retry_number: int, jitter_value: float) -> float:
        """Return exponential backoff with symmetric, bounded jitter."""
        if type(retry_number) is not int or retry_number < 1:
            raise ValueError("retry_number must be positive")
        if (type(jitter_value) not in (int, float)
                or not math.isfinite(jitter_value)
                or not 0 <= jitter_value <= 1):
            raise ValueError("jitter_value must be between 0 and 1")
        nominal = min(self.max_delay_s, self.initial_delay_s * (2 ** (retry_number - 1)))
        factor = 1 - self.jitter_ratio + 2 * self.jitter_ratio * jitter_value
        return min(self.max_delay_s, nominal * factor)
