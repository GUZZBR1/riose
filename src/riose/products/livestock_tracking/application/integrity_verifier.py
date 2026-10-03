"""Read-only consistency checks across the local event chain and receipts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from ..domain.contracts import EvidenceStatus
from ..domain.identity import LocalChainEvidence
from ..domain.publication import ConfirmationResult, PublicationStatus
from ..domain.receipt import PublicationReceipt, ReceiptStatus

_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_SCOPE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z", re.ASCII)
_REFERENCE = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z", re.ASCII)


class VerificationStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


class VerificationReason(StrEnum):
    CONSISTENT_OBSERVATION = "CONSISTENT_OBSERVATION"
    LOCAL_CHAIN_INVALID = "LOCAL_CHAIN_INVALID"
    LOCAL_COMMITMENT_MISMATCH = "LOCAL_COMMITMENT_MISMATCH"
    RECEIPT_MISSING = "RECEIPT_MISSING"
    RECEIPT_MISMATCH = "RECEIPT_MISMATCH"
    OBSERVATION_MISSING = "OBSERVATION_MISSING"
    OBSERVATION_MISMATCH = "OBSERVATION_MISMATCH"
    PUBLICATION_REJECTED = "PUBLICATION_REJECTED"
    PUBLICATION_NOT_CONFIRMED = "PUBLICATION_NOT_CONFIRMED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SIMULATED_ONLY = "SIMULATED_ONLY"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    EVIDENCE_PROVENANCE_MISMATCH = "EVIDENCE_PROVENANCE_MISMATCH"


@dataclass(frozen=True, slots=True)
class IntegrityVerificationRequest:
    commitment: str
    destination: str
    network: str
    reference: str

    def __post_init__(self) -> None:
        if type(self.commitment) is not str or _DIGEST.fullmatch(self.commitment) is None:
            raise ValueError("commitment must be a lowercase SHA-256 digest")
        for name, value in (("destination", self.destination), ("network", self.network)):
            if type(value) is not str or _SCOPE.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase technical identifier")
        if type(self.reference) is not str or _REFERENCE.fullmatch(self.reference) is None:
            raise ValueError("reference must be an opaque technical identifier")


@dataclass(frozen=True, slots=True)
class IntegrityVerificationResult:
    status: VerificationStatus
    reason: VerificationReason
    commitment: str
    algorithm: str | None
    version: int | None
    evidence_status: EvidenceStatus


class IntegrityVerifier:
    """Compare explicitly supplied evidence; never fetch, mutate, or repair."""

    def verify(
        self,
        request: IntegrityVerificationRequest,
        *,
        local_chain: LocalChainEvidence | None,
        receipt: PublicationReceipt | None,
        observation: ConfirmationResult | None,
    ) -> IntegrityVerificationResult:
        evidence_status = _combined_evidence(
            local_chain.evidence_status if local_chain else EvidenceStatus.FUTURE,
            receipt.evidence_status if receipt else EvidenceStatus.FUTURE,
            observation.evidence_status if observation else EvidenceStatus.FUTURE,
        )
        if local_chain is None:
            return self._result(request, VerificationStatus.UNAVAILABLE, VerificationReason.SOURCE_UNAVAILABLE, None, None, evidence_status)
        if local_chain.algorithm != "sha256" or local_chain.version != 1:
            return self._result(request, VerificationStatus.UNAVAILABLE, VerificationReason.UNSUPPORTED_VERSION, local_chain.algorithm, local_chain.version, evidence_status)
        if not local_chain.valid:
            return self._result(request, VerificationStatus.INVALID, VerificationReason.LOCAL_CHAIN_INVALID, local_chain.algorithm, local_chain.version, evidence_status)
        if local_chain.head_digest != request.commitment:
            return self._result(request, VerificationStatus.INVALID, VerificationReason.LOCAL_COMMITMENT_MISMATCH, local_chain.algorithm, local_chain.version, evidence_status)
        if receipt is None:
            return self._result(request, VerificationStatus.UNAVAILABLE, VerificationReason.RECEIPT_MISSING, local_chain.algorithm, local_chain.version, evidence_status)
        if receipt.version != 1:
            return self._result(request, VerificationStatus.UNAVAILABLE, VerificationReason.UNSUPPORTED_VERSION, local_chain.algorithm, receipt.version, evidence_status)
        if (
            receipt.commitment != request.commitment
            or receipt.destination != request.destination
            or receipt.network != request.network
            or (receipt.reference is not None and receipt.reference != request.reference)
        ):
            return self._result(request, VerificationStatus.INVALID, VerificationReason.RECEIPT_MISMATCH, local_chain.algorithm, receipt.version, evidence_status)
        if receipt.status in {ReceiptStatus.UNKNOWN, ReceiptStatus.UNAVAILABLE}:
            return self._result(request, VerificationStatus.UNAVAILABLE, VerificationReason.SOURCE_UNAVAILABLE, local_chain.algorithm, receipt.version, evidence_status)
        if receipt.status is ReceiptStatus.REJECTED:
            return self._result(request, VerificationStatus.INVALID, VerificationReason.PUBLICATION_REJECTED, local_chain.algorithm, receipt.version, evidence_status)
        if observation is None:
            return self._result(request, VerificationStatus.UNAVAILABLE, VerificationReason.OBSERVATION_MISSING, local_chain.algorithm, receipt.version, evidence_status)
        if (
            observation.commitment != request.commitment
            or observation.destination != request.destination
            or observation.network != request.network
            or observation.reference != request.reference
        ):
            return self._result(request, VerificationStatus.INVALID, VerificationReason.OBSERVATION_MISMATCH, local_chain.algorithm, receipt.version, evidence_status)
        if observation.status in {PublicationStatus.UNAVAILABLE, PublicationStatus.UNKNOWN}:
            return self._result(request, VerificationStatus.UNAVAILABLE, VerificationReason.SOURCE_UNAVAILABLE, local_chain.algorithm, receipt.version, evidence_status)
        if observation.status is PublicationStatus.REJECTED:
            return self._result(request, VerificationStatus.INVALID, VerificationReason.PUBLICATION_REJECTED, local_chain.algorithm, receipt.version, evidence_status)
        if observation.status is not PublicationStatus.CONFIRMED:
            return self._result(request, VerificationStatus.UNAVAILABLE, VerificationReason.PUBLICATION_NOT_CONFIRMED, local_chain.algorithm, receipt.version, evidence_status)
        if (
            EvidenceStatus.SIMULATED in {
                local_chain.evidence_status,
                receipt.evidence_status,
                observation.evidence_status,
            }
        ):
            return self._result(request, VerificationStatus.UNAVAILABLE, VerificationReason.SIMULATED_ONLY, local_chain.algorithm, receipt.version, EvidenceStatus.SIMULATED)
        if EvidenceStatus.FUTURE in {
            local_chain.evidence_status,
            receipt.evidence_status,
            observation.evidence_status,
        } or EvidenceStatus.EXPERIMENTAL in {
            local_chain.evidence_status,
            receipt.evidence_status,
            observation.evidence_status,
        }:
            return self._result(request, VerificationStatus.UNAVAILABLE, VerificationReason.SOURCE_UNAVAILABLE, local_chain.algorithm, receipt.version, evidence_status)
        if not _compatible_evidence(receipt.evidence_status, observation.evidence_status):
            return self._result(request, VerificationStatus.INVALID, VerificationReason.EVIDENCE_PROVENANCE_MISMATCH, local_chain.algorithm, receipt.version, evidence_status)
        return self._result(request, VerificationStatus.VALID, VerificationReason.CONSISTENT_OBSERVATION, local_chain.algorithm, receipt.version, evidence_status)

    @staticmethod
    def _result(
        request: IntegrityVerificationRequest,
        status: VerificationStatus,
        reason: VerificationReason,
        algorithm: str | None,
        version: int | None,
        evidence_status: EvidenceStatus,
    ) -> IntegrityVerificationResult:
        return IntegrityVerificationResult(status, reason, request.commitment, algorithm, version, evidence_status)


def _compatible_evidence(receipt: EvidenceStatus, observed: EvidenceStatus) -> bool:
    return receipt is EvidenceStatus.FUTURE or receipt is observed


def _combined_evidence(*statuses: EvidenceStatus) -> EvidenceStatus:
    for status in (EvidenceStatus.SIMULATED, EvidenceStatus.ASSUMED, EvidenceStatus.EXPERIMENTAL):
        if status in statuses:
            return status
    if EvidenceStatus.VALIDATED in statuses:
        return EvidenceStatus.VALIDATED
    return EvidenceStatus.FUTURE
