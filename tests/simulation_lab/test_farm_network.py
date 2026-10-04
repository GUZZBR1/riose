from copy import deepcopy
import json
from pathlib import Path
import sys
import types

import pytest

from riose.simulation_adapter import convert_result
from riose.simulation_contract import ContractError, load_json, validate_request
from riose.simulation_lab.farm_rf import (
    RunnerError,
    _network_config,
    _network_input,
    _network_summary,
    _result,
    _score_after_estimation,
    _summary_markdown,
    _validate_localization_result,
    _validate_network_result,
)


ROOT = Path(__file__).parents[2]


def request_doc():
    return load_json((ROOT / "examples" / "farm_rf_v1.json").read_text(encoding="utf-8"), kind="request")


def localization_metrics(eligible=0, converged=0):
    return {"tdoa": {"eligible_packets": eligible, "converged_packets": converged,
                     "convergence": converged / eligible if eligible else None}}


def test_request_explicitly_pins_network_and_temporal_settings():
    request = validate_request(request_doc())
    network, temporal = _network_config(request)
    assert network == {"enabled": True, "spreading_factor": 7,
                       "payload_bytes": 12, "traffic_interval_s": 60.0}
    assert temporal["detector"]["mode"] == "THRESHOLD_DETECTOR"
    assert set(temporal["clocks"]) == {row["gateway_ref"] for row in request["receivers"]}


def test_loss_and_localization_failure_demo_requests_are_valid_and_explicit():
    collision = load_json((ROOT / "examples" / "farm_rf_collision_v1.json").read_text(encoding="utf-8"), kind="request")
    failure = load_json((ROOT / "examples" / "farm_rf_localization_failure_v1.json").read_text(encoding="utf-8"), kind="request")
    validate_request(collision)
    validate_request(failure)
    assert len(collision["tags"]) == 2
    assert collision["solver"]["parameters"]["network"]["traffic_interval_s"] == 0.01
    assert failure["solver"]["parameters"]["temporal"]["detector"]["threshold_dbm"] == 0.0


def test_network_disabled_retains_no_pdr_or_temporal_claim():
    request = request_doc()
    request["solver"]["parameters"]["network"]["enabled"] = False
    request["solver"]["parameters"].pop("temporal")
    network, temporal = _network_config(request)
    assert network["enabled"] is False
    assert temporal is None
    request["solver"]["parameters"]["temporal"] = request_doc()["solver"]["parameters"]["temporal"]
    with pytest.raises(ContractError, match="cannot be enabled"):
        _network_config(request)


def test_network_result_backend_mismatch_fails_closed():
    request = request_doc()
    with pytest.raises(RunnerError, match="backend does not match"):
        _validate_network_result(request, {"network_backend": "different-engine"})


def test_network_result_unknown_gateway_fails_closed():
    request = request_doc()
    settings = request["solver"]["parameters"]["network"]
    packets = [{"event_index": index, "animal_id": "animal-001", "timestamp_s": float(index),
                "tx_start_s": None, "received_gateway_ids": []} for index in range(3)]
    events = [{"event_index": index, "animal_id": "animal-001", "timestamp_s": float(index),
               "gateway_id": ("GW-UNKNOWN" if index == 0 and gateway == 0 else receiver["gateway_ref"]),
               "outcome": "NOT_TRANSMITTED"}
              for index in range(3) for gateway, receiver in enumerate(request["receivers"])]
    network = {"network_backend": "ns-3.48/lorawan-v0.3.7", "channel_backend": "sionna-rt",
               "classification": "SIMULATED_NETWORK_FROM_SIONNA", "frequency_hz": 915000000,
               "tx_power_dbm": 14.0, "sf": settings["spreading_factor"],
               "payload_bytes": settings["payload_bytes"], "traffic_interval_s": settings["traffic_interval_s"],
               "seed": request["seed"], "time_resolution_ps": 1, "packets": packets,
               "gateway_events": events, "metrics": {}}
    with pytest.raises(RunnerError, match="unknown packet or gateway"):
        _validate_network_result(request, network)


