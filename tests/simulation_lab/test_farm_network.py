from copy import deepcopy
import hashlib
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
    _quality_assessment,
    _score_after_estimation,
    _summary_markdown,
    _validate_operational_bounds,
    _validate_localization_result,
    _validate_network_result,
    _validate_temporal_rows,
)


ROOT = Path(__file__).parents[2]


def request_doc():
    return load_json((ROOT / "examples" / "farm_rf_v1.json").read_text(encoding="utf-8"), kind="request")


def not_transmitted_network(request):
    settings = request["solver"]["parameters"]["network"]
    tag_by_ref = {tag["tag_ref"]: tag for tag in request["tags"]}
    sequences = {}
    packets = []
    events = []
    for index, sample in enumerate(request["trajectory"]["samples"]):
        tag = tag_by_ref[sample["tag_ref"]]
        sequence = sequences.get(sample["tag_ref"], 0)
        sequences[sample["tag_ref"]] = sequence + 1
        request_id = sample.get("request_id") or "req-" + hashlib.sha256(
            f"{request.get('campaign_id', 'campaign')}:{request.get('scenario_id', 'scenario')}:{request.get('seed', 0)}:{sample['tag_ref']}:{sequence}".encode()).hexdigest()[:24]
        animal = tag["animal_ref"]
        timestamp = float(sample["timestamp_s"])
        phase_hash = hashlib.sha256(f"{request['seed']}:{animal}".encode()).digest()
        scheduled = timestamp + int.from_bytes(phase_hash[:8], "big") / 2**64 * settings["traffic_interval_s"]
        packets.append({"event_index": index, "packet_id": request_id, "request_id": request_id,
                        "sequence_number": sequence, "animal_id": animal,
                        "run_id": None, "scenario_id": request["scenario_id"],
                        "campaign_id": request["campaign_id"], "tag_id": tag["tag_ref"],
                        "device_id": tag["device_ref"],
                        "transmitter_id": tag["transmitter_ref"],
                        "timestamp_s": timestamp, "requested_timestamp_s": timestamp,
                        "scheduled_timestamp_s": scheduled, "tx_start_s": None, "airtime_s": None,
                        "tx_outcome": "NOT_TRANSMITTED", "drop_reason": "NO_PHY_TX_OBSERVED",
                        "packet_uid": None, "received_gateway_ids": []})
        for receiver in request["receivers"]:
            events.append({"event_index": index, "packet_id": request_id, "request_id": request_id,
                           "sequence_number": sequence, "animal_id": animal,
                           "run_id": None, "scenario_id": request["scenario_id"],
                           "campaign_id": request["campaign_id"], "tag_id": tag["tag_ref"],
                           "device_id": tag["device_ref"],
                           "transmitter_id": tag["transmitter_ref"],
                           "timestamp_s": timestamp, "requested_timestamp_s": timestamp,
                           "scheduled_timestamp_s": scheduled, "gateway_id": receiver["gateway_ref"],
                           "tx_outcome": "NOT_TRANSMITTED", "tx_start_s": None, "packet_uid": None,
                           "outcome": "NOT_TRANSMITTED"})
    return {"network_backend": "ns-3.48/lorawan-v0.3.7", "channel_backend": "sionna-rt",
            "run_id": None, "scenario_id": request["scenario_id"], "campaign_id": request["campaign_id"],
            "classification": "SIMULATED_NETWORK_FROM_SIONNA", "frequency_hz": request["radio"]["frequency_hz"],
            "tx_power_dbm": request["radio"]["tx_power_dbm"], "sf": settings["spreading_factor"],
            "payload_bytes": settings["payload_bytes"], "traffic_interval_s": settings["traffic_interval_s"],
            "traffic_phase_window_s": settings["traffic_interval_s"],
            "traffic_schedule": "source_timestamp_plus_seeded_device_phase_window", "seed": request["seed"],
            "time_resolution_ps": 1, "packets": packets, "gateway_events": events,
            "metrics": {"requested_packets": len(packets), "transmitted_packets": 0,
                        "not_transmitted_packets": len(packets), "requested_count": len(packets),
                        "transmitted_count": 0, "not_transmitted_count": len(packets),
                        "delivered_packets": 0, "pdr": None}}


