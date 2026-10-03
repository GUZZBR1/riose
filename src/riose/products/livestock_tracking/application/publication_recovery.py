"""Bounded reconciliation for an interrupted commitment publication attempt."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol, TypeAlias

from ..domain.contracts import EvidenceStatus
from ..domain.publication import PublicationReason
from ..domain.publication_state import (
    AttemptCondition,
    LifecycleState,
    PublicationSnapshot,
)

_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z", re.ASCII)
_SCOPE_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z", re.ASCII)


class RecoveryDecision(StrEnum):
    WAIT = "WAIT"
    RESOLVED_SUBMITTED = "RESOLVED_SUBMITTED"
    RESOLVED_CONFIRMED = "RESOLVED_CONFIRMED"
    SAFE_TO_RETRY = "SAFE_TO_RETRY"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"


class RecoveryReason(StrEnum):
    PUBLICATION_OBSERVED = "PUBLICATION_OBSERVED"
    CONFIRMATION_OBSERVED = "CONFIRMATION_OBSERVED"
    NOT_FOUND_IN_LOOKUP = "NOT_FOUND_IN_LOOKUP"
    LOOKUP_UNAVAILABLE = "LOOKUP_UNAVAILABLE"
    LOOKUP_FAILED = "LOOKUP_FAILED"
    QUERY_BUDGET_EXHAUSTED = "QUERY_BUDGET_EXHAUSTED"
    NON_ACCEPTANCE_PROVEN = "NON_ACCEPTANCE_PROVEN"
    RETRY_NOT_AUTHORIZED = "RETRY_NOT_AUTHORIZED"
    ATTEMPT_BUDGET_EXHAUSTED = "ATTEMPT_BUDGET_EXHAUSTED"
    CORRELATION_MISMATCH = "CORRELATION_MISMATCH"
    EVIDENCE_PROVENANCE_MISMATCH = "EVIDENCE_PROVENANCE_MISMATCH"
    UNKNOWN_OBSERVATION = "UNKNOWN_OBSERVATION"


class NonAcceptanceProofKind(StrEnum):
    NOT_SENT = "NOT_SENT"
    REJECTED_BEFORE_ACCEPTANCE = "REJECTED_BEFORE_ACCEPTANCE"


@dataclass(frozen=True, slots=True)
class RecoverySnapshot:
    publication: PublicationSnapshot
    queries_used: int = 0
    query_budget: int = 3
    max_attempts: int = 3
    last_checked_at: float | None = None

    def __post_init__(self) -> None:
        if type(self.publication) is not PublicationSnapshot:
            raise ValueError("publication must be a PublicationSnapshot")
        if type(self.queries_used) is not int or self.queries_used < 0:
            raise ValueError("queries_used must be a non-negative integer")
        if type(self.query_budget) is not int or self.query_budget < 1:
            raise ValueError("query_budget must be a positive integer")
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if self.last_checked_at is not None and (
            isinstance(self.last_checked_at, bool)
            or not isinstance(self.last_checked_at, (int, float))
            or not math.isfinite(self.last_checked_at)
        ):
            raise ValueError("last_checked_at must be a finite timestamp")


@dataclass(frozen=True, slots=True)
class ObservedSubmitted:
    attempt_id: str
    commitment: str
    destination: str
    network: str
    reference: str
    evidence_status: EvidenceStatus

    def __post_init__(self) -> None:
        _validate_observed_identity(
            self.attempt_id,
            self.commitment,
            self.destination,
            self.network,
            self.reference,
            self.evidence_status,
        )


@dataclass(frozen=True, slots=True)
class ObservedConfirmed:
    attempt_id: str
    commitment: str
    destination: str
    network: str
    reference: str
    evidence_status: EvidenceStatus

    def __post_init__(self) -> None:
        _validate_observed_identity(
            self.attempt_id,
            self.commitment,
            self.destination,
            self.network,
            self.reference,
            self.evidence_status,
        )


@dataclass(frozen=True, slots=True)
class LookupNotFound:
    """No result from this lookup source; absence is not proof of non-acceptance."""


@dataclass(frozen=True, slots=True)
class LookupUnavailable:
    reason: PublicationReason = PublicationReason.DESTINATION_UNAVAILABLE

    def __post_init__(self) -> None:
        if not isinstance(self.reason, PublicationReason):
            raise ValueError("reason must be an allowlisted PublicationReason")


@dataclass(frozen=True, slots=True)
class ProvenNonAcceptance:
    attempt_id: str
    proof: NonAcceptanceProofKind
    caller_authorized_retry: bool

    def __post_init__(self) -> None:
        _validate_identifier(self.attempt_id, "attempt_id")
        if not isinstance(self.proof, NonAcceptanceProofKind):
            raise ValueError("proof must be an allowlisted non-acceptance kind")
        if type(self.caller_authorized_retry) is not bool:
            raise ValueError("caller_authorized_retry must be a boolean")


RecoveryObservation: TypeAlias = (
    ObservedSubmitted | ObservedConfirmed | LookupNotFound | LookupUnavailable | ProvenNonAcceptance
)


class PublicationRecoveryPort(Protocol):
    """Injected lookup boundary; one call returns one typed observation."""

    def lookup(self, snapshot: PublicationSnapshot) -> RecoveryObservation: ...


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    snapshot: RecoverySnapshot
    decision: RecoveryDecision
    reason: RecoveryReason


class PublicationRecoveryService:
    """Perform at most one injected lookup per call and redact adapter failures."""

    def __init__(self, lookup: PublicationRecoveryPort) -> None:
        self._lookup = lookup

    def reconcile(self, snapshot: RecoverySnapshot, *, now: float) -> RecoveryResult:
        if type(snapshot) is not RecoverySnapshot:
            raise ValueError("snapshot must be a RecoverySnapshot")
        if (
            isinstance(now, bool)
            or not isinstance(now, (int, float))
            or not math.isfinite(now)
        ):
            return RecoveryResult(snapshot, RecoveryDecision.INVALID, RecoveryReason.UNKNOWN_OBSERVATION)
        if snapshot.queries_used >= snapshot.query_budget:
            return RecoveryResult(
                snapshot,
                RecoveryDecision.UNAVAILABLE,
                RecoveryReason.QUERY_BUDGET_EXHAUSTED,
            )

        try:
            observation = self._lookup.lookup(snapshot.publication)
        except Exception:
            updated = replace(
                snapshot,
                queries_used=snapshot.queries_used + 1,
                last_checked_at=float(now),
            )
            return RecoveryResult(updated, RecoveryDecision.UNAVAILABLE, RecoveryReason.LOOKUP_FAILED)
        updated = replace(
            snapshot,
            queries_used=snapshot.queries_used + 1,
            last_checked_at=float(now),
        )

        if isinstance(observation, LookupNotFound):
            return RecoveryResult(updated, RecoveryDecision.WAIT, RecoveryReason.NOT_FOUND_IN_LOOKUP)
        if isinstance(observation, LookupUnavailable):
            return RecoveryResult(updated, RecoveryDecision.UNAVAILABLE, RecoveryReason.LOOKUP_UNAVAILABLE)
        if isinstance(observation, ProvenNonAcceptance):
            return self._resolve_non_acceptance(updated, observation)
        if isinstance(observation, (ObservedSubmitted, ObservedConfirmed)):
            return self._resolve_observation(updated, observation)
        return RecoveryResult(updated, RecoveryDecision.UNAVAILABLE, RecoveryReason.UNKNOWN_OBSERVATION)

    def _resolve_non_acceptance(
        self, snapshot: RecoverySnapshot, proof: ProvenNonAcceptance
    ) -> RecoveryResult:
        publication = snapshot.publication
        if (
            publication.attempt_id is None
            or proof.attempt_id != publication.attempt_id
            or not isinstance(proof.proof, NonAcceptanceProofKind)
            or type(proof.caller_authorized_retry) is not bool
            or publication.lifecycle in {LifecycleState.SUBMITTED, LifecycleState.CONFIRMED}
            or publication.reference is not None
        ):
            return RecoveryResult(snapshot, RecoveryDecision.INVALID, RecoveryReason.CORRELATION_MISMATCH)
        if not proof.caller_authorized_retry:
            return RecoveryResult(snapshot, RecoveryDecision.WAIT, RecoveryReason.RETRY_NOT_AUTHORIZED)
        if publication.attempt_count >= snapshot.max_attempts:
            return RecoveryResult(snapshot, RecoveryDecision.WAIT, RecoveryReason.ATTEMPT_BUDGET_EXHAUSTED)
        return RecoveryResult(snapshot, RecoveryDecision.SAFE_TO_RETRY, RecoveryReason.NON_ACCEPTANCE_PROVEN)

    def _resolve_observation(
        self,
        snapshot: RecoverySnapshot,
        observed: ObservedSubmitted | ObservedConfirmed,
    ) -> RecoveryResult:
        publication = snapshot.publication
        if (
            publication.attempt_id is None
            or observed.attempt_id != publication.attempt_id
            or observed.commitment != publication.commitment
            or observed.destination != publication.destination
            or observed.network != publication.network
            or (publication.reference is not None and observed.reference != publication.reference)
        ):
            return RecoveryResult(snapshot, RecoveryDecision.INVALID, RecoveryReason.CORRELATION_MISMATCH)
        if not _evidence_compatible(publication.evidence_status, observed.evidence_status):
            return RecoveryResult(
                snapshot,
                RecoveryDecision.INVALID,
                RecoveryReason.EVIDENCE_PROVENANCE_MISMATCH,
            )
        if isinstance(observed, ObservedSubmitted):
            if publication.lifecycle is LifecycleState.CONFIRMED:
                # A stale lower-level observation cannot downgrade prior confirmation.
                return RecoveryResult(
                    snapshot,
                    RecoveryDecision.RESOLVED_CONFIRMED,
                    RecoveryReason.CONFIRMATION_OBSERVED,
                )
            updated_publication = replace(
                publication,
                lifecycle=LifecycleState.SUBMITTED,
                attempt_condition=AttemptCondition.IN_FLIGHT,
                reference=observed.reference,
                retry_at=None,
                evidence_status=observed.evidence_status,
            )
            return RecoveryResult(
                replace(snapshot, publication=updated_publication),
                RecoveryDecision.RESOLVED_SUBMITTED,
                RecoveryReason.PUBLICATION_OBSERVED,
            )
        updated_publication = replace(
            publication,
            lifecycle=LifecycleState.CONFIRMED,
            attempt_condition=AttemptCondition.READY,
            reference=observed.reference,
            retry_at=None,
            evidence_status=observed.evidence_status,
        )
        return RecoveryResult(
            replace(snapshot, publication=updated_publication),
            RecoveryDecision.RESOLVED_CONFIRMED,
            RecoveryReason.CONFIRMATION_OBSERVED,
        )


def _evidence_compatible(current: EvidenceStatus, observed: EvidenceStatus) -> bool:
    return current is EvidenceStatus.FUTURE or current is observed


def _validate_observed_identity(
    attempt_id: str,
    commitment: str,
    destination: str,
    network: str,
    reference: str,
    evidence_status: EvidenceStatus,
) -> None:
    _validate_identifier(attempt_id, "attempt_id")
    _validate_identifier(reference, "reference")
    if type(commitment) is not str or _DIGEST_PATTERN.fullmatch(commitment) is None:
        raise ValueError("commitment must be a lowercase SHA-256 digest")
    for name, value in (("destination", destination), ("network", network)):
        if type(value) is not str or _SCOPE_PATTERN.fullmatch(value) is None:
            raise ValueError(f"{name} must be a lowercase technical identifier")
    if not isinstance(evidence_status, EvidenceStatus):
        raise ValueError("evidence_status must be an EvidenceStatus")


def _validate_identifier(value: str, name: str) -> None:
    if type(value) is not str or _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be an opaque technical identifier")
