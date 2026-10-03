"""Local, aggregate-only publication health snapshots."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class PublicationErrorCode(StrEnum):
    SIGNER_UNAVAILABLE = "SIGNER_UNAVAILABLE"
    RPC_UNAVAILABLE = "RPC_UNAVAILABLE"
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"
    DESTINATION_REJECTED = "DESTINATION_REJECTED"
    RETRY_BUDGET_EXHAUSTED = "RETRY_BUDGET_EXHAUSTED"


@dataclass(frozen=True, slots=True)
class LifecycleCounts:
    queued: int | None = None
    submitted: int | None = None
    confirmed: int | None = None

    def __post_init__(self) -> None:
        _validate_counts(self.queued, self.submitted, self.confirmed)


@dataclass(frozen=True, slots=True)
class AttemptConditionCounts:
    in_flight: int | None = None
    retry_wait: int | None = None
    unknown: int | None = None
    failed: int | None = None
    unavailable: int | None = None

    def __post_init__(self) -> None:
        _validate_counts(self.in_flight, self.retry_wait, self.unknown, self.failed, self.unavailable)


@dataclass(frozen=True, slots=True)
class PublicationObservabilitySnapshot:
    captured_at: float
    enabled: bool
    state_available: bool
    lifecycle: LifecycleCounts | None
    attempts: AttemptConditionCounts | None
    retries_total: int | None
    last_attempt_at: float | None = None
    last_observed_success_at: float | None = None
    last_error_code: PublicationErrorCode | None = None

    def __post_init__(self) -> None:
        _validate_time(self.captured_at, "captured_at")
        if type(self.enabled) is not bool or type(self.state_available) is not bool:
            raise ValueError("enabled and state_available must be booleans")
        if not self.state_available and any(
            value is not None
            for value in (self.lifecycle, self.attempts, self.retries_total)
        ):
            raise ValueError("unavailable state must remain unknown, not zero-filled")
        if self.lifecycle is not None and type(self.lifecycle) is not LifecycleCounts:
            raise ValueError("lifecycle must use LifecycleCounts")
        if self.attempts is not None and type(self.attempts) is not AttemptConditionCounts:
            raise ValueError("attempts must use AttemptConditionCounts")
        if self.retries_total is not None and (type(self.retries_total) is not int or self.retries_total < 0):
            raise ValueError("retries_total must be a non-negative integer or unknown")
        for name, value in (
            ("last_attempt_at", self.last_attempt_at),
            ("last_observed_success_at", self.last_observed_success_at),
        ):
            if value is not None:
                _validate_time(value, name)
        if self.last_error_code is not None and not isinstance(self.last_error_code, PublicationErrorCode):
            raise ValueError("last_error_code must be allowlisted")


class PublicationObservabilityService:
    """Build a snapshot without I/O, logging raw exceptions, or state changes."""

    def unavailable_snapshot(self, *, now: float, enabled: bool = False) -> PublicationObservabilitySnapshot:
        return PublicationObservabilitySnapshot(
            captured_at=now,
            enabled=enabled,
            state_available=False,
            lifecycle=None,
            attempts=None,
            retries_total=None,
        )


def _validate_counts(*values: int | None) -> None:
    for value in values:
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("counts must be non-negative integers or unknown")


def _validate_time(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite timestamp")
