"""Deterministic, volatile blockchain adapter fake for tests and demos only."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from ..domain.contracts import EvidenceStatus
from ..domain.publication import (
    AdapterCapabilities,
    CommitmentPublicationRequest,
    ConfirmationResult,
    PublicationPort,
    PublicationReason,
    PublicationStatus,
    SubmissionResult,
)


class FakeSubmitOutcome(StrEnum):
    """Scripted fake response; ``CONFIRMED`` confirms only on a later query."""

    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    UNAVAILABLE = "UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class FakeSubmissionRecord:
    """Minimized call record; never retains a request or raw payload."""

    commitment: str
    destination: str
    network: str
    reference: str | None
    status: PublicationStatus


@dataclass(frozen=True, slots=True)
class _FakeObservation:
    commitment: str
    destination: str
    network: str
    reference: str
    status: PublicationStatus


class FakeBlockchainAdapter(PublicationPort):
    """Offline fake implementing the canonical port with ``SIMULATED`` evidence.

    Each submit consumes one configured outcome. If the script is exhausted,
    later calls become UNKNOWN rather than silently succeeding. A scripted
    CONFIRMED outcome still returns SUBMITTED from submit; only an explicit
    follow-up query can report the simulated confirmation.
    """

    def __init__(self, submit_outcomes: Iterable[FakeSubmitOutcome]) -> None:
        self._submit_outcomes = tuple(submit_outcomes)
        if any(not isinstance(item, FakeSubmitOutcome) for item in self._submit_outcomes):
            raise ValueError("submit outcomes must use FakeSubmitOutcome")
        self._next_outcome = 0
        self._observations: dict[str, _FakeObservation] = {}
        self._records: list[FakeSubmissionRecord] = []

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            enabled=True,
            destinations=("fake-chain",),
            networks=("offline",),
            query_supported=True,
            evidence_status=EvidenceStatus.SIMULATED,
        )

    @property
    def records(self) -> tuple[FakeSubmissionRecord, ...]:
        return tuple(self._records)

    def submit(self, request: CommitmentPublicationRequest) -> SubmissionResult:
        if type(request) is not CommitmentPublicationRequest:
            raise ValueError("fake adapter accepts only a guarded commitment request")
        outcome = self._take_outcome()
        reference = f"simulated-{len(self._records) + 1:04d}"
        status, reason = _submission_status(outcome)
        if status is PublicationStatus.SUBMITTED:
            observation_status = (
                PublicationStatus.CONFIRMED
                if outcome is FakeSubmitOutcome.CONFIRMED
                else PublicationStatus.UNKNOWN
            )
            self._observations[reference] = _FakeObservation(
                commitment=request.envelope.commitment,
                destination=request.destination,
                network=request.network,
                reference=reference,
                status=observation_status,
            )
        record = FakeSubmissionRecord(
            commitment=request.envelope.commitment,
            destination=request.destination,
            network=request.network,
            reference=reference if status is PublicationStatus.SUBMITTED else None,
            status=status,
        )
        self._records.append(record)
        return SubmissionResult(
            status=status,
            commitment=record.commitment,
            destination=record.destination,
            network=record.network,
            reference=record.reference,
            reason=reason,
            evidence_status=EvidenceStatus.SIMULATED,
        )

    def query(
        self,
        *,
        commitment: str,
        destination: str,
        network: str,
        reference: str,
    ) -> ConfirmationResult:
        observation = self._observations.get(reference)
        if observation is None:
            return ConfirmationResult(
                status=PublicationStatus.UNKNOWN,
                commitment=commitment,
                destination=destination,
                network=network,
                reference=reference,
                reason=PublicationReason.NOT_FOUND,
                evidence_status=EvidenceStatus.SIMULATED,
            )
        if (
            observation.commitment != commitment
            or observation.destination != destination
            or observation.network != network
        ):
            return ConfirmationResult(
                status=PublicationStatus.REJECTED,
                commitment=commitment,
                destination=destination,
                network=network,
                reference=reference,
                reason=PublicationReason.OBSERVATION_MISMATCH,
                evidence_status=EvidenceStatus.SIMULATED,
            )
        return ConfirmationResult(
            status=observation.status,
            commitment=observation.commitment,
            destination=observation.destination,
            network=observation.network,
            reference=observation.reference,
            reason=(
                PublicationReason.NOT_FOUND
                if observation.status is PublicationStatus.UNKNOWN
                else None
            ),
            evidence_status=EvidenceStatus.SIMULATED,
        )

    def _take_outcome(self) -> FakeSubmitOutcome:
        if self._next_outcome >= len(self._submit_outcomes):
            return FakeSubmitOutcome.UNKNOWN
        outcome = self._submit_outcomes[self._next_outcome]
        self._next_outcome += 1
        return outcome


def _submission_status(
    outcome: FakeSubmitOutcome,
) -> tuple[PublicationStatus, PublicationReason | None]:
    if outcome in {FakeSubmitOutcome.SUBMITTED, FakeSubmitOutcome.CONFIRMED}:
        return PublicationStatus.SUBMITTED, None
    if outcome is FakeSubmitOutcome.REJECTED:
        return PublicationStatus.REJECTED, PublicationReason.DESTINATION_REJECTED
    if outcome is FakeSubmitOutcome.UNAVAILABLE:
        return PublicationStatus.UNAVAILABLE, PublicationReason.DESTINATION_UNAVAILABLE
    if outcome is FakeSubmitOutcome.TIMEOUT:
        return PublicationStatus.UNKNOWN, PublicationReason.TIMEOUT
    return PublicationStatus.UNKNOWN, PublicationReason.UNKNOWN
