"""Versioned, lossless and non-promoting shared evidence mapping tests."""

from __future__ import annotations

import json

import pytest

from riose.evidence.bridge import (
    EVIDENCE_MAPPING_VERSION,
    EvidenceBridgeRecord,
    EvidenceClass,
    MeasurementProvenance,
    map_source_evidence,
    parse_evidence_bridge,
    serialize_evidence_bridge,
)


@pytest.mark.parametrize(
    ("status", "source_ref", "method", "expected"),
    [
        ("SIMULATED", None, None, EvidenceClass.SIMULATED),
        ("ASSUMED", None, None, EvidenceClass.UNKNOWN),
        ("ASSUMED", None, "least-squares-v2", EvidenceClass.INFERRED),
        ("EXPERIMENTAL", "lab/run-3", None, EvidenceClass.UNKNOWN),
        ("FUTURE", "planned-device", "future-model", EvidenceClass.UNKNOWN),
        ("VALIDATED", "software:test-42", None, EvidenceClass.UNKNOWN),
        ("DATASHEET", "vendor/doc-42", None, EvidenceClass.DECLARED),
        ("DATASHEET", None, None, EvidenceClass.UNKNOWN),
        ("UNKNOWN_VENDOR_STATE", "source-1", None, EvidenceClass.UNKNOWN),
    ],
)
def test_known_ambiguous_and_unknown_status_mapping_is_closed(
    status, source_ref, method, expected
):
    record = map_source_evidence(
        status, source_ref=source_ref, inference_method=method
    )
    assert record.source_status == status
    assert record.evidence_class is expected
    assert record.mapping_version == EVIDENCE_MAPPING_VERSION


def test_measured_requires_explicit_physical_capture_and_matching_provenance_ref():
    assert map_source_evidence("MEASURED").evidence_class is EvidenceClass.UNKNOWN
    provenance = MeasurementProvenance(
        physical_source_ref="sensor:device-42",
        capture_ref="capture:2026-10-03T12:00Z",
        provenance_ref="evidence:record-8",
    )
    measured = map_source_evidence(
        "MEASURED",
        source_ref="evidence:record-8",
        measurement_provenance=provenance,
    )
    assert measured.evidence_class is EvidenceClass.MEASURED
    assert map_source_evidence(
        "MEASURED",
        source_ref="different-reference",
        measurement_provenance=provenance,
    ).evidence_class is EvidenceClass.UNKNOWN


def test_simulated_assumed_and_datasheet_never_become_measured_by_extra_metadata():
    provenance = MeasurementProvenance("sensor:device-1", "capture:1", "evidence:1")
    simulated = map_source_evidence(
        "SIMULATED",
        source_ref="evidence:1",
        measurement_provenance=provenance,
    )
    assumed = map_source_evidence(
        "ASSUMED",
        source_ref="evidence:1",
        inference_method="model-v1",
        measurement_provenance=provenance,
    )
    datasheet = map_source_evidence(
        "DATASHEET",
        source_ref="evidence:1",
        measurement_provenance=provenance,
    )
    assert simulated.evidence_class is EvidenceClass.SIMULATED
    assert assumed.evidence_class is EvidenceClass.INFERRED
    assert datasheet.evidence_class is EvidenceClass.DECLARED


def test_validated_is_not_measured_without_physical_source_metadata():
    assert map_source_evidence(
        "VALIDATED", source_ref="unit-test:green"
    ).evidence_class is EvidenceClass.UNKNOWN


def test_round_trip_preserves_original_status_reference_and_context_types():
    record = map_source_evidence(
        "ASSUMED",
        source_ref="model/config-7",
        inference_method="weighted-centroid-v1",
        source_context={"unit": "m", "value": 1.25, "reviewed": False},
    )
    restored = parse_evidence_bridge(serialize_evidence_bridge(record))
    assert restored == record
    assert restored.source_status == "ASSUMED"
    assert restored.source_ref == "model/config-7"
    assert restored.source_context == {"unit": "m", "value": 1.25, "reviewed": False}


def test_parser_rejects_class_promotion_and_unknown_mapping_version():
    record = map_source_evidence("SIMULATED")
    value = json.loads(serialize_evidence_bridge(record))
    value["evidence_class"] = "MEASURED"
    with pytest.raises(ValueError, match="mapping rules"):
        parse_evidence_bridge(json.dumps(value, sort_keys=True, separators=(",", ":")))

    value["evidence_class"] = "SIMULATED"
    value["mapping_version"] = 999
    with pytest.raises(ValueError, match="mapping version"):
        parse_evidence_bridge(json.dumps(value, sort_keys=True, separators=(",", ":")))


@pytest.mark.parametrize(
    "context",
    [
        {1: "non-string key"},
        {"not_finite": float("nan")},
        {"not_json": object()},
    ],
)
def test_source_context_rejects_non_json_or_lossy_values(context):
    with pytest.raises(ValueError):
        map_source_evidence("SIMULATED", source_context=context)


@pytest.mark.parametrize("source_ref", ["n/a", "placeholder", "unknown"])
def test_placeholder_references_cannot_support_declared_or_measured_evidence(source_ref):
    with pytest.raises(ValueError, match="source reference"):
        map_source_evidence("DATASHEET", source_ref=source_ref)


def test_deterministic_serialization_and_duplicate_keys_are_enforced():
    record = map_source_evidence("FUTURE", source_context={"source": "fixture"})
    encoded = serialize_evidence_bridge(record)
    assert encoded == serialize_evidence_bridge(record)
    with pytest.raises(ValueError, match="duplicate"):
        parse_evidence_bridge(
            b'{"evidence_class":"UNKNOWN","evidence_class":"UNKNOWN"}'
        )


def test_bridge_record_cannot_be_constructed_with_an_arbitrary_measured_class():
    with pytest.raises(ValueError, match="mapping rules"):
        EvidenceBridgeRecord("VALIDATED", EvidenceClass.MEASURED)