def mark_transmitted(network, index):
    packet = network["packets"][index]
    packet.update(tx_start_s=packet["scheduled_timestamp_s"], airtime_s=0.05,
                  tx_outcome="TRANSMITTED", drop_reason=None, packet_uid=index,
                  received_gateway_ids=[])
    for event in network["gateway_events"]:
        if event["event_index"] == index:
            event.update(outcome="RX", tx_outcome="TRANSMITTED",
                         tx_start_s=packet["tx_start_s"], packet_uid=packet["packet_uid"])
            packet["received_gateway_ids"].append(event["gateway_id"])
    transmitted = sum(row["tx_outcome"] == "TRANSMITTED" for row in network["packets"])
    delivered = sum(bool(row["received_gateway_ids"]) for row in network["packets"])
    network["metrics"].update(transmitted_packets=transmitted,
                              not_transmitted_packets=len(network["packets"]) - transmitted,
                              transmitted_count=transmitted,
                              not_transmitted_count=len(network["packets"]) - transmitted,
                              delivered_packets=delivered,
                              pdr=delivered / transmitted if transmitted else None)
    return packet


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
    network = not_transmitted_network(request)
    network["gateway_events"][0]["gateway_id"] = "GW-UNKNOWN"
    with pytest.raises(RunnerError, match="unknown packet or gateway"):
        _validate_network_result(request, network)


def test_network_packets_must_match_requested_trajectory_identity_and_time():
    request = request_doc()
    network = not_transmitted_network(request)
    packets = network["packets"]
    events = network["gateway_events"]
    packets[0]["timestamp_s"] = 100.0
    for event in events:
        if event["event_index"] == 0:
            event["timestamp_s"] = 100.0
    with pytest.raises(RunnerError, match="does not match a requested trajectory sample"):
        _validate_network_result(request, network)


@pytest.mark.parametrize("field,value,match", [
    ("request_id", "req-wrong", "request identity"),
    ("device_id", "device-wrong", "identity"),
    ("scheduled_timestamp_s", -1.0, "scheduled timestamp"),
])
def test_network_packet_identity_and_schedule_are_bound_to_request(field, value, match):
    request = request_doc()
    network = not_transmitted_network(request)
    network["packets"][0][field] = value
    with pytest.raises(RunnerError, match=match):
        _validate_network_result(request, network)


def test_network_packet_uids_must_be_unique():
    request = request_doc()
    network = not_transmitted_network(request)
    first = mark_transmitted(network, 0)
    second = mark_transmitted(network, 1)
    second["packet_uid"] = first["packet_uid"]
    for event in network["gateway_events"]:
        if event["request_id"] == second["request_id"]:
            event["packet_uid"] = first["packet_uid"]
    with pytest.raises(RunnerError, match="PHY UID"):
        _validate_network_result(request, network)


@pytest.mark.parametrize("offset_s,valid", [(-1e-12, True), (-2e-12, False)])
def test_tx_start_validation_respects_ns3_one_picosecond_resolution(offset_s, valid):
    request = request_doc()
    network = not_transmitted_network(request)
    packet = mark_transmitted(network, 0)
    packet["tx_start_s"] = packet["scheduled_timestamp_s"] + offset_s
    for event in network["gateway_events"]:
        if event["request_id"] == packet["request_id"]:
            event["tx_start_s"] = packet["tx_start_s"]
    if valid:
        _validate_network_result(request, network)
    else:
        with pytest.raises(RunnerError, match="valid TX time"):
            _validate_network_result(request, network)


@pytest.mark.parametrize("field,value", [("device_id", "foreign-device"),
                                          ("transmitter_id", "foreign-tx"),
                                          ("campaign_id", "foreign-campaign")])
def test_gateway_event_identity_must_match_its_packet(field, value):
    request = request_doc()
    network = not_transmitted_network(request)
    mark_transmitted(network, 0)
    network["gateway_events"][0][field] = value
    with pytest.raises(RunnerError, match="does not match its packet identity"):
        _validate_network_result(request, network)


def test_not_transmitted_request_cannot_have_gateway_rx():
    request = request_doc()
    network = not_transmitted_network(request)
    network["gateway_events"][0]["outcome"] = "RX"
    with pytest.raises(RunnerError, match="contradicts the packet TX outcome"):
        _validate_network_result(request, network)