def test_network_packets_must_match_requested_trajectory_identity_and_time():
    request = request_doc()
    settings = request["solver"]["parameters"]["network"]
    packets = [{"event_index": index, "animal_id": "animal-001", "timestamp_s": float(index),
                "tx_start_s": None, "received_gateway_ids": []} for index in range(3)]
    events = [{"event_index": index, "animal_id": "animal-001", "timestamp_s": float(index),
               "gateway_id": receiver["gateway_ref"], "outcome": "NOT_TRANSMITTED"}
              for index in range(3) for receiver in request["receivers"]]
    network = {"network_backend": "ns-3.48/lorawan-v0.3.7", "channel_backend": "sionna-rt",
               "classification": "SIMULATED_NETWORK_FROM_SIONNA", "frequency_hz": 915000000,
               "tx_power_dbm": 14.0, "sf": settings["spreading_factor"],
               "payload_bytes": settings["payload_bytes"], "traffic_interval_s": settings["traffic_interval_s"],
               "seed": request["seed"], "time_resolution_ps": 1, "packets": packets,
               "gateway_events": events,
               "metrics": {"transmitted_packets": 0, "delivered_packets": 0, "pdr": None}}
    packets[0]["timestamp_s"] = 100.0
    for event in events:
        if event["event_index"] == 0:
            event["timestamp_s"] = 100.0
    with pytest.raises(RunnerError, match="does not match a requested trajectory sample"):
        _validate_network_result(request, network)


def test_failed_localization_cannot_smuggle_a_coordinate():
    request = request_doc()
    network = {"packets": [{"event_index": 0, "animal_id": "animal-001", "tx_start_s": 0.0}]}
    localization = {"estimates": [{"packet_id": "0", "device_id": "device-001",
                                   "tdoa_status": "LT3_TIMESTAMPS", "tdoa_position_m": [0, 0]}],
                    "metrics": localization_metrics()}
    with pytest.raises(RunnerError, match="failed.*must not contain"):
        _validate_localization_result(request, network, localization)


def test_two_gateway_tdoa_failure_is_reported_without_a_position():
    request = deepcopy(request_doc())
    request["receivers"] = request["receivers"][:2]
    request["trajectory"]["samples"] = request["trajectory"]["samples"][:1]
    network = {"packets": [{"event_index": 0, "animal_id": "animal-001", "timestamp_s": 0.0,
                            "tx_start_s": 1.0}],
               "gateway_events": [{"event_index": 0, "animal_id": "animal-001", "timestamp_s": 0.0,
                                   "gateway_id": gateway, "outcome": "RX"}
                                  for gateway in ("GW-1", "GW-2")]}
    localization = {"estimates": [{"packet_id": "0", "device_id": "device-001",
                                  "tdoa_position_m": None, "tdoa_status": "LT3_TIMESTAMPS"}],
                    "metrics": localization_metrics()}
    _validate_localization_result(request, network, localization)
    raw = {"snapshots": [{"timestamp_s": 0.0, "records": [
        {"receiver_id": f"rx-{gateway}", "links": [{"transmitter_id": "tx-001",
         "status": "LOS", "received_power_dbm": -80.0,
         "paths": [{"delay_s": 1e-7, "coefficient": {"real": 1.0, "imag": 0.0}}]}]}
        for gateway in ("GW-1", "GW-2")]}]}
    result = _result(request, raw, {}, {"repository_provenance": {}}, "a" * 64, "b" * 64,
                     network, [], localization)
    assert result["locations"][0]["position_m"] is None
    assert "LT3_TIMESTAMPS" in result["locations"][0]["method"]


def test_localization_estimate_device_must_match_packet_animal():
    request = deepcopy(request_doc())
    second = deepcopy(request["tags"][0])
    second.update(tag_ref="riose-tag-002", transmitter_ref="tx-002",
                  animal_ref="animal-002", device_ref="device-002")
    request["tags"].append(second)
    network = {"packets": [{"event_index": 0, "animal_id": "animal-001", "timestamp_s": 0.0,
                            "tx_start_s": 0.0}]}
    localization = {"estimates": [{"packet_id": "0", "device_id": "device-002",
                                   "tdoa_status": "SOLVER_FAILED", "tdoa_position_m": None}]}
    with pytest.raises(RunnerError, match="does not match its packet animal/device identity"):
        _validate_localization_result(request, network, localization)


def test_localization_requires_complete_packet_set_and_consistent_metrics():
    request = request_doc()
    network = {"packets": [
        {"event_index": 0, "animal_id": "animal-001", "timestamp_s": 0.0, "tx_start_s": 0.0},
        {"event_index": 1, "animal_id": "animal-001", "timestamp_s": 1.0, "tx_start_s": 1.0},
    ]}
    first = {"packet_id": "0", "device_id": "device-001", "tdoa_status": "NO_PACKET",
             "tdoa_position_m": None}
    with pytest.raises(RunnerError, match="omits packet estimates"):
        _validate_localization_result(request, network,
            {"estimates": [first], "metrics": localization_metrics()})

    estimates = [first, {"packet_id": "1", "device_id": "device-001",
                         "tdoa_status": "SOLVER_FAILED", "tdoa_position_m": None}]
    with pytest.raises(RunnerError, match="metrics disagree with complete estimate statuses"):
        _validate_localization_result(request, network,
            {"estimates": estimates, "metrics": localization_metrics(eligible=1, converged=1)})


