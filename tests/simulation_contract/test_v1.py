from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from riose.simulation_contract.v1 import (
    ContractError, canonical_json, content_hash, load_json, validate_id_mappings,
    validate_request, validate_result,
)

FIXTURES = Path(__file__).parents[2] / "src/riose/simulation_contract/fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_fixture_request_and_result_validate_and_round_trip():
    request, result = fixture("request-v1.json"), fixture("result-v1.json")
    assert load_json(canonical_json(validate_request(request)), kind="request") == request
    assert load_json(canonical_json(validate_result(result)), kind="result") == result
    assert {row["rx_state"] for row in result["observations"]} >= {"RECEIVED", "NOT_RECEIVED", "NOT_APPLICABLE"}
    assert all(row["status"] == "SIMULATED" for row in result["observations"])


@pytest.mark.parametrize("kind,doc", [("request", fixture("request-v1.json")), ("result", fixture("result-v1.json"))])
def test_missing_and_future_schema_versions_rejected(kind, doc):
    missing = copy.deepcopy(doc)
    del missing["schema_version"]
    with pytest.raises(ContractError, match="missing required"):
        load_json(json.dumps(missing), kind=kind)
    future = copy.deepcopy(doc)
    future["schema_version"] = "riose.simulation." + kind + "/v99"
    with pytest.raises(ContractError, match="unsupported"):
        (validate_request if kind == "request" else validate_result)(future)


def test_unknown_top_level_fields_are_rejected():
    doc = fixture("request-v1.json")
    doc["ignored_dangerous_field"] = True
    with pytest.raises(ContractError, match="unsupported fields"):
        validate_request(doc)


@pytest.mark.parametrize("mapping", [
    {"source_system": "x", "source_kind": "transmitter_id", "source_id": "d1", "riose_kind": "tag_id", "riose_id": "t1"},
    {"source_system": "x", "source_kind": "transmitter_id", "source_id": "d1", "riose_kind": "tag_id", "riose_id": "t2"},
])
def test_duplicate_source_identity_rejected(mapping):
    with pytest.raises(ContractError, match="duplicate source"):
        validate_id_mappings([mapping, mapping])


def test_conflicting_and_ambiguous_target_rejected():
    rows = fixture("request-v1.json")["id_mappings"]
    conflicting = rows + [{**rows[0], "source_id": "second-device"}]
    with pytest.raises(ContractError, match="conflicting RIOSE"):
        validate_id_mappings(conflicting)


def test_same_kind_and_source_id_from_different_systems_is_ambiguous_in_v1_refs():
    rows = fixture("request-v1.json")["id_mappings"]
    duplicated_reference = rows + [{**rows[0], "source_system": "other-engine", "riose_id": "other-tag"}]
    with pytest.raises(ContractError, match="ambiguous source mapping"):
        validate_id_mappings(duplicated_reference)


def test_unknown_or_missing_request_mapping_rejected():
    doc = fixture("request-v1.json")
    doc["id_mappings"].pop(0)
    with pytest.raises(ContractError, match="no exact tag_id mapping"):
        validate_request(doc)
    doc = fixture("request-v1.json")
    doc["tags"][0]["transmitter_ref"] = "not-mapped"
    with pytest.raises(ContractError, match="no exact tag_id mapping"):
        validate_request(doc)


def test_result_requires_mapping_and_rejects_timestamp_without_timezone():
    doc = fixture("result-v1.json")
    del doc["id_mappings"]
    with pytest.raises(ContractError, match="missing required"):
        validate_result(doc)
    doc = fixture("result-v1.json")
    doc["provenance"]["completed_at"] = "2026-10-03T00:00:01"
    with pytest.raises(ContractError, match="UTC offset"):
        validate_result(doc)


@pytest.mark.parametrize("field,value,match", [
    ("schema_version", None, "unsupported"),
    ("unexpected", True, "unsupported fields"),
    ("coordinate_frame", "LAT_LON", "coordinate_frame"),
])
def test_request_invalid_cases(field, value, match):
    doc = fixture("request-v1.json")
    doc[field] = value
    with pytest.raises(ContractError, match=match):
        validate_request(doc)