def test_temporal_rows_must_match_full_packet_and_gateway_identity():
    request = request_doc()
    request["receivers"] = request["receivers"][:1]
    network = not_transmitted_network(request)
    packet = mark_transmitted(network, 0)
    event = network["gateway_events"][0]
    temporal = {"packet_id": packet["request_id"], "request_id": packet["request_id"],
                "sequence_number": packet["sequence_number"], "run_id": packet["run_id"],
                "scenario_id": packet["scenario_id"], "campaign_id": packet["campaign_id"],
                "animal_id": packet["animal_id"], "tag_id": packet["tag_id"],
                "device_id": packet["device_id"], "transmitter_id": packet["transmitter_id"],
                "timestamp_s": packet["timestamp_s"],
                "requested_timestamp_s": packet["requested_timestamp_s"],
                "scheduled_timestamp_s": packet["scheduled_timestamp_s"],
                "tx_start_s": packet["tx_start_s"], "packet_uid": packet["packet_uid"],
                "gateway_id": event["gateway_id"], "network_outcome": event["outcome"],
                "classification": "SIMULATED", "clock_timestamp_s": packet["tx_start_s"]}
    _validate_temporal_rows(network, [temporal])
    temporal["animal_id"] = "foreign-animal"
    with pytest.raises(RunnerError, match="temporal artifact identity/time"):
        _validate_temporal_rows(network, [temporal])


def test_failed_localization_cannot_smuggle_a_coordinate():
    request = request_doc()
    network = not_transmitted_network(request)
    packet = mark_transmitted(network, 0)
    localization = {"estimates": [{"packet_id": packet["request_id"], "device_id": "device-001",
                                   "tdoa_status": "LT3_TIMESTAMPS", "tdoa_position_m": [0, 0]}],
                    "metrics": localization_metrics()}
    with pytest.raises(RunnerError, match="failed.*must not contain"):
        _validate_localization_result(request, network, localization)