def test_network_settings_reject_unknown_gateway_and_invalid_units():
    request = request_doc()
    request["solver"]["parameters"]["temporal"]["clocks"].pop("GW-3")
    with pytest.raises(ContractError, match="exactly one clock"):
        _network_config(request)
    request = request_doc()
    request["solver"]["parameters"]["temporal"]["clocks"]["GW-1"]["jitter_std_s"] = -1
    with pytest.raises(ContractError, match="outside the clock model"):
        _network_config(request)


@pytest.mark.parametrize("field,value", [("drift_ppm", 1e308), ("jitter_std_s", 1e308)])
def test_extreme_clock_drift_or_jitter_is_rejected_before_running(field, value):
    request = request_doc()
    request["solver"]["parameters"]["temporal"]["clocks"]["GW-1"][field] = value
    with pytest.raises(ContractError, match="timestamp horizon"):
        _network_config(request)


def test_network_schedule_near_ns3_timestamp_horizon_is_rejected():
    request = request_doc()
    request["solver"]["parameters"]["network"]["traffic_interval_s"] = 9_000_000.0
    with pytest.raises(ContractError, match="schedule exceeds"):
        _network_config(request)


def test_sionna_links_are_mapped_to_external_network_records_without_recomputing_rf():
    request = request_doc()
    raw = {"snapshots": [{"timestamp_s": 0.0, "records": [{"receiver_id": "rx-GW-1", "links": [
        {"transmitter_id": "tx-001", "status": "NO_PATH", "received_power_dbm": None, "paths": []},
    ]}]}]}
    payload = _network_input(request, raw)
    row = payload["records"][0]
    assert payload["request"] is request
    assert row["animal_id"] == "animal-001"
    assert row["gateway_id"] == "GW-1"
    assert row["tx_position_m"] == request["trajectory"]["samples"][0]["position_m"]
    assert row["los_nlos"] == "NO_PATH"
    assert row["received_power_dbm"] is None
    assert row["paths"] == []


def test_result_keeps_phy_reception_distinct_from_path_and_localization_failure():
    request = deepcopy(request_doc())
    request["receivers"] = request["receivers"][:1]
    request["trajectory"]["samples"] = request["trajectory"]["samples"][:1]
    raw = {"snapshots": [{"timestamp_s": 0.0, "records": [{"receiver_id": "rx-GW-1", "links": [
        {"transmitter_id": "tx-001", "status": "LOS", "received_power_dbm": -80.0,
         "paths": [{"delay_s": 1e-7, "coefficient": {"real": 1.0, "imag": 0.0}}]},
    ]}]}]}
    network = {"network_backend": "ns-3.48/lorawan-v0.3.7", "packets": [
        {"event_index": 0, "animal_id": "animal-001", "timestamp_s": 0.0, "tx_start_s": 1.0}],
        "gateway_events": [{"event_index": 0, "animal_id": "animal-001", "timestamp_s": 0.0,
                            "gateway_id": "GW-1", "outcome": "RX"}]}
    localization = {"estimates": [{"packet_id": "0", "device_id": "device-001",
                                  "tdoa_position_m": None, "tdoa_status": "LT3_TIMESTAMPS"}],
                    "metrics": localization_metrics()}
    result = _result(request, raw, {}, {"repository_provenance": {"sionna_rt_version": "test"}},
                     "a" * 64, "b" * 64, network, [], localization)
    row = result["observations"][0]
    assert row["tx_state"] == "TRANSMITTED"
    assert row["rx_state"] == "PHY_RECEIVED"
    assert row["metrics"]["received_power_dbm"] == -80.0
    assert row["metrics"]["rssi_dbm"] is None
    assert result["locations"][0]["position_m"] is None
    assert "LT3_TIMESTAMPS" in result["locations"][0]["method"]
    assert convert_result(result).observations[0].packet_received is True
    assert convert_result(result).estimates[0].x is None


