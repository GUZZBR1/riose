"""Bounded reconciliation for an interrupted commitment publication attempt."""

from __future__ import annotations

import math
import re
from threading import Lock
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
MAX_RECOVERY_QUERY_BUDGET = 20
MAX_RECOVERY_ATTEMPTS = 10


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
    STALE_RECOVERY_SNAPSHOT = "STALE_RECOVERY_SNAPSHOT"


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
        if type(self.query_budget) is not int or not 1 <= self.query_budget <= MAX_RECOVERY_QUERY_BUDGET:
            raise ValueError(f"query_budget must be between 1 and {MAX_RECOVERY_QUERY_BUDGET}")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= MAX_RECOVERY_ATTEMPTS:
            raise ValueError(f"max_attempts must be between 1 and {MAX_RECOVERY_ATTEMPTS}")
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
class NonAcceptanceEvidence:
    """Source-bound external evidence; it is useful only with an injected verifier."""

    attempt_id: str
    proof: NonAcceptanceProofKind
    source: str
    evidence_reference: str
    evidence_status: EvidenceStatus

    def __post_init__(self) -> None:
        _validate_identifier(self.attempt_id, "attempt_id")
        if not isinstance(self.proof, NonAcceptanceProofKind):
            raise ValueError("proof must be an allowlisted non-acceptance kind")
        _validate_identifier(self.source, "source")
        _validate_identifier(self.evidence_reference, "evidence_reference")
        if not isinstance(self.evidence_status, EvidenceStatus):
            raise ValueError("evidence_status must be an EvidenceStatus")


@dataclass(frozen=True, slots=True)
class ProvenNonAcceptance:
    evidence: NonAcceptanceEvidence

    def __post_init__(self) -> None:
        if type(self.evidence) is not NonAcceptanceEvidence:
            raise ValueError("evidence must be source-bound NonAcceptanceEvidence")


RecoveryObservation: TypeAlias = (
    ObservedSubmitted | ObservedConfirmed | LookupNotFound | LookupUnavailable | ProvenNonAcceptance
)


class PublicationRecoveryPort(Protocol):
    """Injected lookup boundary; one call returns one typed observation."""

    def lookup(self, snapshot: PublicationSnapshot) -> RecoveryObservation: ...


class NonAcceptanceProofVerifier(Protocol):
    """Verify proof provenance and bind evidence to this exact interrupted attempt."""

    def verify(self, snapshot: PublicationSnapshot, evidence: NonAcceptanceEvidence) -> bool: ...


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    snapshot: RecoverySnapshot
    decision: RecoveryDecision
    reason: RecoveryReason


