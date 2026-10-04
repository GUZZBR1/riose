"""Golden and adversarial tests for the private binding/public Commitment V1."""

from __future__ import annotations

from dataclasses import replace
import json

import pytest

from riose.products.livestock_tracking.domain.commitment import (
    COMMITMENT_V1_DOMAIN,
    CommitmentV1,
    create_commitment_v1,
    create_commitment_from_chain_evidence,
    new_subject_ref,
    public_envelope,
    serialize_commitment_preimage,
    verify_commitment_v1,
)
from riose.products.livestock_tracking.domain.identity import LocalChainEvidence
from riose.products.livestock_tracking.domain.privacy import (
    parse_public_envelope_json,
    serialize_public_envelope,
)

SOURCE_DIGEST = "ab" * 32
SUBJECT_REF = "cd" * 32
GOLDEN_PREIMAGE = (
    b'{"algorithm":"sha256","domain":"riose:livestock-commitment:v1",'
    b'"schema_version":1,"source_digest":"'
    + b"ab" * 32
    + b'","subject_ref":"'
    + b"cd" * 32
    + b'"}'
)
GOLDEN_COMMITMENT = "dd5ea1e491681e624aae72a81689c0f4d3a6ae24e1748ab71c3f98cfdfbefafd"


def test_commitment_v1_preimage_and_digest_match_the_golden_vector():
    preimage = serialize_commitment_preimage(SOURCE_DIGEST, SUBJECT_REF)
    commitment = create_commitment_v1(SOURCE_DIGEST, SUBJECT_REF)
    assert preimage == GOLDEN_PREIMAGE
    assert commitment.digest == GOLDEN_COMMITMENT
    assert verify_commitment_v1(commitment)
    assert COMMITMENT_V1_DOMAIN.encode("ascii") in preimage


def test_creation_and_verification_are_deterministic_and_bind_both_inputs():
    first = create_commitment_v1(SOURCE_DIGEST, SUBJECT_REF)
    assert create_commitment_v1(SOURCE_DIGEST, SUBJECT_REF) == first
    assert not verify_commitment_v1(replace(first, source_digest="ef" * 32))
    assert not verify_commitment_v1(replace(first, subject_ref="01" * 32))
    assert create_commitment_v1("ef" * 32, SUBJECT_REF).digest != first.digest
    assert create_commitment_v1(SOURCE_DIGEST, "01" * 32).digest != first.digest


def test_chain_adapter_requires_a_valid_supported_chain_summary():
    evidence = LocalChainEvidence(True, SOURCE_DIGEST, 2)
    assert create_commitment_from_chain_evidence(evidence, SUBJECT_REF) == create_commitment_v1(
        SOURCE_DIGEST, SUBJECT_REF
    )
    with pytest.raises(ValueError, match="not valid"):
        create_commitment_from_chain_evidence(
            LocalChainEvidence(False, SOURCE_DIGEST, 2), SUBJECT_REF
        )
    with pytest.raises(ValueError, match="not valid"):
        create_commitment_from_chain_evidence(
            LocalChainEvidence(True, SOURCE_DIGEST, 2, algorithm="sha3-256"), SUBJECT_REF
        )
    with pytest.raises(ValueError, match="not valid"):
        create_commitment_from_chain_evidence(
            LocalChainEvidence(True, SOURCE_DIGEST, 0), SUBJECT_REF
        )


def test_random_subject_references_are_local_high_entropy_values():
    first = new_subject_ref()
    second = new_subject_ref()
    assert len(first) == len(second) == 64
    assert first != second
    assert all(character in "0123456789abcdef" for character in first)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: create_commitment_v1("not-a-digest", SUBJECT_REF),
        lambda: create_commitment_v1(SOURCE_DIGEST, "predictable"),
        lambda: CommitmentV1(2, "sha256", "aa" * 32, SUBJECT_REF, SOURCE_DIGEST),
        lambda: CommitmentV1(1, "sha3-256", "aa" * 32, SUBJECT_REF, SOURCE_DIGEST),
        lambda: CommitmentV1(1, "sha256", "A" * 64, SUBJECT_REF, SOURCE_DIGEST),
    ],
)
def test_invalid_inputs_unknown_version_algorithm_and_digest_fail_closed(factory):
    with pytest.raises(ValueError):
        factory()


def test_public_projection_contains_only_the_allowlisted_envelope_fields():
    commitment = create_commitment_v1(SOURCE_DIGEST, SUBJECT_REF)
    encoded = serialize_public_envelope(public_envelope(commitment))
    envelope = parse_public_envelope_json(encoded)
    assert set(json.loads(encoded)) == {"version", "algorithm", "commitment"}
    assert envelope.commitment == commitment.digest
    assert SUBJECT_REF.encode("ascii") not in encoded
    assert SOURCE_DIGEST.encode("ascii") not in encoded


def test_public_projection_rejects_a_mutated_local_binding():
    commitment = create_commitment_v1(SOURCE_DIGEST, SUBJECT_REF)
    with pytest.raises(ValueError, match="binding"):
        public_envelope(replace(commitment, source_digest="ef" * 32))


def test_raw_business_payload_cannot_be_used_as_a_commitment_input():
    with pytest.raises(ValueError, match="source_digest"):
        create_commitment_v1({"animal_id": "synthetic", "location": "farm"}, SUBJECT_REF)