def test_ground_truth_is_used_only_by_separate_post_estimation_scoring():
    request = request_doc()
    network = {"packets": [{"event_index": 0, "animal_id": "animal-001", "timestamp_s": 0.0}]}
    localization = {"estimates": [{"packet_id": "0", "device_id": "device-001",
                                  "tdoa_position_m": [120.0, 200.0], "tdoa_status": "CONVERGED"}],
                    "metrics": {"tdoa": {"eligible_packets": 1, "converged_packets": 1,
                                             "convergence": 1.0}}}
    result = _score_after_estimation(request, network, localization)
    assert result["ground_truth_used_after_estimation"] is True
    assert result["scored"] == 1
    assert result["estimates"][0]["error_m"] == pytest.approx(0.0)
    assert "ground_truth" not in localization["estimates"][0]
    before = deepcopy(localization)
    changed_truth = deepcopy(request)
    changed_truth["trajectory"]["samples"][0]["position_m"] = [999.0, 999.0, 999.0]
    changed_score = _score_after_estimation(changed_truth, network, localization)
    assert localization == before
    assert changed_score["estimates"][0]["error_m"] != result["estimates"][0]["error_m"]


def test_upstream_estimator_receives_no_ground_truth_argument(monkeypatch, tmp_path):
    from riose.simulation_lab.frequencia_network import run_pipeline

    observed = {}
    def module(name, **attributes):
        value = types.ModuleType(name)
        value.__dict__.update(attributes)
        value.__path__ = []
        monkeypatch.setitem(sys.modules, name, value)
        return value

    module("network")
    module("network.adapter", run=lambda *args, **kwargs: {
        "network_backend": "fixture", "packets": [], "gateway_events": [], "metrics": {}})
    module("localization")
    module("localization.baseline", Gateway=lambda *args: args)
    def estimate(**kwargs):
        observed.update(kwargs)
        return {"estimates": [], "metrics": {"tdoa": {}}}
    module("localization.network_pipeline", evaluate_network_localization=estimate)
    module("temporal")
    module("temporal.clock", ClockModel=lambda **kwargs: kwargs,
           ClockNetwork=lambda *args, **kwargs: types.SimpleNamespace(observe=lambda *args, **kwargs: None))
    module("temporal.detectors", detect=lambda *args, **kwargs: None)
    module("temporal.phy", DetectionSweep=lambda **kwargs: kwargs,
           LoRaPhyConfig=lambda **kwargs: kwargs, evaluate_detection=lambda *args: None)

    request = request_doc()
    payload = {"request": request, "records": [], "ns3_root": str(tmp_path)}
    first = run_pipeline(payload, tmp_path)
    assert "ground_truth" not in observed
    assert "position_m" not in observed
    assert observed["transmissions"] == []

    # The estimator's observation inputs and output are unchanged if scoring truth
    # is removed from the request after the RF/network inputs have been produced.
    observed.clear()
    request_without_truth = deepcopy(request)
    request_without_truth["trajectory"]["samples"] = []
    second = run_pipeline({**payload, "request": request_without_truth}, tmp_path)
    assert "ground_truth" not in observed
    assert first["localization"] == second["localization"]


def test_summary_reports_pdr_null_when_disabled_and_preserves_network_outcomes():
    disabled = _network_summary(None, None, None)
    assert disabled["enabled"] is False
    assert disabled["pdr"] is None
    assert disabled["drops"] is None
    network = {
        "network_backend": "ns-3.48/lorawan-v0.3.7",
        "metrics": {"transmitted_packets": 2, "delivered_packets": 1, "pdr": 0.5,
                    "gateways": {"GW-1": {"received": 1, "attempted": 2, "pdr": 0.5}}},
        "gateway_events": [{"outcome": outcome} for outcome in
                            ("RX", "INTERFERENCE", "NO_PATH", "NOT_TRANSMITTED", "NO_DEMODULATOR")],
    }
    summary = _network_summary(network, {"estimates": []}, None)
    assert summary["pdr"] == 0.5
    assert summary["received_gateway_events"] == 1
    assert summary["collisions"] == 1
    assert summary["drops"] == 2
    assert summary["no_path"] == 1
    assert summary["outcomes"]["NO_PATH"] == 1


