import json
from pathlib import Path

import pytest

from riose.products.livestock_tracking.domain.contracts import EvidenceStatus
from riose.simulation_adapter import ConversionError, ConversionPolicy, convert_result


FIXTURE = Path(__file__).parents[2] / "src/riose/simulation_contract/fixtures/result-v1.json"


@pytest.fixture
def result():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_demo_batch_preserves_states_nulls_and_simulated_provenance(result):
    batch = convert_result(result)
    assert len(batch.observations) == 3
    received, no_path, not_sent = batch.observations
    assert received.packet_received is True
    assert received.rssi_dbm is None  # received power is not RSSI by default
    assert received.snr_db == 18.5
    assert received.tof_ns == pytest.approx(41.2)
    assert received.phase_rad is None
    assert no_path.packet_received is False and not_sent.packet_received is False
    assert [m["channel_state"] for m in batch.observation_provenance] == ["PATH", "NO_PATH", "UNKNOWN"]
    assert batch.observation_provenance[1]["rx_state"] == "NOT_RECEIVED"
    assert batch.observation_provenance[2]["tx_state"] == "NOT_TRANSMITTED"
    assert all(item.status == EvidenceStatus.SIMULATED for item in batch.observations)
    assert batch.observation_provenance[0]["tof_semantics"] == "SIMULATED_PROPAGATION_DELAY"
    assert batch.estimates[0].status == EvidenceStatus.SIMULATED
    assert batch.estimate_provenance[0]["coordinate_frame"] == "ENU_LOCAL"
    assert batch.report.input_observations == 3
    assert batch.report.converted_observations == 3
    assert batch.report.skipped == 0
    assert batch.report.non_received_observations == 2


def test_empty_valid_runner_result_converts_to_empty_batch(result):
    result["observations"] = []
    result["locations"] = []
    result["id_mappings"] = []
    batch = convert_result(result)
    assert batch.observations == batch.estimates == ()
    assert batch.report.input_observations == batch.report.input_locations == 0
    assert batch.report.converted_observations == batch.report.converted_estimates == 0


def test_received_power_requires_explicit_opt_in(result):
    default = convert_result(result)
    mapped = convert_result(result, map_received_power_to_rssi=True)
    assert default.observations[0].rssi_dbm is None
    assert mapped.observations[0].rssi_dbm == -74.2
    assert mapped.observation_provenance[0]["rssi_source"] == "received_power_dbm_explicitly_mapped"
    assert "SIMULATED" in mapped.report.warnings[-1]


@pytest.mark.parametrize("key", ["snr_db", "propagation_delay_s", "phase_rad"])
def test_optional_metrics_remain_null(result, key):
    result["observations"][0]["metrics"][key] = None
    observation = convert_result(result).observations[0]
    attr = {"propagation_delay_s": "tof_ns"}.get(key, key)
    assert getattr(observation, attr) is None


def test_bad_mapping_and_ambiguous_mapping_rejected(result):
    result["observations"][0]["tag_id"] = "wrong-tag"
    with pytest.raises(ConversionError, match="conflicting mapped identity"):
        convert_result(result)
    result["observations"][0]["tag_id"] = "tag-riose-01"
    result["id_mappings"].append(dict(result["id_mappings"][0], source_id="other-tx"))
    with pytest.raises(ConversionError, match="conflicting RIOSE identity"):
        convert_result(result)


def test_strict_and_lenient_invalid_identity_handling(result):
    result["observations"][0]["tag_id"] = "wrong-tag"
    with pytest.raises(ConversionError):
        convert_result(result)
    batch = convert_result(result, policy=ConversionPolicy.LENIENT)
    assert batch.report.rejected == 1
    assert batch.report.converted_observations == 2
    assert batch.report.reasons


def test_validated_evidence_nonfinite_and_no_path_inconsistency_rejected(result):
    result["observations"][0]["status"] = "VALIDATED"
    with pytest.raises(ConversionError, match="SIMULATED"):
        convert_result(result)
    result["observations"][0]["status"] = "SIMULATED"
    result["observations"][0]["metrics"]["snr_db"] = float("nan")
    with pytest.raises(ConversionError):
        convert_result(result)
    result["observations"][0]["metrics"]["snr_db"] = float("inf")
    with pytest.raises(ConversionError):
        convert_result(result)
    result["observations"][0]["metrics"]["snr_db"] = None
    result["observations"][0]["metrics"]["propagation_delay_s"] = -1e-9
    with pytest.raises(ConversionError, match="must be >= 0"):
        convert_result(result)


def test_packet_received_with_no_path_is_rejected(result):
    row = result["observations"][1]
    row["rx_state"] = "RECEIVED"
    with pytest.raises(ConversionError, match="NO_PATH cannot have rx_state RECEIVED"):
        convert_result(result)


@pytest.mark.parametrize(("metric", "value", "message"), [
    ("received_power_dbm", 500, "must be <= 100"),
    ("snr_db", 101, "must be <= 100"),
    ("phase_rad", 4, "principal radians"),
])
def test_absurd_radio_metrics_and_nonprincipal_phase_rejected(result, metric, value, message):
    result["observations"][0]["metrics"][metric] = value
    with pytest.raises(ConversionError, match=message):
        convert_result(result)


def test_duplicate_and_out_of_order_link_records_are_rejected(result):
    result["observations"].append(dict(result["observations"][0]))
    with pytest.raises(ConversionError, match="duplicates"):
        convert_result(result)
    result["observations"].pop()
    later = dict(result["observations"][0], timestamp_s=2.0)
    result["observations"] = [later, result["observations"][0]]
    with pytest.raises(ConversionError, match="out of order"):
        convert_result(result)


def test_run_manifest_backend_and_hash_conflicts_are_rejected(result):
    manifest = {
        "campaign_id": result["campaign_id"], "backend_used": result["backend"],
        "evidence_classification": "SIMULATED",
        "engine": {"actual_sha": result["solver_version"]},
        "output_sha256": result["provenance"]["output_sha256"],
        "request_sha256": result["provenance"]["request_sha256"],
    }
    assert convert_result(result, run_manifest=manifest).observations
    manifest["backend_used"] = "different-backend"
    with pytest.raises(ConversionError, match="conflicts with run manifest"):
        convert_result(result, run_manifest=manifest)
    manifest["backend_used"] = result["backend"]
    manifest["output_sha256"] = "0" * 64
    with pytest.raises(ConversionError, match="conflicts with run manifest"):
        convert_result(result, run_manifest=manifest)


def test_location_frame_and_estimate_are_retained_without_ground_truth_leakage(result):
    batch = convert_result(result)
    assert len(batch.estimates) == 1
    assert batch.estimates[0].x == 12.2 and batch.estimates[0].y == 7.4
    assert batch.estimate_provenance[0]["source_z_m"] == 1.2
    result["locations"] = []
    # Ground truth is not a result field and cannot be substituted for locations.
    result["ground_truth"] = [{"tag_id": "tag-riose-01", "position_m": [1, 2, 3]}]
    with pytest.raises(ConversionError, match="unsupported fields"):
        convert_result(result)


def test_round_trip_canonical_dataclass_serialization(result):
    from dataclasses import asdict
    from riose.products.livestock_tracking.domain.contracts import RFObservation

    batch = convert_result(result)
    restored = RFObservation(**asdict(batch.observations[0]))
    assert restored == batch.observations[0]