def test_two_gateway_tdoa_failure_is_reported_without_a_position():
    request = deepcopy(request_doc())
    request["receivers"] = request["receivers"][:2]
    request["trajectory"]["samples"] = request["trajectory"]["samples"][:1]
    network = not_transmitted_network(request)
    packet = mark_transmitted(network, 0)
    localization = {"estimates": [{"packet_id": packet["request_id"], "device_id": "device-001",
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
    assert result["locations"][0]["solver_status"] == "LT3_TIMESTAMPS"
    assert result["locations"][0]["quality_status"] == "NOT_EVALUATED"


def test_localization_estimate_device_must_match_packet_animal():
    request = deepcopy(request_doc())
    second = deepcopy(request["tags"][0])
    second.update(tag_ref="riose-tag-002", transmitter_ref="tx-002",
                  animal_ref="animal-002", device_ref="device-002")
    request["tags"].append(second)
    network = not_transmitted_network(request)
    packet = mark_transmitted(network, 0)
    localization = {"estimates": [{"packet_id": packet["request_id"], "device_id": "device-002",
                                   "tdoa_status": "SOLVER_FAILED", "tdoa_position_m": None}]}
    with pytest.raises(RunnerError, match="does not match its packet animal/device identity"):
        _validate_localization_result(request, network, localization)


def test_localization_requires_complete_packet_set_and_consistent_metrics():
    request = request_doc()
    network = not_transmitted_network(request)
    network["packets"] = network["packets"][:2]
    first_packet = mark_transmitted(network, 0)
    second_packet = mark_transmitted(network, 1)
    first = {"packet_id": first_packet["request_id"], "device_id": "device-001", "tdoa_status": "NO_PACKET",
             "tdoa_position_m": None}
    with pytest.raises(RunnerError, match="omits packet estimates"):
        _validate_localization_result(request, network,
            {"estimates": [first], "metrics": localization_metrics()})

    estimates = [first, {"packet_id": second_packet["request_id"], "device_id": "device-001",
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
    payload = _network_input(request, raw, "run-123", "a" * 64)
    row = payload["records"][0]
    assert payload["request"] is request
    assert payload["run_id"] == "run-123"
    assert payload["request_sha256"] == "a" * 64
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
    network = not_transmitted_network(request)
    packet = mark_transmitted(network, 0)
    localization = {"estimates": [{"packet_id": packet["request_id"], "device_id": "device-001",
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
    assert convert_result(result).estimate_provenance[0]["quality_status"] == "NOT_EVALUATED"


def test_ground_truth_is_used_only_by_separate_post_estimation_scoring():
    request = request_doc()
    network = not_transmitted_network(request)
    packet = mark_transmitted(network, 0)
    localization = {"estimates": [{"packet_id": packet["request_id"], "device_id": "device-001",
                                  "tdoa_position_m": [120.0, 200.0], "tdoa_status": "CONVERGED"}],
                    "metrics": {"tdoa": {"eligible_packets": 1, "converged_packets": 1,
                                             "convergence": 1.0}}}
    result = _score_after_estimation(request, network, localization)
    assert result["ground_truth_used_after_estimation"] is True
    assert result["scored"] == 1
    assert result["estimates"][0]["error_m"] == pytest.approx(0.0)
    assert result["estimates"][0]["quality_status"] == "ACCEPTED"
    assert "ground_truth" not in localization["estimates"][0]
    before = deepcopy(localization)
    changed_truth = deepcopy(request)
    changed_truth["trajectory"]["samples"][0]["position_m"] = [999.0, 999.0, 999.0]
    changed_score = _score_after_estimation(changed_truth, network, localization)
    assert localization == before
    assert changed_score["estimates"][0]["error_m"] != result["estimates"][0]["error_m"]
    assert changed_score["estimates"][0]["quality_status"] == result["estimates"][0]["quality_status"]


def test_converged_remote_zero_residual_estimate_is_operationally_rejected():
    request = request_doc()
    network = not_transmitted_network(request)
    packet = mark_transmitted(network, 0)
    for event in network["gateway_events"]:
        if event["request_id"] == packet["request_id"]:
            event["outcome"] = "NO_PATH"
    localization = {"estimates": [{"packet_id": packet["request_id"], "device_id": "device-001",
        "tdoa_position_m": [1248.8757, -4000.8982], "tdoa_status": "CONVERGED",
        "tdoa_residual_rms_m": 8e-14}], "metrics": localization_metrics(1, 1)}
    score = _score_after_estimation(request, network, localization)
    raw = {"snapshots": [{"timestamp_s": sample["timestamp_s"], "records": [
        {"receiver_id": receiver["receiver_ref"], "links": [{"transmitter_id": tag["transmitter_ref"],
         "status": "NO_PATH", "received_power_dbm": None, "paths": []}]}
        for tag in request["tags"] for receiver in request["receivers"]]}
        for sample in request["trajectory"]["samples"]]}
    result = _result(request, raw, {}, {}, "a" * 64, "b" * 64,
                     network, [], localization)
    estimate = result["locations"][0]
    assert estimate["solver_status"] == "CONVERGED"
    assert estimate["quality_status"] == "REJECTED"
    assert estimate["quality_reason"] == "OUTSIDE_DECLARED_OPERATIONAL_BOUNDS"
    assert estimate["position_m"] == [1248.8757, -4000.8982]
    assert score["estimates"][0]["error_m"] is not None


def test_upstream_estimator_receives_no_ground_truth_argument(monkeypatch, tmp_path):
    from riose.simulation_lab.frequencia_network import run_pipeline
    from dataclasses import dataclass

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
    @dataclass(frozen=True)
    class Clock:
        gateway_id: str
        offset_s: float
        drift_ppm: float
        jitter_std_s: float
        quantization_s: float | None

    def clock_network(clocks, **kwargs):
        return types.SimpleNamespace(observe=lambda *args, **kwargs: None,
            _clocks={clock.gateway_id: clock for clock in clocks},
            seed=kwargs["seed"],
            correlated_jitter_std_s=kwargs["correlated_jitter_std_s"],
            timestamp_error_std_s=kwargs["timestamp_error_std_s"])

    module("temporal.clock", ClockModel=Clock, ClockNetwork=clock_network)
    module("temporal.detectors", detect=lambda *args, **kwargs: None)
    module("temporal.phy", DetectionSweep=lambda **kwargs: types.SimpleNamespace(
               noise_density_dbm_hz=-174.0, **kwargs),
           LoRaPhyConfig=lambda **kwargs: types.SimpleNamespace(preamble_symbols=8, **kwargs),
           evaluate_detection=lambda *args: None)

    request = request_doc()
    payload = {"request": request, "records": [], "ns3_root": str(tmp_path),
               "run_id": "run-test", "request_sha256": "a" * 64, "input_sha256": "b" * 64}
    first = run_pipeline(payload, tmp_path)
    assert first["temporal_runtime"]["run_id"] == "run-test"
    assert first["temporal_runtime"]["request_sha256"] == "a" * 64
    assert first["temporal_runtime"]["input_sha256"] == "b" * 64
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
    untransmitted = not_transmitted_network(request)
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
    network = not_transmitted_network(request)
    packet = mark_transmitted(network, 0)
    network["gateway_events"][0]["outcome"] = "INTERFERENCE"
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
        _network_input(request, raw, "run-123", "a" * 64)


def test_effective_temporal_runtime_is_bound_to_run_request_and_values():
    from riose.simulation_lab.farm_rf import _validate_temporal_runtime

    request = request_doc()
    temporal = request["solver"]["parameters"]["temporal"]
    effective = {
        "detector": temporal["detector"], "detector_results": [temporal["detector"]["mode"]],
        "clocks": temporal["clocks"],
        "clock_seed": request["seed"],
        "clock_seed": request["seed"],
        "correlated_jitter_std_s": temporal["correlated_jitter_std_s"],
        "timestamp_error_std_s": temporal["timestamp_error_std_s"],
        "noise_figure_db": temporal["noise_figure_db"],
        "snr_threshold_db": temporal["snr_threshold_db"],
        "detection_margin_db": temporal["detection_margin_db"],
        "max_iterations": temporal["max_iterations"],
    }
    units = {"offset_s": "s", "drift_ppm": "ppm", "jitter_std_s": "s",
             "quantization_s": "s", "correlated_jitter_std_s": "s", "timestamp_error_std_s": "s",
             "threshold_dbm": "dBm", "relative_threshold_db": "dB", "noise_figure_db": "dB",
             "snr_threshold_db": "dB", "detection_margin_db": "dB", "max_iterations": "iterations"}
    runtime = {"schema_version": "riose.simulation.temporal-runtime/v1",
               "run_id": "run-123", "request_sha256": "a" * 64,
               "input_sha256": "b" * 64, "units": units,
               "detector_threshold_semantics": "RELATIVE_TO_STRONGEST_PATH", "effective": effective,
               "effective_defaults": {
                   "phy.preamble_symbols": {"requested": None, "effective": 8, "status": "VERIFIED"},
                   "sweep.noise_density_dbm_hz": {"requested": None, "effective": -174.0,
                                                   "status": "VERIFIED"}}}
    binding = _validate_temporal_runtime(request, runtime, "run-123", "a" * 64, "b" * 64)
    assert binding["status"] == "VERIFIED"
    assert binding["effective"]["detector"]["threshold_dbm"] is None
    absolute_request = deepcopy(request)
    absolute_request["solver"]["parameters"]["temporal"]["detector"]["threshold_dbm"] = 0.0
    runtime["effective"]["detector"] = absolute_request["solver"]["parameters"]["temporal"]["detector"]
    runtime["detector_threshold_semantics"] = "ABSOLUTE_DBM"
    _validate_temporal_runtime(absolute_request, runtime, "run-123", "a" * 64, "b" * 64)
    runtime["effective"]["detector"] = temporal["detector"]
    runtime["detector_threshold_semantics"] = "RELATIVE_TO_STRONGEST_PATH"

    runtime["run_id"] = "another-run"
    with pytest.raises(RunnerError, match="wrong schema, run, or request identity"):
        _validate_temporal_runtime(request, runtime, "run-123", "a" * 64, "b" * 64)
    runtime["run_id"] = "run-123"
    runtime["effective"]["snr_threshold_db"] += 1
    with pytest.raises(RunnerError, match="effective temporal settings differ"):
        _validate_temporal_runtime(request, runtime, "run-123", "a" * 64, "b" * 64)
    runtime["effective"]["snr_threshold_db"] -= 1
    runtime["units"]["offset_s"] = "ns"
    with pytest.raises(RunnerError, match="incorrect units"):
        _validate_temporal_runtime(request, runtime, "run-123", "a" * 64, "b" * 64)
    runtime["units"] = units
    runtime["input_sha256"] = "c" * 64
    with pytest.raises(RunnerError, match="wrong schema, run, or request identity"):
        _validate_temporal_runtime(request, runtime, "run-123", "a" * 64, "b" * 64)


def test_operational_quality_gate_preserves_raw_point_and_never_uses_truth():
    request = request_doc()
    inside = _quality_assessment(request, "CONVERGED", [500.0, 500.0])
    outside = _quality_assessment(request, "CONVERGED", [1248.8, -4000.9])
    failed = _quality_assessment(request, "LT3_TIMESTAMPS", None)
    assert inside["quality_status"] == "ACCEPTED"
    assert outside["quality_status"] == "REJECTED"
    assert outside["quality_reason"] == "OUTSIDE_DECLARED_OPERATIONAL_BOUNDS"
    assert failed["quality_status"] == "NOT_EVALUATED"
    request.pop("operational_bounds_m")
    assert _quality_assessment(request, "CONVERGED", [0.0, 0.0])["quality_status"] == "NOT_EVALUATED"


def test_operational_bounds_must_be_finite_and_increasing():
    request = request_doc()
    request["operational_bounds_m"]["east_max_m"] = request["operational_bounds_m"]["east_min_m"]
    with pytest.raises(ContractError, match="increasing east and north limits"):
        validate_request(request)
    request = request_doc()
    request["operational_bounds_m"]["east_max_m"] = 1001.0
    with pytest.raises(ContractError, match="declared FARM scenario area"):
        _validate_operational_bounds(request, 1000.0)


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