def test_zero_and_perfect_pdr_are_preserved_without_inference():
    for value in (0.0, 1.0):
        network = {"metrics": {"transmitted_packets": 1, "delivered_packets": int(value), "pdr": value},
                   "gateway_events": [], "network_backend": "ns-3.48/lorawan-v0.3.7"}
        assert _network_summary(network, None, None)["pdr"] == value
    request = request_doc()
    config = request["solver"]["parameters"]["network"]
    packets = [{"event_index": index, "animal_id": "animal-001", "timestamp_s": float(index),
                "tx_start_s": None, "received_gateway_ids": []} for index in range(3)]
    events = [{"event_index": index, "animal_id": "animal-001", "timestamp_s": float(index),
               "gateway_id": receiver["gateway_ref"], "outcome": "NOT_TRANSMITTED"}
              for index in range(3) for receiver in request["receivers"]]
    untransmitted = {"network_backend": "ns-3.48/lorawan-v0.3.7", "channel_backend": "sionna-rt",
        "classification": "SIMULATED_NETWORK_FROM_SIONNA", "frequency_hz": 915000000,
        "tx_power_dbm": 14.0, "sf": config["spreading_factor"], "payload_bytes": config["payload_bytes"],
        "traffic_interval_s": config["traffic_interval_s"], "seed": request["seed"],
        "time_resolution_ps": 1, "packets": packets, "gateway_events": events,
        "metrics": {"transmitted_packets": 0, "delivered_packets": 0, "pdr": None}}
    _validate_network_result(request, untransmitted)
    assert _network_summary(untransmitted, None, None)["pdr"] is None


def test_human_summary_marks_disabled_network_as_not_applicable():
    text = _summary_markdown(request_doc(), {}, {}, _network_summary(None, None, None), 0.1)
    assert "Evidence status: **SIMULATED**" in text
    assert "Network simulation: disabled" in text
    assert "PDR and network metrics are N/A" in text
    assert "physical hardware timestamp precision" in text


def test_path_can_exist_when_ns3_reports_phy_loss():
    request = deepcopy(request_doc())
    request["receivers"] = request["receivers"][:1]
    request["trajectory"]["samples"] = request["trajectory"]["samples"][:1]
    raw = {"snapshots": [{"timestamp_s": 0.0, "records": [{"receiver_id": "rx-GW-1", "links": [
        {"transmitter_id": "tx-001", "status": "LOS", "received_power_dbm": -90.0,
         "paths": [{"delay_s": 1e-7, "coefficient": {"real": 1.0, "imag": 0.0}}]},
    ]}]}]}
    network = {"packets": [{"event_index": 0, "animal_id": "animal-001", "timestamp_s": 0.0,
                            "tx_start_s": 1.0}],
               "gateway_events": [{"event_index": 0, "animal_id": "animal-001", "timestamp_s": 0.0,
                                   "gateway_id": "GW-1", "outcome": "INTERFERENCE"}]}
    result = _result(request, raw, {}, {"repository_provenance": {}}, "a" * 64, "b" * 64,
                     network, [], {"estimates": []})
    observation = result["observations"][0]
    assert observation["channel_state"] == "PATH"
    assert observation["metrics"]["received_power_dbm"] == -90.0
    assert observation["rx_state"] == "PHY_NOT_RECEIVED"


def test_sionna_result_unknown_ids_fail_closed():
    request = request_doc()
    raw = {"snapshots": [{"timestamp_s": 0.0, "records": [{"receiver_id": "rx-unknown", "links": []}]}]}
    with pytest.raises(RunnerError, match="unmapped receiver"):
        _network_input(request, raw)


def test_multiple_tags_can_share_each_trajectory_timestamp():
    request = request_doc()
    tag = deepcopy(request["tags"][0])
    tag.update(tag_ref="riose-tag-002", transmitter_ref="tx-002",
               animal_ref="animal-002", device_ref="device-002")
    request["tags"].append(tag)
    request["id_mappings"].extend([
        {"source_system": "frequencia", "source_kind": "animal_id", "source_id": "animal-002", "riose_kind": "animal_id", "riose_id": "riose-animal-002"},
        {"source_system": "RIOSE", "source_kind": "device_id", "source_id": "device-002", "riose_kind": "device_id", "riose_id": "riose-device-002"},
        {"source_system": "frequencia", "source_kind": "transmitter_id", "source_id": "tx-002", "riose_kind": "tag_id", "riose_id": "riose-tag-002"},
    ])
    for sample in list(request["trajectory"]["samples"]):
        request["trajectory"]["samples"].append({**sample, "tag_ref": "riose-tag-002",
                                                 "position_m": [sample["position_m"][0] + 1,
                                                                sample["position_m"][1], sample["position_m"][2]]})
    request["trajectory"]["samples"].sort(key=lambda row: (row["timestamp_s"], row["tag_ref"]))
    validate_request(request)


def test_duplicate_timestamp_for_same_tag_is_rejected():
    request = request_doc()
    request["trajectory"]["samples"].insert(1, dict(request["trajectory"]["samples"][0]))
    with pytest.raises(ContractError, match="increase strictly"):
        validate_request(request)
