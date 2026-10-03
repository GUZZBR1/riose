"""Adversarial tests for the public commitment privacy boundary."""

from __future__ import annotations

import json

import pytest

from riose.products.livestock_tracking.domain.privacy import (
    MAX_PUBLIC_ENVELOPE_BYTES,
    PrivacyGuardError,
    build_public_envelope,
    guard_public_envelope,
    parse_public_envelope_json,
    serialize_public_envelope,
)


VALID = {
    "version": 1,
    "algorithm": "sha256",
    "commitment": "a" * 64,
}


def test_allowlisted_envelope_passes_and_serialization_is_deterministic():
    guarded = guard_public_envelope(VALID)

    assert guarded == build_public_envelope("a" * 64)
    expected = b'{"algorithm":"sha256","commitment":"' + b"a" * 64 + b'","version":1}'
    assert serialize_public_envelope(VALID) == expected
    assert serialize_public_envelope(guarded) == expected
    assert serialize_public_envelope(VALID) == serialize_public_envelope(dict(reversed(list(VALID.items()))))
    assert len(expected) <= MAX_PUBLIC_ENVELOPE_BYTES


@pytest.mark.parametrize(
    "extra",
    [
        {"name": "Synthetic Cow"},
        {"animal_id": "animal-123"},
        {"owner": "Synthetic Owner"},
        {"coordinates": {"lat": -23.5, "lon": -46.6}},
        {"vet_history": [{"diagnosis": "synthetic"}]},
        {"payload": {"health_event": "synthetic"}},
        {"private_key": "synthetic-secret"},
        {"metadata": {"payload": {"name": "Synthetic Cow"}}},
        {"events": [{"payload": "encoded"}]},
        {"Yаме": "unicode lookalike key"},
        {"ＮＡＭＥ": "fullwidth alias"},
        {"NAME": "case alias"},
    ],
)
def test_rejects_sensitive_fields_aliases_and_nested_extras(extra):
    with pytest.raises(PrivacyGuardError):
        serialize_public_envelope(VALID | extra)


@pytest.mark.parametrize(
    "envelope",
    [
        VALID | {"salt": "a" * 64},
        VALID | {"metadata": {}},
        {"version": True, "algorithm": "sha256", "commitment": "a" * 64},
        {"version": 2, "algorithm": "sha256", "commitment": "a" * 64},
        {"version": 1, "algorithm": "SHA256", "commitment": "a" * 64},
        {"version": 1, "algorithm": "sha1", "commitment": "a" * 64},
        {"version": 1, "algorithm": "sha256", "commitment": "A" * 64},
        {"version": 1, "algorithm": "sha256", "commitment": "a" * 63},
        {"version": 1, "algorithm": "sha256", "commitment": "g" * 64},
    ],
)
def test_rejects_extra_or_malformed_schema_values(envelope):
    with pytest.raises(PrivacyGuardError):
        guard_public_envelope(envelope)


def test_fuzzes_unrecognized_keys_without_allowing_aliases():
    keys = {
        *("x" * size for size in range(1, 80)),
        *(f"field_{index}" for index in range(100)),
        "Version",
        "commitment_digest",
        "animal\u200b_id",
        "\ufeffversion",
    }
    for key in keys:
        with pytest.raises(PrivacyGuardError):
            guard_public_envelope(VALID | {key: "synthetic"})


def test_rejects_duplicate_keys_including_hidden_nested_duplicates():
    with pytest.raises(PrivacyGuardError, match="duplicate keys"):
        parse_public_envelope_json(
            '{"version":1,"algorithm":"sha256","commitment":"'
            + "a" * 64
            + '","version":1}'
        )
    with pytest.raises(PrivacyGuardError, match="duplicate keys"):
        parse_public_envelope_json(
            '{"version":1,"algorithm":"sha256","commitment":"'
            + "a" * 64
            + '","metadata":{"x":1,"x":2}}'
        )


def test_rejects_encoded_or_compressed_payload_fields_and_non_object_roots():
    encoded = "e30="
    compressed = "H4sIAAAAAAAA"
    for value in (
        VALID | {"encoded_payload": encoded},
        VALID | {"compressed_payload": compressed},
        [VALID],
        None,
    ):
        with pytest.raises(PrivacyGuardError):
            serialize_public_envelope(value)


def test_rejects_oversized_utf8_input_and_non_json_constants():
    oversized = b" " * (MAX_PUBLIC_ENVELOPE_BYTES + 1)
    with pytest.raises(PrivacyGuardError, match="size limit"):
        parse_public_envelope_json(oversized)
    with pytest.raises(PrivacyGuardError):
        parse_public_envelope_json('{"version":NaN}')


def test_rejected_values_are_not_echoed_in_errors():
    secret = "SYNTHETIC_PRIVATE_SEED_7e48f1"
    with pytest.raises(PrivacyGuardError) as error:
        serialize_public_envelope(VALID | {"private_key": secret})
    assert secret not in str(error.value)
    assert "private_key" not in str(error.value)

    with pytest.raises(PrivacyGuardError) as error:
        guard_public_envelope(VALID | {"commitment": secret})
    assert secret not in str(error.value)


def test_builder_accepts_only_a_valid_digest():
    assert build_public_envelope("a" * 64).commitment == "a" * 64
    with pytest.raises(PrivacyGuardError):
        build_public_envelope("synthetic private seed")


def test_guard_has_no_external_adapter_or_storage_input():
    # The public guard is a pure function: its only input is the JSON value.
    assert tuple(guard_public_envelope.__annotations__) == ("value", "return")
    assert json.loads(serialize_public_envelope(VALID)) == {
        "algorithm": "sha256",
        "commitment": "a" * 64,
        "version": 1,
    }