class PublicationRecoveryService:
    """Perform at most one injected lookup per call and redact adapter failures."""

    def __init__(
        self,
        lookup: PublicationRecoveryPort,
        proof_verifier: NonAcceptanceProofVerifier | None = None,
    ) -> None:
        self._lookup = lookup
        self._proof_verifier = proof_verifier
        self._queries_by_attempt: dict[tuple[str, str, str, str], int] = {}
        self._budgets_by_attempt: dict[tuple[str, str, str, str], tuple[int, int]] = {}
        self._query_lock = Lock()

    def reconcile(
        self,
        snapshot: RecoverySnapshot,
        *,
        now: float,
        authorize_retry: bool = False,
    ) -> RecoveryResult:
        if type(snapshot) is not RecoverySnapshot:
            raise ValueError("snapshot must be a RecoverySnapshot")
        if type(authorize_retry) is not bool:
            return RecoveryResult(snapshot, RecoveryDecision.INVALID, RecoveryReason.UNKNOWN_OBSERVATION)
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
        reservation_error = self._reserve_query(snapshot)
        if reservation_error is RecoveryReason.STALE_RECOVERY_SNAPSHOT:
            return RecoveryResult(snapshot, RecoveryDecision.UNAVAILABLE, reservation_error)
        if reservation_error is RecoveryReason.QUERY_BUDGET_EXHAUSTED:
            return RecoveryResult(
                snapshot,
                RecoveryDecision.UNAVAILABLE,
                reservation_error,
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
            return self._resolve_non_acceptance(updated, observation, authorize_retry=authorize_retry, now=float(now))
        if isinstance(observation, (ObservedSubmitted, ObservedConfirmed)):
            return self._resolve_observation(updated, observation)
        return RecoveryResult(updated, RecoveryDecision.UNAVAILABLE, RecoveryReason.UNKNOWN_OBSERVATION)

    def _resolve_non_acceptance(
        self,
        snapshot: RecoverySnapshot,
        proof: ProvenNonAcceptance,
        *,
        authorize_retry: bool,
        now: float,
    ) -> RecoveryResult:
        publication = snapshot.publication
        evidence = proof.evidence
        if (
            publication.attempt_id is None
            or evidence.attempt_id != publication.attempt_id
            or publication.lifecycle is not LifecycleState.QUEUED
            or publication.attempt_condition not in {AttemptCondition.IN_FLIGHT, AttemptCondition.UNKNOWN}
            or publication.reference is not None
        ):
            return RecoveryResult(snapshot, RecoveryDecision.INVALID, RecoveryReason.CORRELATION_MISMATCH)
        if (
            self._proof_verifier is None
            or evidence.evidence_status is not EvidenceStatus.VALIDATED
            or not _evidence_compatible(publication.evidence_status, evidence.evidence_status)
        ):
            return RecoveryResult(snapshot, RecoveryDecision.INVALID, RecoveryReason.EVIDENCE_PROVENANCE_MISMATCH)
        try:
            verified = self._proof_verifier.verify(publication, evidence)
        except Exception:
            verified = False
        if verified is not True:
            return RecoveryResult(snapshot, RecoveryDecision.INVALID, RecoveryReason.EVIDENCE_PROVENANCE_MISMATCH)
        if not authorize_retry:
            return RecoveryResult(snapshot, RecoveryDecision.WAIT, RecoveryReason.RETRY_NOT_AUTHORIZED)
        if publication.attempt_count >= snapshot.max_attempts:
            return RecoveryResult(snapshot, RecoveryDecision.WAIT, RecoveryReason.ATTEMPT_BUDGET_EXHAUSTED)
        # This privileged state change stays inside the recovery service after
        # the source-bound proof, verifier, explicit caller authorization, and
        # attempt budget have all been checked. The general FSM exposes no
        # signal that can release UNKNOWN/IN_FLIGHT attempts on its own.
        released = replace(
            publication,
            attempt_condition=AttemptCondition.READY,
            retry_at=None,
        )
        return RecoveryResult(
            replace(snapshot, publication=released),
            RecoveryDecision.SAFE_TO_RETRY,
            RecoveryReason.NON_ACCEPTANCE_PROVEN,
        )

    def _reserve_query(self, snapshot: RecoverySnapshot) -> RecoveryReason | None:
        publication = snapshot.publication
        key = (
            publication.commitment,
            publication.destination,
            publication.network,
            publication.attempt_id or "no-attempt",
        )
        budgets = (snapshot.query_budget, snapshot.max_attempts)
        with self._query_lock:
            previous_budgets = self._budgets_by_attempt.get(key)
            if previous_budgets is not None and previous_budgets != budgets:
                return RecoveryReason.STALE_RECOVERY_SNAPSHOT
            used = self._queries_by_attempt.get(key, snapshot.queries_used)
            if snapshot.queries_used < used:
                return RecoveryReason.STALE_RECOVERY_SNAPSHOT
            used = max(used, snapshot.queries_used)
            if used >= snapshot.query_budget:
                return RecoveryReason.QUERY_BUDGET_EXHAUSTED
            self._budgets_by_attempt[key] = budgets
            self._queries_by_attempt[key] = used + 1
        return None

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
