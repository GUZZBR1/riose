"""Pure state-transition policy for one commitment publication intention."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TypeAlias

from .contracts import EvidenceStatus
from .publication import PublicationStatus


_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z", re.ASCII)
_SCOPE_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z", re.ASCII)


class LifecycleState(StrEnum):
    QUEUED = "QUEUED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"


class AttemptCondition(StrEnum):
    READY = "READY"
    IN_FLIGHT = "IN_FLIGHT"
    RETRY_WAIT = "RETRY_WAIT"
    UNKNOWN = "UNKNOWN"
    FAILED = "FAILED"


class TransitionDecision(StrEnum):
    APPLIED = "APPLIED"
    NOOP = "NOOP"
    REJECTED = "REJECTED"


class TransitionReason(StrEnum):
    ACCEPTED = "ACCEPTED"
    CONFIRMATION_OBSERVED = "CONFIRMATION_OBSERVED"
    PRE_ACCEPTANCE_FAILURE = "PRE_ACCEPTANCE_FAILURE"
    WAITING_FOR_RETRY_DEADLINE = "WAITING_FOR_RETRY_DEADLINE"
    RETRY_READY = "RETRY_READY"
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"
    REJECTION_OBSERVED = "REJECTION_OBSERVED"
    DUPLICATE_SIGNAL = "DUPLICATE_SIGNAL"
    STALE_ATTEMPT = "STALE_ATTEMPT"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    EVIDENCE_PROVENANCE_MISMATCH = "EVIDENCE_PROVENANCE_MISMATCH"
    RETRY_BUDGET_EXHAUSTED = "RETRY_BUDGET_EXHAUSTED"
    INVALID_SIGNAL = "INVALID_SIGNAL"


@dataclass(frozen=True, slots=True)
class PublicationPolicy:
    max_attempts: int = 3
    retry_delay_s: float = 30.0

    def __post_init__(self) -> None:
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if (
            isinstance(self.retry_delay_s, bool)
            or not isinstance(self.retry_delay_s, (int, float))
            or not math.isfinite(self.retry_delay_s)
            or self.retry_delay_s < 0
        ):
            raise ValueError("retry_delay_s must be a finite non-negative number")


@dataclass(frozen=True, slots=True)
class PublicationSnapshot:
    commitment: str
    destination: str
    network: str
    lifecycle: LifecycleState = LifecycleState.QUEUED
    attempt_condition: AttemptCondition = AttemptCondition.READY
    attempt_id: str | None = None
    attempt_count: int = 0
    reference: str | None = None
    retry_at: float | None = None
    evidence_status: EvidenceStatus = EvidenceStatus.FUTURE

    def __post_init__(self) -> None:
        if type(self.commitment) is not str or _DIGEST_PATTERN.fullmatch(self.commitment) is None:
            raise ValueError("commitment must be a lowercase SHA-256 digest")
        for name, value in (("destination", self.destination), ("network", self.network)):
            if type(value) is not str or _SCOPE_PATTERN.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase technical identifier")
        if not isinstance(self.lifecycle, LifecycleState):
            raise ValueError("lifecycle must be a LifecycleState")
        if not isinstance(self.attempt_condition, AttemptCondition):
            raise ValueError("attempt_condition must be an AttemptCondition")
        if type(self.attempt_count) is not int or self.attempt_count < 0:
            raise ValueError("attempt_count must be a non-negative integer")
        if self.attempt_id is not None:
            _validate_identifier(self.attempt_id, "attempt_id")
        if self.reference is not None:
            _validate_identifier(self.reference, "reference")
        if self.retry_at is not None:
            _validate_time(self.retry_at, "retry_at")
        if not isinstance(self.evidence_status, EvidenceStatus):
            raise ValueError("evidence_status must be an EvidenceStatus")
        if self.attempt_condition in {AttemptCondition.IN_FLIGHT, AttemptCondition.UNKNOWN} and self.attempt_id is None:
            raise ValueError("active or unknown attempt requires attempt_id")
        if self.attempt_condition is AttemptCondition.RETRY_WAIT and self.retry_at is None:
            raise ValueError("RETRY_WAIT requires retry_at")
        if self.lifecycle in {LifecycleState.SUBMITTED, LifecycleState.CONFIRMED} and self.reference is None:
            raise ValueError("submitted lifecycle requires a correlated reference")
        if self.lifecycle is LifecycleState.CONFIRMED and self.attempt_condition is not AttemptCondition.READY:
            raise ValueError("confirmed lifecycle is terminal for this policy version")


@dataclass(frozen=True, slots=True)
class BeginAttempt:
    attempt_id: str
    destination: str
    network: str


@dataclass(frozen=True, slots=True)
class SubmissionAccepted:
    attempt_id: str
    destination: str
    network: str
    reference: str
    evidence_status: EvidenceStatus


@dataclass(frozen=True, slots=True)
class SubmissionUnknown:
    attempt_id: str
    destination: str
    network: str
    reference: str | None = None


@dataclass(frozen=True, slots=True)
class PreAcceptanceFailure:
    """Explicit evidence that this attempt failed before destination acceptance."""

    attempt_id: str
    destination: str
    network: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class RetryDue:
    previous_attempt_id: str
    next_attempt_id: str
    destination: str
    network: str


@dataclass(frozen=True, slots=True)
class ConfirmationObserved:
    attempt_id: str
    destination: str
    network: str
    reference: str
    evidence_status: EvidenceStatus


@dataclass(frozen=True, slots=True)
class PublicationRejected:
    """Explicit post-submission rejection observation, not a pre-acceptance error."""

    attempt_id: str
    destination: str
    network: str
    reference: str
    evidence_status: EvidenceStatus


PublicationSignal: TypeAlias = (
    BeginAttempt
    | SubmissionAccepted
    | SubmissionUnknown
    | PreAcceptanceFailure
    | RetryDue
    | ConfirmationObserved
    | PublicationRejected
)


@dataclass(frozen=True, slots=True)
class TransitionResult:
    snapshot: PublicationSnapshot
    decision: TransitionDecision
    reason: TransitionReason


def transition(
    snapshot: PublicationSnapshot,
    signal: PublicationSignal,
    policy: PublicationPolicy,
    now: float,
) -> TransitionResult:
    """Apply one typed signal without I/O, mutation, clock reads, or persistence."""

    if type(snapshot) is not PublicationSnapshot or type(policy) is not PublicationPolicy:
        return _rejected(snapshot, TransitionReason.INVALID_SIGNAL)
    try:
        _validate_time(now, "now")
        _validate_signal(signal)
    except (TypeError, ValueError):
        return _rejected(snapshot, TransitionReason.INVALID_SIGNAL)

    if isinstance(signal, (BeginAttempt, SubmissionAccepted, SubmissionUnknown, PreAcceptanceFailure, ConfirmationObserved, PublicationRejected)):
        if signal.destination != snapshot.destination or signal.network != snapshot.network:
            return _rejected(snapshot, TransitionReason.SCOPE_MISMATCH)
        if signal.attempt_id != snapshot.attempt_id and not isinstance(signal, BeginAttempt):
            return _rejected(snapshot, TransitionReason.STALE_ATTEMPT)
    elif isinstance(signal, RetryDue):
        if signal.destination != snapshot.destination or signal.network != snapshot.network:
            return _rejected(snapshot, TransitionReason.SCOPE_MISMATCH)
        if signal.previous_attempt_id != snapshot.attempt_id:
            return _rejected(snapshot, TransitionReason.STALE_ATTEMPT)

    if isinstance(signal, BeginAttempt):
        if snapshot.lifecycle is not LifecycleState.QUEUED or snapshot.attempt_condition is not AttemptCondition.READY:
            return _rejected(snapshot, TransitionReason.INVALID_TRANSITION)
        if snapshot.attempt_count >= policy.max_attempts:
            return _rejected(snapshot, TransitionReason.RETRY_BUDGET_EXHAUSTED)
        updated = replace(
            snapshot,
            attempt_id=signal.attempt_id,
            attempt_count=snapshot.attempt_count + 1,
            attempt_condition=AttemptCondition.IN_FLIGHT,
            retry_at=None,
        )
        return _applied(updated, TransitionReason.ACCEPTED)

    if isinstance(signal, SubmissionAccepted):
        if snapshot.lifecycle is LifecycleState.SUBMITTED:
            if snapshot.reference == signal.reference:
                return _noop(snapshot, TransitionReason.DUPLICATE_SIGNAL)
            return _rejected(snapshot, TransitionReason.STALE_ATTEMPT)
        if snapshot.lifecycle is not LifecycleState.QUEUED or snapshot.attempt_condition not in {
            AttemptCondition.IN_FLIGHT,
            AttemptCondition.UNKNOWN,
        }:
            return _rejected(snapshot, TransitionReason.INVALID_TRANSITION)
        if snapshot.reference is not None and snapshot.reference != signal.reference:
            return _rejected(snapshot, TransitionReason.STALE_ATTEMPT)
        if not _evidence_compatible(snapshot.evidence_status, signal.evidence_status):
            return _rejected(snapshot, TransitionReason.EVIDENCE_PROVENANCE_MISMATCH)
        updated = replace(
            snapshot,
            lifecycle=LifecycleState.SUBMITTED,
            attempt_condition=AttemptCondition.IN_FLIGHT,
            reference=signal.reference,
            retry_at=None,
            evidence_status=signal.evidence_status,
        )
        return _applied(updated, TransitionReason.ACCEPTED)

    if isinstance(signal, SubmissionUnknown):
        if snapshot.lifecycle is LifecycleState.CONFIRMED:
            return _rejected(snapshot, TransitionReason.INVALID_TRANSITION)
        if snapshot.attempt_condition not in {AttemptCondition.IN_FLIGHT, AttemptCondition.UNKNOWN}:
            return _rejected(snapshot, TransitionReason.INVALID_TRANSITION)
        if signal.reference is not None:
            _validate_identifier(signal.reference, "reference")
            if snapshot.reference is not None and snapshot.reference != signal.reference:
                return _rejected(snapshot, TransitionReason.STALE_ATTEMPT)
        updated = replace(
            snapshot,
            attempt_condition=AttemptCondition.UNKNOWN,
            reference=signal.reference or snapshot.reference,
            retry_at=None,
        )
        return _applied(updated, TransitionReason.SUBMISSION_UNKNOWN)

    if isinstance(signal, PreAcceptanceFailure):
        if snapshot.lifecycle is not LifecycleState.QUEUED or snapshot.attempt_condition is not AttemptCondition.IN_FLIGHT:
            return _rejected(snapshot, TransitionReason.INVALID_TRANSITION)
        if type(signal.retryable) is not bool:
            return _rejected(snapshot, TransitionReason.INVALID_SIGNAL)
        if signal.retryable and snapshot.attempt_count < policy.max_attempts:
            updated = replace(
                snapshot,
                attempt_condition=AttemptCondition.RETRY_WAIT,
                retry_at=float(now) + float(policy.retry_delay_s),
            )
            return _applied(updated, TransitionReason.PRE_ACCEPTANCE_FAILURE)
        updated = replace(snapshot, attempt_condition=AttemptCondition.FAILED, retry_at=None)
        reason = (
            TransitionReason.RETRY_BUDGET_EXHAUSTED
            if signal.retryable
            else TransitionReason.PRE_ACCEPTANCE_FAILURE
        )
        return _applied(updated, reason)

    if isinstance(signal, RetryDue):
        if snapshot.attempt_condition is not AttemptCondition.RETRY_WAIT or snapshot.retry_at is None:
            return _rejected(snapshot, TransitionReason.INVALID_TRANSITION)
        if float(now) < snapshot.retry_at:
            return _noop(snapshot, TransitionReason.WAITING_FOR_RETRY_DEADLINE)
        if snapshot.attempt_count >= policy.max_attempts:
            return _rejected(snapshot, TransitionReason.RETRY_BUDGET_EXHAUSTED)
        updated = replace(
            snapshot,
            attempt_id=signal.next_attempt_id,
            attempt_condition=AttemptCondition.READY,
            reference=None,
            retry_at=None,
        )
        return _applied(updated, TransitionReason.RETRY_READY)

    if isinstance(signal, ConfirmationObserved):
        if snapshot.lifecycle is LifecycleState.CONFIRMED and snapshot.reference == signal.reference:
            return _noop(snapshot, TransitionReason.DUPLICATE_SIGNAL)
        if snapshot.lifecycle is not LifecycleState.SUBMITTED or snapshot.attempt_condition not in {
            AttemptCondition.IN_FLIGHT,
            AttemptCondition.UNKNOWN,
        }:
            return _rejected(snapshot, TransitionReason.INVALID_TRANSITION)
        if snapshot.reference != signal.reference:
            return _rejected(snapshot, TransitionReason.STALE_ATTEMPT)
        if not _evidence_compatible(snapshot.evidence_status, signal.evidence_status):
            return _rejected(snapshot, TransitionReason.EVIDENCE_PROVENANCE_MISMATCH)
        updated = replace(
            snapshot,
            lifecycle=LifecycleState.CONFIRMED,
            attempt_condition=AttemptCondition.READY,
            retry_at=None,
            evidence_status=signal.evidence_status,
        )
        return _applied(updated, TransitionReason.CONFIRMATION_OBSERVED)

    if isinstance(signal, PublicationRejected):
        if snapshot.lifecycle is not LifecycleState.SUBMITTED or snapshot.attempt_condition not in {
            AttemptCondition.IN_FLIGHT,
            AttemptCondition.UNKNOWN,
        }:
            return _rejected(snapshot, TransitionReason.INVALID_TRANSITION)
        if snapshot.reference != signal.reference:
            return _rejected(snapshot, TransitionReason.STALE_ATTEMPT)
        if not _evidence_compatible(snapshot.evidence_status, signal.evidence_status):
            return _rejected(snapshot, TransitionReason.EVIDENCE_PROVENANCE_MISMATCH)
        updated = replace(snapshot, attempt_condition=AttemptCondition.FAILED, retry_at=None)
        return _applied(updated, TransitionReason.REJECTION_OBSERVED)

    return _rejected(snapshot, TransitionReason.INVALID_SIGNAL)


def _validate_signal(signal: object) -> None:
    if isinstance(signal, BeginAttempt):
        _validate_identifier(signal.attempt_id, "attempt_id")
    elif isinstance(signal, SubmissionAccepted):
        _validate_identifier(signal.attempt_id, "attempt_id")
        _validate_identifier(signal.reference, "reference")
        if not isinstance(signal.evidence_status, EvidenceStatus):
            raise ValueError("invalid evidence status")
    elif isinstance(signal, SubmissionUnknown):
        _validate_identifier(signal.attempt_id, "attempt_id")
        if signal.reference is not None:
            _validate_identifier(signal.reference, "reference")
    elif isinstance(signal, PreAcceptanceFailure):
        _validate_identifier(signal.attempt_id, "attempt_id")
        if type(signal.retryable) is not bool:
            raise ValueError("retryable must be a boolean")
    elif isinstance(signal, RetryDue):
        _validate_identifier(signal.previous_attempt_id, "previous_attempt_id")
        _validate_identifier(signal.next_attempt_id, "next_attempt_id")
        if signal.previous_attempt_id == signal.next_attempt_id:
            raise ValueError("retry requires a new attempt id")
    elif isinstance(signal, ConfirmationObserved):
        _validate_identifier(signal.attempt_id, "attempt_id")
        _validate_identifier(signal.reference, "reference")
        if not isinstance(signal.evidence_status, EvidenceStatus):
            raise ValueError("invalid evidence status")
    elif isinstance(signal, PublicationRejected):
        _validate_identifier(signal.attempt_id, "attempt_id")
        _validate_identifier(signal.reference, "reference")
        if not isinstance(signal.evidence_status, EvidenceStatus):
            raise ValueError("invalid evidence status")
    else:
        raise ValueError("unknown signal type")

    for name in ("destination", "network"):
        value = getattr(signal, name)
        if type(value) is not str or _SCOPE_PATTERN.fullmatch(value) is None:
            raise ValueError(f"{name} must be a lowercase technical identifier")


def _validate_identifier(value: str, name: str) -> None:
    if type(value) is not str or _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be an opaque technical identifier")


def _validate_time(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite timestamp")


def _evidence_compatible(current: EvidenceStatus, observed: EvidenceStatus) -> bool:
    """Do not let a later signal relabel the provenance of an existing attempt."""

    return current is EvidenceStatus.FUTURE or current is observed


def _applied(snapshot: PublicationSnapshot, reason: TransitionReason) -> TransitionResult:
    return TransitionResult(snapshot, TransitionDecision.APPLIED, reason)


def _noop(snapshot: PublicationSnapshot, reason: TransitionReason) -> TransitionResult:
    return TransitionResult(snapshot, TransitionDecision.NOOP, reason)


def _rejected(snapshot: PublicationSnapshot, reason: TransitionReason) -> TransitionResult:
    return TransitionResult(snapshot, TransitionDecision.REJECTED, reason)
