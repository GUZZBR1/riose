from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from riose.simulation_lab import farm_rf
from riose.simulation_adapter import convert_result
from riose.simulation_contract import ContractError, load_json, validate_request
from riose.simulation_lab.farm_rf import _network_config, _prepare_inputs, _result, _validate_sionna_binding
from riose.simulation_lab.runner import RunnerError, run


ROOT = Path(__file__).parents[2]
REQUEST = ROOT / "examples" / "farm_rf_v1.json"


def request_doc():
    return load_json(REQUEST.read_text(encoding="utf-8"), kind="request")


def single_link_request():
    request = request_doc()
    request["receivers"] = request["receivers"][:1]
    request["trajectory"]["samples"] = request["trajectory"]["samples"][:1]
    return request


def raw_fixture(state: str, power: float | None, paths: list[dict], *, single: bool = False):
    snapshots = []
    for timestamp in ((0.0,) if single else (0.0, 1.0, 2.0)):
        records = []
        for gateway in (("GW-1",) if single else ("GW-1", "GW-2", "GW-3", "GW-4")):
            records.append({"receiver_id": f"rx-{gateway}", "links": [{
                "transmitter_id": "tx-001", "status": state,
                "received_power_dbm": power, "paths": paths,
            }]})
        snapshots.append({"timestamp_s": timestamp, "records": records})
    return {"snapshots": snapshots}


def test_farm_request_has_explicit_identity_and_small_synthetic_route():
    request = validate_request(request_doc())
    assert len(request["tags"]) == 1
    assert len(request["receivers"]) == 4
    assert [row["timestamp_s"] for row in request["trajectory"]["samples"]] == [0.0, 1.0, 2.0]
    assert request["coordinate_frame"] == "ENU_LOCAL"
    assert request["backend"] == "sionna-rt"
    assert {row["source_kind"] for row in request["id_mappings"]} >= {
        "animal_id", "device_id", "transmitter_id", "gateway_id", "receiver_id"}


def test_farm_dispatch_uses_explicit_sionna_runner_without_analytic_fallback(tmp_path):
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request_doc()), encoding="utf-8")
    with patch("riose.simulation_lab.farm_rf.run_farm_sionna", return_value={"status": "SIMULATED"}) as runner:
        assert run(request_path, repo=tmp_path, expected_sha="ba2bdabf003722aae8292580e048f7092d0356d6",
                   dry_run=True) == {"status": "SIMULATED"}
    runner.assert_called_once()
    assert runner.call_args.kwargs["dry_run"] is True


def test_farm_adapter_preserves_channel_power_without_calling_it_rssi():
    request = single_link_request()
    raw = raw_fixture("LOS", -71.0,
                      [{"delay_s": 1.25e-7, "coefficient": {"real": 1.0, "imag": 0.0}}], single=True)
    result = _result(request, raw, {}, {"repository_provenance": {"sionna_rt_version": "test"},
                                         "solver_configuration": {}, "material_provenance": {}},
                    "a" * 64, "b" * 64)
    batch = convert_result(result)
    assert len(batch.observations) == 1
    observation = batch.observations[0]
    assert observation.rssi_dbm is None
    assert observation.snr_db is None
    assert observation.packet_received is False
    assert observation.tof_ns == pytest.approx(125)
    provenance = batch.observation_provenance[0]
    assert provenance["received_power_dbm"] == -71.0
    assert provenance["rx_state"] == "DATA_UNAVAILABLE"
    assert provenance["tof_semantics"] == "SIMULATED_PROPAGATION_DELAY"
    assert provenance["source_system"] == "frequencia"


def test_farm_adapter_keeps_no_path_metrics_null():
    request = single_link_request()
    raw = raw_fixture("NO_PATH", None, [], single=True)
    result = _result(request, raw, {}, {"repository_provenance": {}, "solver_configuration": {},
                                         "material_provenance": {}}, "a" * 64, "b" * 64)
    row = result["observations"][0]
    assert row["channel_state"] == "NO_PATH"
    assert row["metrics"]["received_power_dbm"] is None
    assert row["metrics"]["propagation_delay_s"] is None
    assert row["status"] == "SIMULATED"


