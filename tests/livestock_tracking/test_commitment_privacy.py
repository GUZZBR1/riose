import json
from dataclasses import replace

import pytest

from riose.products.livestock_tracking.domain.commitment import (
    create_commitment_v1, new_subject_ref, public_envelope,
    serialize_commitment_preimage, verify_commitment_v1,
)
from riose.products.livestock_tracking.domain.privacy import (
    parse_public_envelope_json, serialize_public_envelope,
)


def test_commitment_v1_preserves_historical_golden_vector():
    source = "ab" * 32
    subject = "cd" * 32
    preimage = serialize_commitment_preimage(source, subject)
    assert preimage == (
        b'{"algorithm":"sha256","domain":"riose:livestock-commitment:v1",'
        b'"schema_version":1,"source_digest":"' + b"ab" * 32 +
        b'","subject_ref":"' + b"cd" * 32 + b'"}'
    )
    assert create_commitment_v1(source, subject).digest == (
        "dd5ea1e491681e624aae72a81689c0f4d3a6ae24e1748ab71c3f98cfdfbefafd"
    )


def test_commitment_is_deterministic_and_binds_source_and_subject():
    source, subject = "ab" * 32, "cd" * 32
    first = create_commitment_v1(source, subject)
    assert create_commitment_v1(source, subject) == first
    assert create_commitment_v1("ef" * 32, subject).digest != first.digest
    assert create_commitment_v1(source, "01" * 32).digest != first.digest
    assert not verify_commitment_v1(replace(first, source_digest="ef" * 32))


def test_subject_refs_are_high_entropy_and_public_envelope_is_minimal():
    first, second = new_subject_ref(), new_subject_ref()
    assert first != second and len(first) == len(second) == 64
    commitment = create_commitment_v1("ab" * 32, first)
    raw = serialize_public_envelope(public_envelope(commitment))
    assert set(json.loads(raw)) == {"version", "algorithm", "commitment"}
    assert first.encode() not in raw and b"ab" * 32 not in raw
    assert parse_public_envelope_json(raw).commitment == commitment.digest


@pytest.mark.parametrize("payload", [
    b'{"version":1,"version":1,"algorithm":"sha256","commitment":"' + b"a" * 64 + b'"}',
    b'{"version":1,"algorithm":"sha256","commitment":"' + b"a" * 64 + b'","animal_id":"cow-1"}',
    b'{"version":NaN,"algorithm":"sha256","commitment":"' + b"a" * 64 + b'"}',
])
def test_public_envelope_parser_fails_closed(payload):
    with pytest.raises(ValueError):
        parse_public_envelope_json(payload)
