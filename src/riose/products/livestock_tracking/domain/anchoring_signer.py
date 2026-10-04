"""External signer contract for blockchain transaction anchoring."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .contracts import EvidenceStatus


MAX_SIGNING_MESSAGE_BYTES = 1_048_576
MAX_SIGNATURE_BYTES = 4096
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z", re.ASCII)


class AnchoringPurpose(StrEnum):
    TRANSACTION = "TRANSACTION"


class SigningStatus(StrEnum):
    SIGNED = "SIGNED"
    UNAVAILABLE = "UNAVAILABLE"
    REJECTED = "REJECTED"


class SigningReason(StrEnum):
    SIGNER_UNAVAILABLE = "SIGNER_UNAVAILABLE"
    SIGNATURE_INVALID = "SIGNATURE_INVALID"
    PUBLIC_KEY_MISMATCH = "PUBLIC_KEY_MISMATCH"
    REQUEST_REJECTED = "REQUEST_REJECTED"
    VERIFIER_UNAVAILABLE = "VERIFIER_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class AnchorSigningRequest:
    """Exact immutable transaction bytes and scope; it has no secret field."""

    message: bytes
    network: str
    expected_public_key: str
    purpose: AnchoringPurpose

    def __post_init__(self) -> None:
        if type(self.message) is not bytes or not self.message:
            raise ValueError("message must be non-empty immutable bytes")
        if len(self.message) > MAX_SIGNING_MESSAGE_BYTES:
            raise ValueError("message exceeds the signing size limit")
        _validate_identifier(self.network, "network")
        _validate_identifier(self.expected_public_key, "expected_public_key")
        if not isinstance(self.purpose, AnchoringPurpose):
            raise ValueError("purpose must be an AnchoringPurpose")


@dataclass(frozen=True, slots=True)
class SigningResult:
    status: SigningStatus
    public_key: str | None = None
    signature: bytes | None = None
    reason: SigningReason | None = None
    evidence_status: EvidenceStatus = EvidenceStatus.FUTURE

    def __post_init__(self) -> None:
        if not isinstance(self.status, SigningStatus):
            raise ValueError("status must be a SigningStatus")
        if self.reason is not None and not isinstance(self.reason, SigningReason):
            raise ValueError("reason must use an allowlisted SigningReason")
        if not isinstance(self.evidence_status, EvidenceStatus):
            raise ValueError("evidence_status must be an EvidenceStatus")
        if self.status is SigningStatus.SIGNED:
            _validate_identifier(self.public_key, "public_key")
            if type(self.signature) is not bytes or not self.signature:
                raise ValueError("signed result requires non-empty signature bytes")
            if len(self.signature) > MAX_SIGNATURE_BYTES:
                raise ValueError("signature exceeds the size limit")
        elif self.public_key is not None or self.signature is not None:
            raise ValueError("non-success result cannot carry signature material")


class AnchoringSignerPort(Protocol):
    """External signer boundary; private key material never enters this API."""

    def sign(self, request: AnchorSigningRequest) -> SigningResult: ...


class SignatureVerifier(Protocol):
    """Injected verifier for the algorithm and key representation in use."""

    def verify(self, request: AnchorSigningRequest, result: SigningResult) -> bool: ...


def sign_anchor_transaction(
    request: AnchorSigningRequest,
    signer: AnchoringSignerPort | None,
    verifier: SignatureVerifier,
) -> SigningResult:
    """Call the external signer and verify its exact key/message binding."""

    if signer is None:
        return SigningResult(
            SigningStatus.UNAVAILABLE,
            reason=SigningReason.SIGNER_UNAVAILABLE,
            evidence_status=EvidenceStatus.FUTURE,
        )
    try:
        result = signer.sign(request)
    except Exception:
        return SigningResult(
            SigningStatus.UNAVAILABLE,
            reason=SigningReason.SIGNER_UNAVAILABLE,
            evidence_status=EvidenceStatus.FUTURE,
        )
    if result.status is not SigningStatus.SIGNED:
        return result
    if result.public_key != request.expected_public_key:
        return SigningResult(
            SigningStatus.REJECTED,
            reason=SigningReason.PUBLIC_KEY_MISMATCH,
            evidence_status=result.evidence_status,
        )
    try:
        valid = verifier.verify(request, result)
    except Exception:
        return SigningResult(
            SigningStatus.UNAVAILABLE,
            reason=SigningReason.VERIFIER_UNAVAILABLE,
            evidence_status=result.evidence_status,
        )
    if valid is not True:
        return SigningResult(
            SigningStatus.REJECTED,
            reason=SigningReason.SIGNATURE_INVALID,
            evidence_status=result.evidence_status,
        )
    return result


def _validate_identifier(value: str | None, name: str) -> None:
    if type(value) is not str or _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be an opaque technical identifier")


def _simulated_signature(request: AnchorSigningRequest) -> bytes:
    """Deterministic test value; deliberately not a cryptographic signature."""

    material = b"\0".join(
        (
            request.message,
            request.network.encode("ascii"),
            request.expected_public_key.encode("ascii"),
            request.purpose.value.encode("ascii"),
        )
    )
    return b"SIMULATED:" + hashlib.sha256(material).digest()


class FakeAnchoringSigner:
    """No-key signer fake whose deterministic output is marked SIMULATED."""

    def __init__(self, *, public_key: str | None = None, unavailable: bool = False) -> None:
        self.public_key = public_key
        self.unavailable = unavailable
        self.calls: list[AnchorSigningRequest] = []

    def sign(self, request: AnchorSigningRequest) -> SigningResult:
        self.calls.append(request)
        if self.unavailable:
            return SigningResult(
                SigningStatus.UNAVAILABLE,
                reason=SigningReason.SIGNER_UNAVAILABLE,
                evidence_status=EvidenceStatus.SIMULATED,
            )
        public_key = self.public_key or request.expected_public_key
        result_request = AnchorSigningRequest(
            message=request.message,
            network=request.network,
            expected_public_key=public_key,
            purpose=request.purpose,
        )
        return SigningResult(
            SigningStatus.SIGNED,
            public_key=public_key,
            signature=_simulated_signature(result_request),
            evidence_status=EvidenceStatus.SIMULATED,
        )


class FakeSignatureVerifier:
    """Checks fake bytes against the exact request; it is not cryptographic."""

    def verify(self, request: AnchorSigningRequest, result: SigningResult) -> bool:
        return result.signature == _simulated_signature(request)
