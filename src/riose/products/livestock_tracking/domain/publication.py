"""Chain-neutral contracts for optional commitment publication.

These types describe a boundary only. They perform no network, persistence,
signing, retry, or polling work. Legacy ``BlockchainAdapter`` Protocols remain
available at their original import paths during migration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .contracts import EvidenceStatus
from .privacy import PublicCommitmentEnvelope, serialize_public_envelope


_DESTINATION_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z", re.ASCII)
_REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z", re.ASCII)
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


class PublicationStatus(StrEnum):
    """Knowledge about a publication or its external observation."""

    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class PublicationReason(StrEnum):
    """Allowlisted, non-sensitive reason codes for typed results."""

    INVALID_REQUEST = "INVALID_REQUEST"
    DESTINATION_REJECTED = "DESTINATION_REJECTED"
    DESTINATION_UNAVAILABLE = "DESTINATION_UNAVAILABLE"
    SIGNER_UNAVAILABLE = "SIGNER_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    NOT_FOUND = "NOT_FOUND"
    OBSERVATION_MISMATCH = "OBSERVATION_MISMATCH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CommitmentPublicationRequest:
    """Minimal request for one already-guarded commitment."""

    envelope: PublicCommitmentEnvelope
    destination: str
    network: str
    protocol_version: int = 1
    idempotency_reference: str | None = None

    def __post_init__(self) -> None:
        if type(self.envelope) is not PublicCommitmentEnvelope:
            raise ValueError("envelope must be a guarded public commitment")
        # Revalidate the DTO at the application boundary, including exact fields.
        serialize_public_envelope(self.envelope)
        for name, value in (("destination", self.destination), ("network", self.network)):
            if type(value) is not str or _DESTINATION_PATTERN.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase technical identifier")
        if type(self.protocol_version) is not int or self.protocol_version < 1:
            raise ValueError("protocol_version must be a positive integer")
        if self.idempotency_reference is not None and (
            type(self.idempotency_reference) is not str
            or _REFERENCE_PATTERN.fullmatch(self.idempotency_reference) is None
        ):
            raise ValueError("idempotency_reference must be an opaque technical reference")


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    """Explicit optional adapter support; absence never implies success."""

    enabled: bool
    destinations: tuple[str, ...]
    networks: tuple[str, ...]
    query_supported: bool
    evidence_status: EvidenceStatus = EvidenceStatus.FUTURE

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool or type(self.query_supported) is not bool:
            raise ValueError("capability flags must be booleans")
        if not isinstance(self.evidence_status, EvidenceStatus):
            raise ValueError("evidence_status must be an EvidenceStatus")
        if type(self.destinations) is not tuple or type(self.networks) is not tuple:
            raise ValueError("destinations and networks must be tuples")
        for value in (*self.destinations, *self.networks):
            if type(value) is not str or _DESTINATION_PATTERN.fullmatch(value) is None:
                raise ValueError("capability identifiers must be lowercase technical identifiers")
        if not self.enabled and (self.destinations or self.networks or self.query_supported):
            raise ValueError("disabled capabilities cannot advertise support")


DISABLED_PUBLICATION_CAPABILITIES = AdapterCapabilities(
    enabled=False,
    destinations=(),
    networks=(),
    query_supported=False,
    evidence_status=EvidenceStatus.FUTURE,
)


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    """Outcome of a submit call; it cannot claim external confirmation."""

    status: PublicationStatus
    commitment: str
    destination: str
    network: str
    reference: str | None = None
    reason: PublicationReason | None = None
    evidence_status: EvidenceStatus = EvidenceStatus.FUTURE

    def __post_init__(self) -> None:
        if not isinstance(self.status, PublicationStatus):
            raise ValueError("status must be a PublicationStatus")
        if self.status not in {
            PublicationStatus.SUBMITTED,
            PublicationStatus.REJECTED,
            PublicationStatus.UNAVAILABLE,
            PublicationStatus.UNKNOWN,
        }:
            raise ValueError("submit cannot report confirmation")
        _validate_result_identity(self.commitment, self.destination, self.network)
        if self.status is PublicationStatus.SUBMITTED:
            _validate_reference(self.reference)
        elif self.reference is not None:
            _validate_reference(self.reference)
        _validate_reason_and_evidence(self.reason, self.evidence_status)


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    """Outcome of an explicit lookup tied to one commitment and reference."""

    status: PublicationStatus
    commitment: str
    destination: str
    network: str
    reference: str
    reason: PublicationReason | None = None
    evidence_status: EvidenceStatus = EvidenceStatus.FUTURE

    def __post_init__(self) -> None:
        if not isinstance(self.status, PublicationStatus):
            raise ValueError("status must be a PublicationStatus")
        if self.status not in {
            PublicationStatus.SUBMITTED,
            PublicationStatus.CONFIRMED,
            PublicationStatus.REJECTED,
            PublicationStatus.UNAVAILABLE,
            PublicationStatus.UNKNOWN,
        }:
            raise ValueError("lookup result must describe an observation or its absence")
        _validate_result_identity(self.commitment, self.destination, self.network)
        _validate_reference(self.reference)
        _validate_reason_and_evidence(self.reason, self.evidence_status)


def _validate_result_identity(commitment: str, destination: str, network: str) -> None:
    if type(commitment) is not str or _DIGEST_PATTERN.fullmatch(commitment) is None:
        raise ValueError("commitment must be a lowercase SHA-256 digest")
    for name, value in (("destination", destination), ("network", network)):
        if type(value) is not str or _DESTINATION_PATTERN.fullmatch(value) is None:
            raise ValueError(f"{name} must be a lowercase technical identifier")


def _validate_reference(reference: str | None) -> None:
    if type(reference) is not str or _REFERENCE_PATTERN.fullmatch(reference) is None:
        raise ValueError("reference must be a non-empty opaque technical reference")


def _validate_reason_and_evidence(
    reason: PublicationReason | None, evidence_status: EvidenceStatus
) -> None:
    if reason is not None and not isinstance(reason, PublicationReason):
        raise ValueError("reason must use an allowlisted PublicationReason")
    if not isinstance(evidence_status, EvidenceStatus):
        raise ValueError("evidence_status must be an EvidenceStatus")


class PublicationPort(Protocol):
    """Canonical optional port for commitment submission and explicit lookup."""

    @property
    def capabilities(self) -> AdapterCapabilities: ...

    def submit(self, request: CommitmentPublicationRequest) -> SubmissionResult: ...

    def query(
        self,
        *,
        commitment: str,
        destination: str,
        network: str,
        reference: str,
    ) -> ConfirmationResult: ...


def publication_capabilities(port: PublicationPort | None) -> AdapterCapabilities:
    """Return an explicit disabled/FUTURE snapshot when no adapter is configured."""

    return DISABLED_PUBLICATION_CAPABILITIES if port is None else port.capabilities