@pytest.mark.parametrize("field,value,match", [
    ("frequency_hz", -1, "frequency_hz"),
    ("frequency_hz", float("nan"), "finite number"),
    ("tx_power_dbm", 1000, "tx_power_dbm"),
])
def test_invalid_radio_numbers_rejected(field, value, match):
    doc = fixture("request-v1.json")
    doc["radio"][field] = value
    with pytest.raises(ContractError, match=match):
        validate_request(doc)


def test_invalid_trajectory_position_and_duplicate_ids_rejected():
    doc = fixture("request-v1.json")
    doc["trajectory"]["samples"][1]["timestamp_s"] = 0
    with pytest.raises(ContractError, match="timestamps"):
        validate_request(doc)
    doc = fixture("request-v1.json")
    doc["receivers"].append(copy.deepcopy(doc["receivers"][0]))
    with pytest.raises(ContractError, match="duplicate receiver_ref"):
        validate_request(doc)


def test_result_rejects_bad_state_metrics_mapping_and_evidence_promotion():
    doc = fixture("result-v1.json")
    doc["observations"][1]["metrics"]["received_power_dbm"] = -80
    with pytest.raises(ContractError, match="NO_PATH"):
        validate_result(doc)
    doc = fixture("result-v1.json")
    doc["observations"][0]["rx_state"] = "NOT_RECEIVED"
    with pytest.raises(ContractError, match="PHY reception"):
        validate_result(doc)
    doc = fixture("result-v1.json")
    doc["observations"][0]["anchor_id"] = "unknown-anchor"
    with pytest.raises(ContractError, match="unknown or conflicting"):
        validate_result(doc)
    doc = fixture("result-v1.json")
    doc["status"] = "VALIDATED"
    with pytest.raises(ContractError, match="SIMULATED"):
        validate_result(doc)


def test_result_rejects_received_no_path_and_absurd_metrics():
    doc = fixture("result-v1.json")
    doc["observations"][0]["channel_state"] = "NO_PATH"
    with pytest.raises(ContractError, match="NO_PATH"):
        validate_result(doc)
    doc = fixture("result-v1.json")
    doc["observations"][0]["metrics"]["received_power_dbm"] = 1000
    with pytest.raises(ContractError, match="received_power_dbm"):
        validate_result(doc)


def test_unknown_and_unavailable_metrics_are_null_not_fabricated():
    doc = fixture("result-v1.json")
    received = doc["observations"][0]["metrics"]
    assert received["rssi_dbm"] is None and received["tof_measured_s"] is None
    validate_result(doc)


def test_channel_power_is_available_when_packet_outcome_is_unmodeled():
    doc = fixture("result-v1.json")
    row = doc["observations"][0]
    row["tx_state"] = "UNKNOWN"
    row["rx_state"] = "DATA_UNAVAILABLE"
    row["metrics"]["snr_db"] = None
    row["metrics"]["rssi_dbm"] = None
    # A propagation solver can produce channel power without modeling packet
    # detection. This must never be relabeled as RSSI.
    validate_result(doc)


def test_channel_power_without_path_is_rejected():
    doc = fixture("result-v1.json")
    row = doc["observations"][0]
    row["channel_state"] = "UNKNOWN"
    row["metrics"]["path_state"] = "UNKNOWN"
    row["metrics"]["snr_db"] = None
    with pytest.raises(ContractError, match="channel path"):
        validate_result(doc)


def test_deterministic_hash_is_order_independent_for_objects_and_sensitive_to_content():
    one = {"b": 2, "a": [1, 3]}
    two = {"a": [1, 3], "b": 2}
    assert canonical_json(one) == canonical_json(two)
    assert content_hash(one) == content_hash(two)
    assert content_hash(one) != content_hash({"a": [1, 4], "b": 2})
    assert content_hash({"a": [1, 3, 2], "b": 2}) != content_hash(one)


def test_malformed_non_finite_json_rejected():
    with pytest.raises(ContractError, match="malformed JSON"):
        load_json('{"x":NaN}', kind="request")
    with pytest.raises(ContractError, match="finite JSON"):
        canonical_json({"x": float("inf")})
