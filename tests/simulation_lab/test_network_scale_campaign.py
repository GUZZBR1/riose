import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from run_network_scale_campaign import (_packet_loss_summary, _unique_tx_start_count,
                                        build_request, expand_cells)  # noqa: E402
from summarize_network_scale_campaign import _quality_status  # noqa: E402
from riose.simulation_contract import load_json, validate_request  # noqa: E402


def _base_request():
    return load_json((ROOT / "examples" / "farm_rf_v1.json").read_text(encoding="utf-8"), kind="request")


def _cell(schedule, *, epochs=3):
    return {"tags": 10, "gateways": 4, "cadence_s": 10, "schedule": schedule,
            "phase_window_s": None, "sf": 7, "payload_bytes": 12,
            "distribution": "gateway-control", "load_class": "TEST", "epochs": epochs}


def test_controlled_geometry_holds_every_tag_and_epoch_at_single_tag_rf_point():
    request = build_request(_base_request(), _cell("SOURCE_TIMESTAMP", epochs=5), 20261005)
    validate_request(request)
    positions = {tuple(tag["position_m"]) for tag in request["tags"]}
    assert positions == {(120.0, 200.0, 10.78)}
    assert len(request["trajectory"]["samples"]) == 50
    assert {tuple(row["position_m"]) for row in request["trajectory"]["samples"]} == positions
    assert request["solver"]["parameters"]["network"]["traffic_interval_s"] is None


def test_existing_seeded_phase_is_requested_once_downstream_not_baked_into_samples():
    request = build_request(_base_request(), _cell("SEEDED_PHASE", epochs=4), 20261005)
    assert request["solver"]["parameters"]["network"]["traffic_interval_s"] == 10.0
    assert {row["timestamp_s"] for row in request["trajectory"]["samples"]} == {0.0, 10.0, 20.0, 30.0}


@pytest.mark.parametrize("schedule", ["SEEDED_PHASE", "NEAR_SYNCHRONIZED"])
def test_supported_device_phase_schedules_preserve_shared_epochs(schedule):
    cell = _cell(schedule, epochs=10)
    first = build_request(_base_request(), cell, 20261005)
    repeat = build_request(_base_request(), cell, 20261005)
    other_seed = build_request(_base_request(), cell, 20261006)
    first_times = [row["timestamp_s"] for row in first["trajectory"]["samples"]]
    repeated_times = [row["timestamp_s"] for row in repeat["trajectory"]["samples"]]
    other_times = [row["timestamp_s"] for row in other_seed["trajectory"]["samples"]]
    assert first_times == repeated_times
    assert first_times == other_times
    assert len(first_times) == 100
    assert first["solver"]["parameters"]["network"]["traffic_interval_s"] == (
        10.0 if schedule == "SEEDED_PHASE" else 0.01)
    assert len({row["timestamp_s"] for row in first["trajectory"]["samples"]}) == 10
    validate_request(first)


def test_cell_expansion_preserves_epoch_count_and_default_for_old_specs():
    group = {"id": "test", "tags": [2], "gateways": [4], "cadence_s": [10],
             "schedules": ["SOURCE_TIMESTAMP"], "spreading_factors": [7],
             "payload_bytes": [12], "seeds": [1]}
    assert expand_cells({"run_sets": [group]})[0]["epochs"] == 3
    group["epochs"] = 25
    assert expand_cells({"run_sets": [group]})[0]["epochs"] == 25


def test_packet_loss_classes_keep_phy_received_no_path_interference_and_untransmitted_separate():
    network = {"metrics": {"transmitted_packets": 3}, "packets": [
        {"event_index": 0, "tx_start_s": 0.0, "received_gateway_ids": ["GW-1"]},
        {"event_index": 1, "tx_start_s": 1.0, "received_gateway_ids": []},
        {"event_index": 2, "tx_start_s": 2.0, "received_gateway_ids": []},
        {"event_index": 3, "tx_start_s": None, "received_gateway_ids": []},
    ], "gateway_events": [
        {"event_index": 0, "outcome": "RX", "channel_status": "LOS"},
        {"event_index": 0, "outcome": "INTERFERENCE", "channel_status": "LOS"},
        {"event_index": 1, "outcome": "NO_PATH", "channel_status": "NO_PATH"},
        {"event_index": 1, "outcome": "NO_PATH", "channel_status": "NO_PATH"},
        {"event_index": 2, "outcome": "INTERFERENCE", "channel_status": "LOS"},
        {"event_index": 2, "outcome": "NO_PATH", "channel_status": "NO_PATH"},
        {"event_index": 3, "outcome": "NOT_TRANSMITTED", "channel_status": "LOS"},
    ]}
    summary = _packet_loss_summary(network)
    assert summary["counts"] == {"INTERFERENCE_LOSS": 1, "NO_PATH": 1,
                                 "NOT_TRANSMITTED": 1, "PHY_RECEIVED": 1}
    assert summary["requested_packet_denominator"] == 4
    assert summary["tx_packet_denominator"] == 3
    assert summary["rf_reachable_tx_packets"] == 2
    assert summary["rf_reachable_received_packets"] == 1
    assert summary["pdr_conditional_on_rf_path"] == 0.5


def test_actual_transmission_metrics_keep_requested_and_tx_start_denominators_distinct():
    assert _unique_tx_start_count([1.0] * 10) == 1
    assert _unique_tx_start_count([float(i) for i in range(10)]) == 10
    assert _quality_status(1.0, 0.4) == "INCOMPLETE_SCHEDULE_SIMULATED"
    assert _quality_status(1.0, 1.0) == "ROBUST_SIMULATED"


def test_per_packet_jitter_schedule_is_not_silently_treated_as_seeded_device_phase():
    with pytest.raises(ValueError, match="unsupported schedule mode"):
        build_request(_base_request(), _cell("JITTERED"), 20261005)


@pytest.mark.parametrize("epochs", [0, -1, 1.5, True])
def test_epoch_count_must_be_a_positive_integer(epochs):
    with pytest.raises(ValueError, match="positive integer"):
        build_request(_base_request(), _cell("SOURCE_TIMESTAMP", epochs=epochs), 20261005)
