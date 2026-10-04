"""Pure, domain-separated Commitment V1 calculation and local binding."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass

from .identity import LocalChainEvidence
from .privacy import PublicCommitmentEnvelope, build_public_envelope

COMMITMENT_V1_VERSION = 1
COMMITMENT_V1_ALGORITHM = "sha256"
COMMITMENT_V1_DOMAIN = "riose:livestock-commitment:v1"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_SUBJECT_REF = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class CommitmentV1:
    """Private binding plus public digest; publish only `public_envelope()`.

    `source_digest` is the already-validated local event-chain digest and
    `subject_ref` is a local random reference. Neither belongs in the public
    envelope.
    """

    schema_version: int
    algorithm: str
    digest: str
    subject_ref: str
    source_digest: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != COMMITMENT_V1_VERSION:
            raise ValueError("unsupported Commitment V1 schema_version")
        if type(self.algorithm) is not str or self.algorithm != COMMITMENT_V1_ALGORITHM:
            raise ValueError("unsupported Commitment V1 algorithm")
        if type(self.digest) is not str or _DIGEST.fullmatch(self.digest) is None:
            raise ValueError("digest must be a lowercase SHA-256 digest")
        if type(self.source_digest) is not str or _DIGEST.fullmatch(self.source_digest) is None:
            raise ValueError("source_digest must be a lowercase SHA-256 digest")
        if type(self.subject_ref) is not str or _SUBJECT_REF.fullmatch(self.subject_ref) is None:
            raise ValueError("subject_ref must be a 256-bit lowercase hexadecimal reference")


def new_subject_ref() -> str:
    """Create a high-entropy local-only reference for one commitment subject."""

    return secrets.token_hex(32)


def serialize_commitment_preimage(source_digest: str, subject_ref: str) -> bytes:
    """Return the frozen deterministic UTF-8 preimage used by Commitment V1."""

    _validate_digest(source_digest, "source_digest")
    _validate_subject_ref(subject_ref)
    preimage = {
        "algorithm": COMMITMENT_V1_ALGORITHM,
        "domain": COMMITMENT_V1_DOMAIN,
        "schema_version": COMMITMENT_V1_VERSION,
        "source_digest": source_digest,
        "subject_ref": subject_ref,
    }
    return json.dumps(
        preimage,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def create_commitment_v1(source_digest: str, subject_ref: str) -> CommitmentV1:
    """Create a commitment from a verified source digest and local random ref.

    This pure function validates digest shape, not the source chain itself. The
    caller must verify its local chain before passing that chain's head digest.
    """

    preimage = serialize_commitment_preimage(source_digest, subject_ref)
    digest = hashlib.sha256(preimage).hexdigest()
    return CommitmentV1(
        schema_version=COMMITMENT_V1_VERSION,
        algorithm=COMMITMENT_V1_ALGORITHM,
        digest=digest,
        subject_ref=subject_ref,
        source_digest=source_digest,
    )


def create_commitment_from_chain_evidence(
    evidence: LocalChainEvidence, subject_ref: str
) -> CommitmentV1:
    """Create only from a valid, supported local-chain evidence summary."""

    if type(evidence) is not LocalChainEvidence:
        raise ValueError("evidence must be a LocalChainEvidence")
    if (
        evidence.valid is not True
        or evidence.algorithm != "sha256"
        or evidence.version != 1
        or evidence.event_count < 1
        or evidence.head_digest is None
    ):
        raise ValueError("local chain evidence is not valid Commitment V1 input")
    return create_commitment_v1(evidence.head_digest, subject_ref)


def verify_commitment_v1(commitment: CommitmentV1) -> bool:
    """Verify the local binding without I/O or fallback to unknown versions."""

    if type(commitment) is not CommitmentV1:
        raise ValueError("commitment must be a CommitmentV1")
    expected = hashlib.sha256(
        serialize_commitment_preimage(commitment.source_digest, commitment.subject_ref)
    ).hexdigest()
    return hmac.compare_digest(commitment.digest, expected)


def public_envelope(commitment: CommitmentV1) -> PublicCommitmentEnvelope:
    """Project only the allowlisted version, algorithm, and commitment digest."""

    if not verify_commitment_v1(commitment):
        raise ValueError("Commitment V1 local binding failed verification")
    return build_public_envelope(commitment.digest)


def _validate_digest(value: str, name: str) -> None:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _validate_subject_ref(value: str) -> None:
    if type(value) is not str or _SUBJECT_REF.fullmatch(value) is None:
        raise ValueError("subject_ref must be a 256-bit lowercase hexadecimal reference")