def test_farm_adapter_rejects_incomplete_campaign_output():
    request = request_doc()
    raw = {"snapshots": [{"timestamp_s": 0.0, "records": [{"receiver_id": "rx-GW-1", "links": [
        {"transmitter_id": "tx-001", "status": "NO_PATH", "received_power_dbm": None, "paths": []},
    ]}]}]}
    with pytest.raises(RunnerError, match="does not match requested links"):
        _result(request, raw, {}, {"repository_provenance": {}, "solver_configuration": {},
                                   "material_provenance": {}}, "a" * 64, "b" * 64)


@pytest.mark.parametrize("mutation, message", [
    ("duplicate", "duplicate timestamp/tag/receiver"),
    ("wrong_timestamp", "outside the requested trajectory"),
])
def test_farm_adapter_rejects_duplicate_or_unrequested_link_records(mutation, message):
    request = request_doc()
    raw = raw_fixture("LOS", -71.0,
                      [{"delay_s": 1.25e-7, "coefficient": {"real": 1.0, "imag": 0.0}}])
    if mutation == "duplicate":
        raw["snapshots"][0]["records"].append(raw["snapshots"][0]["records"][0])
    else:
        raw["snapshots"][0]["timestamp_s"] = 0.5
    with pytest.raises(RunnerError, match=message):
        _result(request, raw, {}, {"repository_provenance": {}, "solver_configuration": {},
                                   "material_provenance": {}}, "a" * 64, "b" * 64)


def test_farm_request_rejects_unmapped_gateway():
    request = request_doc()
    request["id_mappings"] = [row for row in request["id_mappings"]
                              if not (row["source_kind"] == "gateway_id" and row["source_id"] == "GW-2")]
    with pytest.raises(ContractError, match="gateway_id mapping"):
        validate_request(request)


def test_sionna_binding_records_requested_and_effective_values_and_rejects_divergence():
    request = request_doc()
    summary = {
        "backend": "sionna-rt", "seed": request["seed"],
        "frequency_hz": request["radio"]["frequency_hz"],
        "bandwidth_hz": request["radio"]["bandwidth_hz"],
        "rf_configuration": {"tx_power_dbm": request["radio"]["tx_power_dbm"]},
    }
    solver = {key: value for key, value in request["solver"]["parameters"].items()
              if key in {"max_depth", "samples_per_src", "max_num_paths_per_src",
                         "cfr_points", "los", "specular_reflection"}}
    binding = _validate_sionna_binding(request, summary, {"solver_configuration": solver})
    assert binding["radio_and_backend"]["status"] == "VERIFIED"
    assert binding["radio_and_backend"]["requested"] == binding["radio_and_backend"]["effective"]
    assert binding["solver"]["status"] == "VERIFIED"

    summary["seed"] = 20260929
    with pytest.raises(RunnerError, match="effective seed differs from request"):
        _validate_sionna_binding(request, summary, {"solver_configuration": solver})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("trajectory", {"samples": None, "reference": "external-route.csv"}, "trajectory.reference is unsupported"),
        ("radio", None, "explicit radio.bandwidth_hz"),
    ],
)
def test_farm_rejects_inputs_it_cannot_bind_before_engine_setup(tmp_path, field, value, message):
    request = request_doc()
    if field == "trajectory":
        request[field] = value
    else:
        request[field]["bandwidth_hz"] = value
    validate_request(request)
    with pytest.raises(ContractError, match=message):
        _prepare_inputs(request, tmp_path, tmp_path / "frequencia", "run-1")


