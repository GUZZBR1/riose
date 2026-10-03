"""Idempotent intent boundary for optional commitment publication."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ..domain.publication import (
    ConfirmationResult,
    PublicationPort,
    PublicationReason,
    PublicationStatus,
    SubmissionResult,
    CommitmentPublicationRequest,
)


PUBLICATION_KEY_VERSION = 1
_PURPOSE_PATTERN = re.compile(r"[a-z][a-z0-9._-]{0,63}\Z", re.ASCII)


class RegistryStatus(StrEnum):
    NEW = "NEW"
    EXISTING_SUBMITTED = "EXISTING_SUBMITTED"
    EXISTING_CONFIRMED = "EXISTING_CONFIRMED"
    UNKNOWN = "UNKNOWN"


class IdempotencyConflict(ValueError):
    """A stable publication key was presented with a different fingerprint."""


@dataclass(frozen=True, slots=True)
class RegistryResult:
    status: RegistryStatus
    reference: str | None = None


@dataclass(frozen=True, slots=True)
class IdempotentSubmission:
    key: str
    status: RegistryStatus
    submission: SubmissionResult | None = None
    reference: str | None = None
    reason: PublicationReason | None = None


class PublicationAttemptRegistry(Protocol):
    """Atomic local intent registry; implementations define their durability."""

    def reserve(self, key: str, fingerprint: str) -> RegistryResult: ...

    def get(self, key: str, fingerprint: str) -> RegistryResult: ...

    def record_submission(
        self, key: str, fingerprint: str, result: SubmissionResult
    ) -> None: ...

    def record_unknown(self, key: str, fingerprint: str) -> None: ...

    def record_confirmation(
        self, key: str, fingerprint: str, result: ConfirmationResult
    ) -> None: ...


def derive_publication_key(
    request: CommitmentPublicationRequest, *, purpose: str = "commitment-anchor"
) -> str:
    """Derive a stable key from versioned technical scope and digest only."""

    _validate_request_and_purpose(request, purpose)
    canonical = json.dumps(
        {
            "commitment": request.envelope.commitment,
            "destination": request.destination,
            "key_version": PUBLICATION_KEY_VERSION,
            "network": request.network,
            "protocol_version": request.protocol_version,
            "purpose": purpose,
        },
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def publication_fingerprint(
    request: CommitmentPublicationRequest, *, purpose: str = "commitment-anchor"
) -> str:
    """Fingerprint the complete minimized intent for conflict detection."""

    _validate_request_and_purpose(request, purpose)
    canonical = json.dumps(
        {
            "algorithm": request.envelope.algorithm,
            "commitment": request.envelope.commitment,
            "destination": request.destination,
            "envelope_version": request.envelope.version,
            "network": request.network,
            "protocol_version": request.protocol_version,
            "purpose": purpose,
        },
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class IdempotentPublisher:
    """Avoid duplicate local submit calls when a registry has prior evidence."""

    def __init__(
        self,
        adapter: PublicationPort,
        registry: PublicationAttemptRegistry,
        *,
        purpose: str = "commitment-anchor",
    ) -> None:
        if not isinstance(purpose, str) or _PURPOSE_PATTERN.fullmatch(purpose) is None:
            raise ValueError("purpose must be a lowercase technical identifier")
        self._adapter = adapter
        self._registry = registry
        self._purpose = purpose

    def submit(self, request: CommitmentPublicationRequest) -> IdempotentSubmission:
        key = derive_publication_key(request, purpose=self._purpose)
        fingerprint = publication_fingerprint(request, purpose=self._purpose)
        reservation = self._registry.reserve(key, fingerprint)
        if reservation.status is not RegistryStatus.NEW:
            return IdempotentSubmission(
                key=key,
                status=reservation.status,
                reference=reservation.reference,
                reason=(
                    PublicationReason.UNKNOWN
                    if reservation.status is RegistryStatus.UNKNOWN
                    else None
                ),
            )

        try:
            result = self._adapter.submit(request)
        except Exception:
            # Do not copy adapter exception text into records or responses.
            self._registry.record_unknown(key, fingerprint)
            return IdempotentSubmission(
                key=key,
                status=RegistryStatus.UNKNOWN,
                reason=PublicationReason.UNKNOWN,
            )

        if (
            result.commitment != request.envelope.commitment
            or result.destination != request.destination
            or result.network != request.network
        ):
            self._registry.record_unknown(key, fingerprint)
            return IdempotentSubmission(
                key=key,
                status=RegistryStatus.UNKNOWN,
                reason=PublicationReason.UNKNOWN,
            )
        self._registry.record_submission(key, fingerprint, result)
        return IdempotentSubmission(
            key=key,
            status=RegistryStatus.NEW,
            submission=result,
            reference=result.reference,
            reason=(
                result.reason
                if result.status is not PublicationStatus.SUBMITTED
                else None
            ),
        )

    def query(
        self, request: CommitmentPublicationRequest, reference: str
    ) -> ConfirmationResult:
        key = derive_publication_key(request, purpose=self._purpose)
        fingerprint = publication_fingerprint(request, purpose=self._purpose)
        registered = self._registry.get(key, fingerprint)
        result = self._adapter.query(
            commitment=request.envelope.commitment,
            destination=request.destination,
            network=request.network,
            reference=reference,
        )
        if (
            result.status is PublicationStatus.CONFIRMED
            and result.commitment == request.envelope.commitment
            and result.destination == request.destination
            and result.network == request.network
            and result.reference == reference
            and registered.status is RegistryStatus.EXISTING_SUBMITTED
            and registered.reference == reference
        ):
            self._registry.record_confirmation(key, fingerprint, result)
        return result


def _validate_request_and_purpose(
    request: CommitmentPublicationRequest, purpose: str
) -> None:
    if type(request) is not CommitmentPublicationRequest:
        raise ValueError("request must be a guarded commitment publication request")
    if type(purpose) is not str or _PURPOSE_PATTERN.fullmatch(purpose) is None:
        raise ValueError("purpose must be a lowercase technical identifier")