def test_farm_output_path_is_confined_to_results_root(tmp_path):
    request = request_doc()
    request["campaign_id"] = "../../.git"
    engine = tmp_path / "frequencia"
    config_path = engine / "configs" / "farm_sionna_smoke.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("""scenario:\n  area_m: 10000\n  seed: 1\n  terrain:\n    relief_amplitude_m: 0\nherd:\n  sample_interval_s: 1\n  animals: 1\n  duration_s: 2\nradio:\n  gateways: []\nsionna: {}\n""", encoding="utf-8")
    with pytest.raises(ContractError, match="ignored results directory"):
        _prepare_inputs(request, tmp_path / "workspace", engine, "run-1")


def test_sionna_failure_after_workspace_creation_writes_failed_manifest(tmp_path, monkeypatch):
    engine = tmp_path / "frequencia"
    (engine / "hub").mkdir(parents=True)
    (engine / "scripts").mkdir()
    (engine / "hub" / "run.py").touch()
    (engine / "scripts" / "run_farm_sionna_experiment.py").touch()
    monkeypatch.setattr(farm_rf, "_engine_inspection", lambda *_args: {
        "path": str(engine), "actual_sha": "a" * 40, "dirty": False,
    })
    monkeypatch.setattr(farm_rf, "_check_inspection", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(farm_rf, "_engine_python", lambda _root: Path("/usr/bin/python3"))
    monkeypatch.setattr(farm_rf, "_prepare_inputs", lambda *_args: (_ for _ in ()).throw(
        RunnerError("controlled input preparation failure")))
    request = request_doc()
    request["input_references"] = []
    with pytest.raises(RunnerError, match="failure manifest") as failure:
        farm_rf.run_farm_sionna(request, "b" * 64, repo=engine,
            expected_sha="a" * 40, output_root=tmp_path / "runs", timeout_seconds=1,
            allow_dirty=False)
    manifest_path = Path(str(failure.value).split("failure manifest: ", 1)[1])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["execution_status"] == "FAILED"
    assert manifest["backend_used"] is None
    assert manifest["exit_code"] is None
    assert manifest["request_sha256"] == "b" * 64


def test_farm_network_route_rejects_trajectory_reference_before_reading_samples():
    request = request_doc()
    request["trajectory"] = {"samples": None, "reference": "external-route.csv"}
    validate_request(request)
    with pytest.raises(ContractError, match="trajectory.reference is unsupported"):
        _network_config(request)


def test_localization_score_separates_noneligible_statuses_and_declares_error_denominator():
    from riose.simulation_lab.farm_rf import _score_after_estimation

    request = request_doc()
    request_ids = ["req-score-1", "req-score-2", "req-score-3"]
    network = {"packets": [
        {"request_id": request_ids[0], "timestamp_s": 0.0},
        {"request_id": request_ids[1], "timestamp_s": 1.0},
        {"request_id": request_ids[2], "timestamp_s": 2.0},
    ]}
    localization = {"estimates": [
        {"packet_id": request_ids[0], "device_id": "device-001", "tdoa_status": "CONVERGED",
         "tdoa_position_m": [125.0, 205.0]},
        {"packet_id": request_ids[1], "device_id": "device-001", "tdoa_status": "SOLVER_FAILED",
         "tdoa_position_m": None},
        {"packet_id": request_ids[2], "device_id": "device-001", "tdoa_status": "LT3_TIMESTAMPS",
         "tdoa_position_m": None},
    ]}
    result = _score_after_estimation(request, network, localization)
    assert result["truth_source"] == "SYNTHETIC_REQUEST_TRAJECTORY_SCORE_ONLY"
    assert (result["attempts"], result["eligible"], result["converged"], result["failed"],
            result["non_eligible"]) == (3, 2, 1, 1, 1)
    assert result["non_eligible_status_counts"] == {"LT3_TIMESTAMPS": 1}
    assert result["truth_matched_attempts"] == 3
    assert result["error_denominator"] == result["scored"] == 1
