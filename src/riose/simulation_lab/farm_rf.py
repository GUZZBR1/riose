"""Dispatch a FARM request to frequencia's existing generic Sionna runner."""

from __future__ import annotations

import csv
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from riose.simulation_contract import ContractError, canonical_json, content_hash, validate_result

from .runner import (
    FREQUENCIA_URL, RunnerError,
    _check_inspection, _controlled_environment, _engine_inspection, _new_workspace,
    _git_provenance, _run_process, _utc_now, _write_json,
)


def _json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"),
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RunnerError(f"required frequencia artifact is missing or malformed: {path.name}") from exc


def _engine_python(engine_root: Path) -> Path:
    candidate = engine_root / ".venv-sionna-agent1" / "bin" / "python"
    if sys.platform == "win32":
        candidate = engine_root / ".venv-sionna-agent1" / "Scripts" / "python.exe"
    if not candidate.is_file():
        raise RunnerError("frequencia Sionna Python environment is missing; Sionna is never replaced by another backend")
    try:
        probe = subprocess.run([str(candidate), "-c",
                                "import importlib.metadata as m; import importlib.util as u; "
                                "assert u.find_spec('sionna') is not None; print(m.version('sionna-rt'))"],
                               cwd=engine_root, env=_controlled_environment(), capture_output=True,
                               text=True, timeout=20, check=False, shell=False)
    except subprocess.TimeoutExpired as exc:
        raise RunnerError("Sionna package availability probe timed out") from exc
    if probe.returncode:
        raise RunnerError("Sionna RT is unavailable in frequencia's configured Python environment")
    return candidate


def _keep_results_out_of_git(engine_root: Path) -> None:
    """Locally exclude generated engine output without editing its source tree."""
    rule = "/results/riose_simulation_lab/"
    try:
        git_dir = Path(subprocess.check_output(
            ["git", "-C", str(engine_root), "rev-parse", "--git-path", "info/exclude"],
            text=True, stderr=subprocess.DEVNULL).strip())
        if not git_dir.is_absolute():
            git_dir = (engine_root / git_dir).resolve()
        existing = git_dir.read_text(encoding="utf-8") if git_dir.is_file() else ""
        if rule not in existing.splitlines():
            git_dir.parent.mkdir(parents=True, exist_ok=True)
            with git_dir.open("a", encoding="utf-8") as stream:
                if existing and not existing.endswith("\n"):
                    stream.write("\n")
                stream.write(rule + "\n")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RunnerError("could not keep generated frequencia results outside normal Git tracking") from exc


def _prepare_inputs(request: dict, workspace: Path, engine_root: Path,
                    run_id: str) -> tuple[Path, Path, Path]:
    if request["trajectory"]["samples"] is None:
        raise ContractError(
            "FARM Sionna requires inline trajectory.samples; trajectory.reference is unsupported"
        )
    if request["radio"]["bandwidth_hz"] is None:
        raise ContractError("FARM Sionna requires an explicit radio.bandwidth_hz")
    try:
        import yaml
    except ImportError as exc:
        raise RunnerError("PyYAML is required to write the existing frequencia ExperimentSpec") from exc
    # Keep the upstream configuration as the source of synthetic geometry and
    # material assumptions. Only campaign dimensions, radio, and explicit IDs
    # are specialized for this request.
    source_config = engine_root / "configs" / "farm_sionna_smoke.yaml"
    if not source_config.is_file():
        raise RunnerError("frequencia FARM Sionna reference config is missing")
    config = yaml.safe_load(source_config.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise RunnerError("frequencia FARM Sionna config is malformed")
    tags = request["tags"]
    receivers = request["receivers"]
    samples = request["trajectory"]["samples"]
    if len(receivers) < 3 or len(receivers) > 8:
        raise ContractError("frequencia FARM V1 requires 3 to 8 explicit gateways")
    tx_expected = [f"tx-{index:03d}" for index in range(1, len(tags) + 1)]
    for index, (tag, expected_tx) in enumerate(zip(tags, tx_expected, strict=True), start=1):
        if tag["transmitter_ref"] != expected_tx:
            raise ContractError(f"FARM transmitter {tag['transmitter_ref']!r} does not match upstream FARM identity {expected_tx!r}")
        if tag.get("animal_ref") != f"animal-{index:03d}":
            raise ContractError("animal_ref does not match the explicitly configured FARM animal")
    gateway_ids = [receiver.get("gateway_ref") for receiver in receivers]
    if any(not isinstance(value, str) or not value for value in gateway_ids) or len(set(gateway_ids)) != len(gateway_ids):
        raise ContractError("every FARM receiver requires a unique, explicitly mapped gateway_ref")
    receiver_by_id = {receiver["receiver_ref"]: receiver for receiver in receivers}
    if any(receiver_id != f"rx-{gateway_id}" for gateway_id in gateway_ids
           for receiver_id, row in receiver_by_id.items() if row.get("gateway_ref") == gateway_id):
        raise ContractError("receiver_ref must match frequencia FARM's explicit rx-<gateway_id> identity")
    for row in receivers:
        if row.get("gateway_ref") is None:
            raise ContractError("each FARM receiver must declare gateway_ref")
    for tag in tags:
        if tag.get("animal_ref") is None:
            raise ContractError("each FARM tag must declare its animal_ref")
    area = float(config["scenario"]["area_m"])
    _validate_operational_bounds(request, area)
    for row in samples:
        if row["tag_ref"] not in {tag["tag_ref"] for tag in tags}:
            raise ContractError("trajectory sample refers to an undeclared tag")
        x, y, _ = row["position_m"]
        if not 0 <= x <= area or not 0 <= y <= area:
            raise ContractError(f"trajectory position lies outside the FARM [0,{area:g}] m scenario bounds")
    for tag in tags:
        first = next((row for row in samples if row["tag_ref"] == tag["tag_ref"]), None)
        if first is None or first["timestamp_s"] != 0 or first["position_m"] != tag["position_m"]:
            raise ContractError(f"tag {tag['tag_ref']!r} initial position must equal its t=0 trajectory sample")
    times = sorted({float(row["timestamp_s"]) for row in samples})
    if not times or times[0] != 0 or any(not value.is_integer() for value in times):
        raise ContractError("FARM Sionna trajectory timestamps must start at zero and be whole seconds")
    if len(times) != len(samples) // len(tags):
        raise ContractError("each tag must have exactly one trajectory sample per timestamp")
    if len(times) > 1:
        intervals = {b - a for a, b in zip(times, times[1:])}
        if len(intervals) != 1:
            raise ContractError("frequencia FARM requires evenly spaced trajectory timestamps")
        config["herd"]["sample_interval_s"] = intervals.pop()
    config["herd"]["animals"] = len(tags)
    config["herd"]["duration_s"] = int(times[-1])
    config["scenario"]["seed"] = request["seed"]
    config["radio"]["frequency_hz"] = request["radio"]["frequency_hz"]
    config["radio"]["bandwidth_hz"] = request["radio"]["bandwidth_hz"]
    config["radio"]["tx_power_dbm"] = request["radio"]["tx_power_dbm"]
    relief = float(config["scenario"]["terrain"]["relief_amplitude_m"])
    config["radio"]["gateways"] = []
    for row in receivers:
        east, north, up = (float(value) for value in row["position_m"])
        ground = relief * (0.55 * math.sin(2 * math.pi * east / area)
                           + 0.45 * math.cos(2 * math.pi * north / area))
        antenna_height = up - ground
        if antenna_height <= 0:
            raise ContractError(f"gateway {row['gateway_ref']!r} lies below the synthetic FARM terrain")
        config["radio"]["gateways"].append(
            {"id": row["gateway_ref"], "position_m": [east, north, antenna_height]})
    sionna_parameters = {"max_depth", "samples_per_src", "max_num_paths_per_src",
                         "cfr_points", "los", "specular_reflection"}
    unsupported = set(request["solver"]["parameters"]) - sionna_parameters - {"network", "temporal"}
    if unsupported:
        raise ContractError(f"unsupported FARM solver parameters: {sorted(unsupported)}")
    parameters = request["solver"]["parameters"]
    for key in ("max_depth", "samples_per_src", "max_num_paths_per_src", "cfr_points"):
        if key in parameters and (not isinstance(parameters[key], int)
                                  or isinstance(parameters[key], bool)
                                  or parameters[key] < (0 if key == "max_depth" else 2 if key == "cfr_points" else 1)):
            raise ContractError(f"solver.parameters.{key} is outside the supported integer range")
    for key in ("los", "specular_reflection"):
        if key in parameters and not isinstance(parameters[key], bool):
            raise ContractError(f"solver.parameters.{key} must be boolean")
    config["sionna"].update({key: value for key, value in request["solver"]["parameters"].items()
                             if key in sionna_parameters})
    source_config_path = workspace / "inputs" / "farm_config.yaml"
    source_config_path.parent.mkdir(parents=True, exist_ok=True)
    source_config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    trajectory_path = workspace / "inputs" / "trajectory.csv"
    tx_by_tag = {row["tag_ref"]: row["transmitter_ref"] for row in tags}
    with trajectory_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("timestamp_s", "transmitter_id", "x_m", "y_m", "z_m"))
        writer.writeheader()
        for row in samples:
            writer.writerow({"timestamp_s": row["timestamp_s"], "transmitter_id": tx_by_tag[row["tag_ref"]],
                             "x_m": row["position_m"][0], "y_m": row["position_m"][1],
                             "z_m": row["position_m"][2]})
    engine_output = (engine_root / "results" / "riose_simulation_lab" /
                     request["campaign_id"] / run_id / "engine").resolve()
    if not engine_output.is_relative_to(engine_root):
        raise ContractError("FARM campaign output must remain inside frequencia's ignored results directory")
    spec_path = workspace / "inputs" / "experiment_spec.yaml"
    spec = {"experiment_id": request["campaign_id"], "environment": "FARM", "backend": "sionna-rt",
            "config": str(source_config_path), "output_dir": str(engine_output),
            "trajectory": str(trajectory_path), "trajectory_source": "SYNTHETIC RIOSE request trajectory",
            "trajectory_frame": "ENU local", "max_snapshots": len(times),
            "rf": {"center_frequency_hz": request["radio"]["frequency_hz"],
                   "bandwidth_hz": request["radio"]["bandwidth_hz"], "seed": request["seed"]}}
    spec_path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return source_config_path, trajectory_path, spec_path


def _network_config(request: dict) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validate the optional external ns-3 and temporal configuration."""
    if request["trajectory"]["samples"] is None:
        raise ContractError("FARM network simulation requires inline trajectory.samples; trajectory.reference is unsupported")
    parameters = request["solver"]["parameters"]
    network = parameters.get("network")
    temporal = parameters.get("temporal")
    if network is None:
        if temporal is not None:
            raise ContractError("temporal settings require an explicit network configuration")
        return None, None
    if not isinstance(network, dict) or set(network) != {
        "enabled", "spreading_factor", "payload_bytes", "traffic_interval_s"
    }:
        raise ContractError("solver.parameters.network must declare enabled, spreading_factor, payload_bytes and traffic_interval_s")
    if not isinstance(network["enabled"], bool):
        raise ContractError("network.enabled must be boolean")
    if not network["enabled"]:
        if temporal is not None:
            raise ContractError("temporal settings cannot be enabled when network.enabled is false")
        return network, None
    if isinstance(network["spreading_factor"], bool) or not isinstance(network["spreading_factor"], int) or not 7 <= network["spreading_factor"] <= 12:
        raise ContractError("network.spreading_factor must be an integer from 7 to 12")
    if isinstance(network["payload_bytes"], bool) or not isinstance(network["payload_bytes"], int) or not 1 <= network["payload_bytes"] <= 51:
        raise ContractError("network.payload_bytes must be an integer from 1 to 51")
    interval = network["traffic_interval_s"]
    if interval is not None and (isinstance(interval, bool) or not isinstance(interval, (int, float))
                                 or not math.isfinite(interval) or interval <= 0):
        raise ContractError("network.traffic_interval_s must be null or a positive finite value in seconds")
    if request["radio"]["bandwidth_hz"] != 125_000:
        raise ContractError("the pinned FREQUENCIA ns-3 adapter currently configures a single 125 kHz channel")
    if not 0 <= request["radio"]["tx_power_dbm"] <= 14:
        raise ContractError("the pinned FREQUENCIA ns-3 adapter supports TX power from 0 through 14 dBm")
    if not 1 <= request["seed"] <= 4_294_967_295:
        raise ContractError("the pinned FREQUENCIA ns-3 adapter requires a positive 32-bit seed")
    if any(float(sample["timestamp_s"]) >= 9_000_000
           for sample in request["trajectory"]["samples"]):
        raise ContractError("FREQUENCIA ns-3 picosecond timestamps must be below 9,000,000 seconds")
    event_horizon_s = max(float(sample["timestamp_s"])
                          for sample in request["trajectory"]["samples"]) + (interval or 0.0) + 10.0
    if not math.isfinite(event_horizon_s) or event_horizon_s >= 9_000_000:
        raise ContractError("network traffic schedule exceeds FREQUENCIA ns-3 timestamp horizon")
    declared_sf = request["radio"]["phy"].get("spreading_factor")
    declared_technology = request["radio"]["phy"].get("technology")
    if declared_technology is not None and declared_technology != "LoRa":
        raise ContractError("FREQUENCIA network adapter only supports the declared LoRa PHY")
    if declared_sf is not None and declared_sf != network["spreading_factor"]:
        raise ContractError("radio.phy.spreading_factor must match network.spreading_factor")
    if not isinstance(temporal, dict) or set(temporal) != {
        "detector", "clocks", "correlated_jitter_std_s", "timestamp_error_std_s",
        "noise_figure_db", "snr_threshold_db", "detection_margin_db", "max_iterations"
    }:
        raise ContractError("temporal settings must explicitly declare detector, clocks, noise and solver parameters")
    detector = temporal["detector"]
    if not isinstance(detector, dict) or set(detector) != {"mode", "threshold_dbm", "relative_threshold_db"}:
        raise ContractError("temporal.detector must declare mode, threshold_dbm and relative_threshold_db")
    if detector["mode"] not in {"ORACLE_FIRST_PATH", "STRONGEST_PATH", "THRESHOLD_DETECTOR"}:
        raise ContractError("unsupported FREQUENCIA detector mode")
    if detector["threshold_dbm"] is not None and (
        isinstance(detector["threshold_dbm"], bool)
        or not isinstance(detector["threshold_dbm"], (int, float))
        or not math.isfinite(detector["threshold_dbm"])
    ):
        raise ContractError("temporal.detector.threshold_dbm must be finite or null")
    if (isinstance(detector["relative_threshold_db"], bool)
            or not isinstance(detector["relative_threshold_db"], (int, float))
            or not math.isfinite(detector["relative_threshold_db"])):
        raise ContractError("temporal.detector.relative_threshold_db must be finite")
    for key in ("correlated_jitter_std_s", "timestamp_error_std_s", "noise_figure_db",
                "snr_threshold_db", "detection_margin_db"):
        value = temporal[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ContractError(f"temporal.{key} must be finite")
    if any(temporal[key] < 0 for key in ("correlated_jitter_std_s", "timestamp_error_std_s",
                                         "noise_figure_db", "detection_margin_db")):
        raise ContractError("temporal jitter, noise figure and detection margin must be non-negative")
    gateway_ids = {row["gateway_ref"] for row in request["receivers"]}
    if not isinstance(temporal["clocks"], dict) or set(temporal["clocks"]) != gateway_ids:
        raise ContractError("temporal.clocks must specify exactly one clock for every configured gateway")
    for gateway, clock in temporal["clocks"].items():
        if not isinstance(clock, dict) or set(clock) != {"offset_s", "drift_ppm", "jitter_std_s", "quantization_s"}:
            raise ContractError(f"clock {gateway} must declare offset_s, drift_ppm, jitter_std_s and quantization_s")
        for key in ("offset_s", "drift_ppm", "jitter_std_s"):
            value = clock[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ContractError(f"clock {gateway}.{key} must be finite")
        if clock["drift_ppm"] <= -1_000_000 or clock["jitter_std_s"] < 0:
            raise ContractError(f"clock {gateway} drift_ppm/jitter_std_s is outside the clock model")
        quantization = clock["quantization_s"]
        if quantization is not None and (isinstance(quantization, bool) or not isinstance(quantization, (int, float))
                                         or not math.isfinite(quantization) or quantization <= 0):
            raise ContractError(f"clock {gateway}.quantization_s must be positive seconds or null")
        clock_rate = 1.0 + float(clock["drift_ppm"]) * 1e-6
        worst_case_timestamp = (event_horizon_s * abs(clock_rate) + abs(float(clock["offset_s"]))
                                + 8.0 * (float(clock["jitter_std_s"])
                                         + float(temporal["correlated_jitter_std_s"])
                                         + float(temporal["timestamp_error_std_s"]))
                                + (float(quantization) if quantization is not None else 0.0))
        if not math.isfinite(worst_case_timestamp) or worst_case_timestamp >= 9_000_000:
            raise ContractError(f"clock {gateway} can exceed the ns-3 timestamp horizon")
    if isinstance(temporal["max_iterations"], bool) or not isinstance(temporal["max_iterations"], int) or temporal["max_iterations"] < 1:
        raise ContractError("temporal.max_iterations must be a positive integer")
    return network, temporal


def _network_input(request: dict, raw: dict, run_id: str, request_hash: str) -> dict[str, Any]:
    """Adapt exact Sionna links plus request geometry to FREQUENCIA's network input."""
    positions = {(row["tag_ref"], float(row["timestamp_s"])): row["position_m"]
                 for row in request["trajectory"]["samples"]}
    tags_by_tx = {row["transmitter_ref"]: row for row in request["tags"]}
    receivers_by_ref = {row["receiver_ref"]: row for row in request["receivers"]}
    records = []
    for snapshot in raw.get("snapshots", []):
        timestamp = float(snapshot["timestamp_s"])
        for receiver in snapshot.get("records", []):
            receiver_ref = str(receiver["receiver_id"])
            if receiver_ref not in receivers_by_ref:
                raise RunnerError(f"Sionna output contains unmapped receiver {receiver_ref!r}")
            receiver_request = receivers_by_ref[receiver_ref]
            for link in receiver.get("links", []):
                transmitter = str(link["transmitter_id"])
                tag = tags_by_tx.get(transmitter)
                if tag is None:
                    raise RunnerError(f"Sionna output contains unmapped transmitter {transmitter!r}")
                position = positions.get((tag["tag_ref"], timestamp))
                if position is None:
                    raise RunnerError(f"Sionna output time {timestamp} is absent from the RIOSE trajectory")
                records.append({
                    "animal_id": tag["animal_ref"], "timestamp_s": timestamp,
                    "gateway_id": receiver_request["gateway_ref"],
                    "tx_position_m": list(position), "rx_position_m": list(receiver_request["position_m"]),
                    "los_nlos": link["status"],
                    "received_power_dbm": link["received_power_dbm"],
                    "paths": link["paths"],
                })
    if not records:
        raise RunnerError("Sionna output contains no channel links for network simulation")
    return {"request": request, "records": records, "run_id": run_id,
            "request_sha256": request_hash}


def _validate_temporal_runtime(request: dict, runtime: dict, run_id: str,
                               request_hash: str, input_hash: str) -> dict[str, Any]:
    """Bind temporal settings to the runtime objects reported by the bridge."""
    if (not isinstance(runtime, dict)
            or runtime.get("schema_version") != "riose.simulation.temporal-runtime/v1"
            or runtime.get("run_id") != run_id
            or runtime.get("request_sha256") != request_hash
            or runtime.get("input_sha256") != input_hash):
        raise RunnerError("FREQUENCIA temporal runtime artifact has the wrong schema, run, or request identity")
    requested = request["solver"]["parameters"].get("temporal")
    effective = runtime.get("effective")
    if not isinstance(requested, dict) or not isinstance(effective, dict):
        raise RunnerError("FREQUENCIA temporal runtime artifact is missing requested or effective settings")
    expected = {
        "detector": requested["detector"],
        "clocks": requested["clocks"],
        "clock_seed": request["seed"],
        "correlated_jitter_std_s": requested["correlated_jitter_std_s"],
        "timestamp_error_std_s": requested["timestamp_error_std_s"],
        "noise_figure_db": requested["noise_figure_db"],
        "snr_threshold_db": requested["snr_threshold_db"],
        "detection_margin_db": requested["detection_margin_db"],
        "max_iterations": requested["max_iterations"],
    }
    if any(effective.get(key) != value for key, value in expected.items()):
        raise RunnerError("FREQUENCIA effective temporal settings differ from the request")
    detector_results = effective.get("detector_results")
    if (not isinstance(detector_results, list)
            or any(value != requested["detector"]["mode"] for value in detector_results)):
        raise RunnerError("FREQUENCIA detector runtime result differs from the requested mode")
    expected_units = {"offset_s": "s", "drift_ppm": "ppm", "jitter_std_s": "s",
        "quantization_s": "s", "correlated_jitter_std_s": "s", "timestamp_error_std_s": "s",
        "threshold_dbm": "dBm", "relative_threshold_db": "dB", "noise_figure_db": "dB",
        "snr_threshold_db": "dB", "detection_margin_db": "dB", "max_iterations": "iterations"}
    if runtime.get("units") != expected_units:
        raise RunnerError("FREQUENCIA temporal runtime artifact uses missing or incorrect units")
    expected_threshold_semantics = ("RELATIVE_TO_STRONGEST_PATH"
                                    if requested["detector"]["threshold_dbm"] is None
                                    else "ABSOLUTE_DBM")
    if runtime.get("detector_threshold_semantics") != expected_threshold_semantics:
        raise RunnerError("FREQUENCIA detector default/override semantics differ from the request")
    defaults = runtime.get("effective_defaults")
    if (not isinstance(defaults, dict)
            or set(defaults) != {"phy.preamble_symbols", "sweep.noise_density_dbm_hz"}
            or any(not isinstance(row, dict) or row.get("requested") is not None
                   or row.get("status") != "VERIFIED" or isinstance(row.get("effective"), bool)
                   or not isinstance(row.get("effective"), (int, float))
                   or not math.isfinite(row["effective"]) for row in defaults.values())
            or type(defaults["phy.preamble_symbols"]["effective"]) is not int):
        raise RunnerError("FREQUENCIA temporal runtime defaults are missing or malformed")
    return {"schema_version": "riose.simulation.temporal-binding/v1",
            "run_id": run_id, "request_sha256": request_hash,
            "input_sha256": input_hash,
            "requested": requested, "forwarded": requested,
            "effective": {key: effective[key] for key in expected},
            "effective_defaults": defaults,
            "observed_detector_modes": detector_results,
            "status": "VERIFIED"}


def _validate_sionna_binding(request: dict, summary: dict, engine_manifest: dict) -> dict[str, Any]:
    """Compare requested Sionna settings with values attested by FREQUENCIA."""
    effective_rf = summary.get("rf_configuration")
    if not isinstance(effective_rf, dict):
        raise RunnerError("FREQUENCIA summary is missing its effective RF configuration")
    requested_radio = request["radio"]
    requested = {
        "backend": request["backend"],
        "seed": request["seed"],
        "frequency_hz": requested_radio["frequency_hz"],
        "bandwidth_hz": requested_radio["bandwidth_hz"],
        "tx_power_dbm": requested_radio["tx_power_dbm"],
    }
    effective = {
        "backend": summary.get("backend"),
        "seed": summary.get("seed"),
        "frequency_hz": summary.get("frequency_hz"),
        "bandwidth_hz": summary.get("bandwidth_hz"),
        "tx_power_dbm": effective_rf.get("tx_power_dbm"),
    }
    for name, requested_value in requested.items():
        if effective[name] != requested_value:
            raise RunnerError(
                f"FREQUENCIA effective {name} differs from request "
                f"(requested={requested_value!r}, effective={effective[name]!r})"
            )

    requested_solver = request["solver"]["parameters"]
    solver_keys = {"max_depth", "samples_per_src", "max_num_paths_per_src",
                   "cfr_points", "los", "specular_reflection"}
    requested_sionna = {key: value for key, value in requested_solver.items() if key in solver_keys}
    effective_solver = engine_manifest.get("solver_configuration")
    if not isinstance(effective_solver, dict) or any(
        effective_solver.get(key) != value for key, value in requested_sionna.items()
    ):
        raise RunnerError("FREQUENCIA effective Sionna solver settings differ from the request")

    return {
        "schema_version": "riose.simulation.parameter-binding/v1",
        "request_sha256": content_hash(request),
        "radio_and_backend": {"requested": requested, "effective": effective, "status": "VERIFIED"},
        "solver": {"requested": requested_sionna, "effective": effective_solver,
                   "status": "VERIFIED"},
    }


def _quality_assessment(request: dict, solver_status: str,
                        position: list[float] | None) -> dict[str, Any]:
    """Gate a raw solver estimate against only explicitly declared farm bounds."""
    bounds = request.get("operational_bounds_m")
    if position is None:
        return {"quality_status": "NOT_EVALUATED", "quality_reason": f"NO_NUMERICAL_POSITION:{solver_status}",
                "quality_bounds_m": bounds}
    if bounds is None:
        return {"quality_status": "NOT_EVALUATED", "quality_reason": "NO_DECLARED_OPERATIONAL_BOUNDS",
                "quality_bounds_m": None}
    inside = (bounds["east_min_m"] <= position[0] <= bounds["east_max_m"]
              and bounds["north_min_m"] <= position[1] <= bounds["north_max_m"])
    return {"quality_status": "ACCEPTED" if inside else "REJECTED",
            "quality_reason": "WITHIN_DECLARED_OPERATIONAL_BOUNDS" if inside
                              else "OUTSIDE_DECLARED_OPERATIONAL_BOUNDS",
            "quality_bounds_m": bounds}


def _validate_operational_bounds(request: dict, scenario_area_m: float) -> None:
    """Keep the declared operational box inside the pinned square FARM region."""
    bounds = request.get("operational_bounds_m")
    if bounds is not None and any(value < 0 or value > scenario_area_m for value in bounds.values()):
        raise ContractError("operational_bounds_m must stay within the declared FARM scenario area")


def _score_after_estimation(request: dict, network: dict, localization: dict) -> dict[str, Any]:
    """Score TDoA estimates only after FREQUENCIA's estimator returns."""
    truth = {(str(sample["tag_ref"]), float(sample["timestamp_s"])): sample["position_m"]
             for sample in request["trajectory"]["samples"]}
    tags_by_device = {str(tag["device_ref"]): tag for tag in request["tags"]}
    packets = {str(packet["event_index"]): packet for packet in network.get("packets", [])}
    rows = []
    errors = []
    for estimate in localization.get("estimates", []):
        packet = packets.get(str(estimate.get("packet_id")))
        tag = tags_by_device.get(str(estimate.get("device_id")))
        if packet is None or tag is None:
            raise RunnerError("TDoA scoring references an unknown packet or RIOSE tag")
        point = truth.get((tag["tag_ref"], float(packet["timestamp_s"])))
        position = estimate.get("tdoa_position_m")
        error = None
        if point is not None and position is not None:
            error = math.hypot(float(position[0]) - float(point[0]),
                               float(position[1]) - float(point[1]))
            if not math.isfinite(error):
                raise RunnerError("TDoA scoring produced a non-finite error")
            errors.append(error)
        quality = _quality_assessment(request, str(estimate.get("tdoa_status")),
                                      [float(position[0]), float(position[1])] if position is not None else None)
        rows.append({"packet_id": str(estimate["packet_id"]), "tag_id": tag["tag_ref"],
                     "timestamp_s": float(packet["timestamp_s"]),
                     "tdoa_status": estimate.get("tdoa_status"),
                     "quality_status": quality["quality_status"],
                     "quality_reason": quality["quality_reason"], "error_m": error})
    ordered = sorted(errors)
    median = (ordered[len(ordered) // 2] if len(ordered) % 2 else
              (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2) if ordered else None
    estimates = localization.get("estimates", [])
    attempts = len(estimates)
    eligible = sum(estimate.get("tdoa_status") in {"CONVERGED", "SOLVER_FAILED"}
                   for estimate in estimates)
    converged = sum(estimate.get("tdoa_status") == "CONVERGED" for estimate in estimates)
    return {"schema_version": "riose.simulation.localization-score/v1",
            "ground_truth_used_after_estimation": True, "attempts": attempts,
            "eligible": eligible,
            "converged": converged, "failed": attempts - converged,
        "quality_counts": {status: sum(row["quality_status"] == status for row in rows)
                           for status in ("ACCEPTED", "REJECTED", "NOT_EVALUATED")},
            "convergence_rate": converged / eligible if eligible else None, "scored": len(errors),
            "conditional_rmse_m": math.sqrt(sum(value * value for value in errors) / len(errors)) if errors else None,
            "median_error_m": median,
            "p90_error_m": (ordered[min(len(ordered) - 1, math.ceil(0.9 * len(ordered)) - 1)]
                            if ordered else None),
            "estimates": rows}


def _network_summary(network: dict | None, localization: dict | None,
                     scoring: dict | None) -> dict[str, Any]:
    """Summarize only reported engine values; unavailable simulation stays null."""
    if network is None:
        return {"enabled": False, "transmitted_packets": None, "received_gateway_events": None,
                "delivered_packets": None, "drops": None, "collisions": None, "pdr": None,
                "no_path": None, "not_transmitted": None,
                "outcomes": None, "gateways": None, "localization": None}
    metrics = network.get("metrics", {})
    events = network.get("gateway_events", [])
    outcomes: dict[str, int] = {}
    for event in events:
        outcome = str(event.get("outcome", "UNKNOWN"))
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    drops = sum(outcomes.get(outcome, 0) for outcome in
                ("INTERFERENCE", "UNDER_SENSITIVITY", "NO_DEMODULATOR", "UNTRACED_DROP"))
    return {"enabled": True,
            "network_backend": network.get("network_backend"),
            "frequency_hz": network.get("frequency_hz"), "bandwidth_hz": 125_000,
            "spreading_factor": network.get("sf"), "tx_power_dbm": network.get("tx_power_dbm"),
            "payload_bytes": network.get("payload_bytes"),
            "transmitted_packets": metrics.get("transmitted_packets"),
            "received_gateway_events": outcomes.get("RX", 0),
            "delivered_packets": metrics.get("delivered_packets"),
            "drops": drops, "collisions": outcomes.get("INTERFERENCE", 0),
            "no_path": outcomes.get("NO_PATH", 0),
            "not_transmitted": outcomes.get("NOT_TRANSMITTED", 0),
            "pdr": metrics.get("pdr"), "outcomes": outcomes,
            "gateways": metrics.get("gateways"),
            "localization": None if scoring is None else {
                "method": "FREQUENCIA TDoA",
                "attempts": scoring.get("attempts"), "eligible": scoring.get("eligible"),
                "converged": scoring.get("converged"), "failed": scoring.get("failed"),
                "convergence_rate_among_eligible": scoring.get("convergence_rate"),
                "quality_counts": scoring.get("quality_counts"),
                "conditional_rmse_m": scoring.get("conditional_rmse_m"),
                "median_error_m": scoring.get("median_error_m"),
                "p90_error_m": scoring.get("p90_error_m"),
                "coordinate_frame": "ENU_LOCAL", "gateway_count": len(metrics.get("gateways", {})),
            }}


def _validate_network_result(request: dict, network: dict) -> None:
    """Reject mismatched, inconsistent or fabricated network artifacts."""
    if network.get("network_backend") != "ns-3.48/lorawan-v0.3.7":
        raise RunnerError("FREQUENCIA network artifact backend does not match pinned ns-3/LoRaWAN")
    if network.get("channel_backend") != "sionna-rt" or network.get("classification") != "SIMULATED_NETWORK_FROM_SIONNA":
        raise RunnerError("FREQUENCIA network artifact does not attest Sionna-derived simulated input")
    config, _ = _network_config(request)
    expected = {"frequency_hz": request["radio"]["frequency_hz"],
                "tx_power_dbm": request["radio"]["tx_power_dbm"],
                "sf": config["spreading_factor"], "payload_bytes": config["payload_bytes"],
                "traffic_interval_s": config["traffic_interval_s"], "seed": request["seed"]}
    if any(network.get(key) != value for key, value in expected.items()):
        raise RunnerError("FREQUENCIA network artifact parameters differ from the requested experiment")
    if network.get("time_resolution_ps") != 1:
        raise RunnerError("FREQUENCIA network artifact has an unexpected ns-3 time resolution")
    packets, events = network.get("packets"), network.get("gateway_events")
    metrics = network.get("metrics")
    if not isinstance(packets, list) or not isinstance(events, list) or not isinstance(metrics, dict):
        raise RunnerError("FREQUENCIA network artifact is missing packet, gateway event or metric arrays")
    tags_by_ref = {tag["tag_ref"]: tag for tag in request["tags"]}
    expected_packet_identities = {
        (tags_by_ref[sample["tag_ref"]]["animal_ref"], float(sample["timestamp_s"]))
        for sample in request["trajectory"]["samples"]
    }
    expected_packets = len(expected_packet_identities)
    if len(packets) != expected_packets:
        raise RunnerError("FREQUENCIA network artifact packet count differs from the trajectory")
    packet_index: dict[str, dict] = {}
    packet_identities: set[tuple[str, float]] = set()
    for packet in packets:
        event_id = packet.get("event_index")
        if isinstance(event_id, bool) or not isinstance(event_id, int) or str(event_id) in packet_index:
            raise RunnerError("FREQUENCIA network artifact contains an invalid or duplicate packet ID")
        if packet.get("animal_id") not in {tag["animal_ref"] for tag in request["tags"]}:
            raise RunnerError("FREQUENCIA network artifact contains an unknown animal")
        timestamp = packet.get("timestamp_s")
        if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
                or not math.isfinite(timestamp)):
            raise RunnerError("FREQUENCIA network artifact contains an invalid packet timestamp")
        identity = (packet["animal_id"], float(timestamp))
        if identity not in expected_packet_identities or identity in packet_identities:
            raise RunnerError("FREQUENCIA packet identity/time does not match a requested trajectory sample")
        packet_identities.add(identity)
        packet_index[str(event_id)] = packet
    if packet_identities != expected_packet_identities:
        raise RunnerError("FREQUENCIA network packets do not cover the requested trajectory samples")
    gateway_ids = {row["gateway_ref"] for row in request["receivers"]}
    seen_events: set[tuple[str, str]] = set()
    rx_gateways: dict[str, set[str]] = {key: set() for key in packet_index}
    outcomes = {"RX", "NO_PATH", "INTERFERENCE", "UNDER_SENSITIVITY",
                "NO_DEMODULATOR", "UNTRACED_DROP", "NOT_TRANSMITTED"}
    for event in events:
        packet_id = str(event.get("event_index"))
        gateway_id = event.get("gateway_id")
        packet = packet_index.get(packet_id)
        if packet is None or gateway_id not in gateway_ids:
            raise RunnerError("FREQUENCIA network artifact references an unknown packet or gateway")
        key = (packet_id, str(gateway_id))
        if key in seen_events:
            raise RunnerError("FREQUENCIA network artifact contains a duplicate gateway event")
        seen_events.add(key)
        if event.get("outcome") not in outcomes:
            raise RunnerError("FREQUENCIA network artifact contains an unknown reception outcome")
        if (event.get("animal_id") != packet["animal_id"]
                or event.get("timestamp_s") != packet["timestamp_s"]):
            raise RunnerError("FREQUENCIA network event does not match its packet identity/time")
        if event["outcome"] == "RX":
            rx_gateways[packet_id].add(str(gateway_id))
    if len(seen_events) != expected_packets * len(gateway_ids):
        raise RunnerError("FREQUENCIA network artifact has missing gateway events")
    if any(set(packet.get("received_gateway_ids", [])) != rx_gateways[key]
           for key, packet in packet_index.items()):
        raise RunnerError("FREQUENCIA packet reception list disagrees with gateway events")
    transmitted = sum(packet.get("tx_start_s") is not None for packet in packets)
    delivered = sum(bool(rx_gateways[key]) for key in packet_index)
    expected_pdr = delivered / transmitted if transmitted else None
    if (metrics.get("transmitted_packets") != transmitted
            or metrics.get("delivered_packets") != delivered
            or metrics.get("pdr") != expected_pdr):
        raise RunnerError("FREQUENCIA network PDR or denominator disagrees with packet outcomes")


def _validate_localization_result(request: dict, network: dict, localization: dict) -> None:
    estimates = localization.get("estimates")
    if not isinstance(estimates, list):
        raise RunnerError("FREQUENCIA localization artifact has no estimate array")
    packet_ids = {str(row["event_index"]) for row in network["packets"]
                  if row.get("tx_start_s") is not None}
    devices_by_animal = {row["animal_ref"]: row["device_ref"] for row in request["tags"]}
    transmitted_packets = {str(row["event_index"]): row for row in network["packets"]
                           if row.get("tx_start_s") is not None}
    seen: set[str] = set()
    statuses = {"NO_PACKET", "LT3_TIMESTAMPS", "SOLVER_FAILED", "CONVERGED"}
    for estimate in estimates:
        packet_id = str(estimate.get("packet_id"))
        packet = transmitted_packets.get(packet_id)
        if (packet_id not in packet_ids or packet is None
                or estimate.get("device_id") != devices_by_animal.get(packet.get("animal_id"))
                or packet_id in seen):
            raise RunnerError("FREQUENCIA localization estimate does not match its packet animal/device identity")
        seen.add(packet_id)
        status, position = estimate.get("tdoa_status"), estimate.get("tdoa_position_m")
        if status not in statuses:
            raise RunnerError("FREQUENCIA localization artifact has an unknown TDoA status")
        if status == "CONVERGED":
            if not isinstance(position, list) or len(position) != 2 or any(
                    isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                    for value in position):
                raise RunnerError("converged FREQUENCIA estimate has invalid ENU coordinates")
        elif position is not None:
            raise RunnerError("failed FREQUENCIA estimate must not contain a fabricated position")
    if len(seen) != len(packet_ids):
        raise RunnerError("FREQUENCIA localization artifact omits packet estimates")
    tdoa = localization.get("metrics", {}).get("tdoa") if isinstance(localization.get("metrics"), dict) else None
    if not isinstance(tdoa, dict):
        raise RunnerError("FREQUENCIA localization artifact is missing TDoA metrics")
    eligible = sum(estimate["tdoa_status"] in {"CONVERGED", "SOLVER_FAILED"} for estimate in estimates)
    converged = sum(estimate["tdoa_status"] == "CONVERGED" for estimate in estimates)
    expected_convergence = converged / eligible if eligible else None
    observed_convergence = tdoa.get("convergence")
    valid_convergence = (observed_convergence is None if expected_convergence is None else
                         not isinstance(observed_convergence, bool)
                         and isinstance(observed_convergence, (int, float))
                         and math.isfinite(observed_convergence)
                         and observed_convergence == expected_convergence)
    if (type(tdoa.get("eligible_packets")) is not int
            or tdoa.get("eligible_packets") != eligible
            or type(tdoa.get("converged_packets")) is not int
            or tdoa.get("converged_packets") != converged
            or not valid_convergence):
        raise RunnerError("FREQUENCIA TDoA metrics disagree with complete estimate statuses")


def _summary_markdown(request: dict, metrics: dict, status_counts: dict,
                      network_report: dict, runtime_seconds: float) -> str:
    """Create the small human-readable campaign summary next to JSON artifacts."""
    lines = [f"# Simulation Lab campaign: {request['campaign_id']}", "",
             "Evidence status: **SIMULATED**", "",
             "## RF", "",
             f"- Backend: `sionna-rt`",
             f"- Links: {metrics.get('observations', 'N/A')}",
             f"- LOS / NLOS / NO_PATH: {status_counts.get('LOS', 0)} / "
             f"{status_counts.get('NLOS', 0)} / {status_counts.get('NO_PATH', 0)}",
             "", "## Network", ""]
    if not network_report["enabled"]:
        lines.append("Network simulation: disabled; PDR and network metrics are N/A.")
    else:
        lines.extend([
            f"- Engine: `{network_report['network_backend']}`",
            f"- Packets transmitted: {network_report['transmitted_packets']}",
            f"- Gateway PHY receptions: {network_report['received_gateway_events']}",
            f"- Network drop events / collisions: {network_report['drops']} / {network_report['collisions']}",
            f"- NO_PATH / not transmitted events: {network_report['no_path']} / {network_report['not_transmitted']}",
            f"- Packet delivery ratio: {network_report['pdr']}",
            f"- LoRa: {network_report['frequency_hz']} Hz, {network_report['bandwidth_hz']} Hz, "
            f"SF{network_report['spreading_factor']}, {network_report['tx_power_dbm']} dBm, "
            f"{network_report['payload_bytes']} byte payload",
        ])
    lines.extend(["", "## Localization", ""])
    localization = network_report.get("localization")
    if localization is None:
        lines.append("TDoA: not run.")
    else:
        lines.extend([
            f"- Method / frame: {localization['method']} / {localization['coordinate_frame']}",
            f"- Attempts / eligible / converged / failed: {localization['attempts']} / "
            f"{localization['eligible']} / {localization['converged']} / {localization['failed']}",
            f"- Convergence among eligible: {localization['convergence_rate_among_eligible']}",
            f"- Operational quality accepted / rejected / not evaluated: "
            f"{localization['quality_counts']['ACCEPTED']} / "
            f"{localization['quality_counts']['REJECTED']} / "
            f"{localization['quality_counts']['NOT_EVALUATED']}",
            f"- Conditional RMSE / median / p90 error: {localization['conditional_rmse_m']} / "
            f"{localization['median_error_m']} / {localization['p90_error_m']} m",
        ])
    lines.extend(["", "## Temporal model", "",
                  "- Timestamp output is a `SIMULATED_CLOCK_TIMESTAMP_MODEL`.",
                  "- ns-3 numerical resolution is not physical hardware timestamp precision.",
                  f"- Runtime: {runtime_seconds:.3f} s",
                  "- PHY reception is gateway reception; application/server delivery is not modeled.",
                  "- No result in this report represents field validation.", ""])
    return "\n".join(lines)


def _result(request: dict, raw: dict, summary: dict, manifest: dict,
            request_hash: str, raw_hash: str, network_result: dict | None = None,
            temporal_rows: list[dict] | None = None,
            localization: dict | None = None) -> dict:
    mappings = request["id_mappings"]
    by_source = {(row["source_kind"], row["source_id"]): (row["riose_kind"], row["riose_id"])
                 for row in mappings}
    tags = {row["transmitter_ref"]: row for row in request["tags"]}
    receivers = {row["receiver_ref"]: row for row in request["receivers"]}
    expected_links = {
        (float(sample["timestamp_s"]), tag["transmitter_ref"], receiver["receiver_ref"])
        for sample in request["trajectory"]["samples"]
        for tag in request["tags"]
        for receiver in request["receivers"]
    }
    observed_links: set[tuple[float, str, str]] = set()
    observations = []
    for snapshot in raw["snapshots"]:
        raw_timestamp = snapshot["timestamp_s"]
        if (isinstance(raw_timestamp, bool) or not isinstance(raw_timestamp, (int, float))
                or not math.isfinite(raw_timestamp)):
            raise RunnerError("FARM result contains an invalid timestamp")
        timestamp = float(raw_timestamp)
        for receiver in snapshot["records"]:
            rx_id = receiver["receiver_id"]
            if rx_id not in receivers:
                raise RunnerError(f"FARM result contains unmapped receiver {rx_id!r}")
            for link in receiver["links"]:
                tx_id = link["transmitter_id"]
                if tx_id not in tags:
                    raise RunnerError(f"FARM result contains unmapped transmitter {tx_id!r}")
                link_key = (timestamp, tx_id, rx_id)
                if link_key not in expected_links:
                    raise RunnerError("FARM result contains a link outside the requested trajectory")
                if link_key in observed_links:
                    raise RunnerError("FARM result contains a duplicate timestamp/tag/receiver link")
                observed_links.add(link_key)
                state = link["status"]
                if state not in {"LOS", "NLOS", "NO_PATH"}:
                    raise RunnerError(f"FARM result contains unknown path state {state!r}")
                paths = link["paths"]
                if (state == "NO_PATH") != (len(paths) == 0):
                    raise RunnerError("FARM output has contradictory NO_PATH and path-list state")
                if (state == "NO_PATH") != (link["received_power_dbm"] is None):
                    raise RunnerError("FARM output has contradictory NO_PATH and received-power state")
                first_path = min(paths, key=lambda path: float(path["delay_s"])) if paths else None
                coefficient = first_path.get("coefficient") if first_path else None
                phase = None
                if isinstance(coefficient, dict) and all(isinstance(coefficient.get(key), (int, float))
                                                          for key in ("real", "imag")):
                    phase = math.atan2(float(coefficient["imag"]), float(coefficient["real"]))
                tag = tags[tx_id]
                receiver_request = receivers[rx_id]
                if by_source.get(("transmitter_id", tx_id)) != ("tag_id", tag["tag_ref"]):
                    raise RunnerError(f"FARM result tag mapping mismatch for {tx_id!r}")
                if by_source.get(("receiver_id", rx_id)) != ("anchor_id", receiver_request["anchor_ref"]):
                    raise RunnerError(f"FARM result anchor mapping mismatch for {rx_id!r}")
                has_path = state != "NO_PATH"
                observations.append({
                    "timestamp_s": timestamp, "source_tag_ref": tx_id, "source_receiver_ref": rx_id,
                    "tag_id": tag["tag_ref"], "anchor_id": receiver_request["anchor_ref"],
                    "channel_state": "PATH" if has_path else "NO_PATH",
                    "tx_state": "UNKNOWN", "rx_state": "DATA_UNAVAILABLE",
                    "metrics": {"received_power_dbm": link["received_power_dbm"] if has_path else None,
                                "rssi_dbm": None, "snr_db": None,
                                "propagation_delay_s": float(first_path["delay_s"]) if first_path else None,
                                "tof_measured_s": None, "phase_rad": phase,
                                "path_state": state},
                    "status": "SIMULATED",
                })
    if observed_links != expected_links:
        missing = len(expected_links - observed_links)
        extra = len(observed_links - expected_links)
        raise RunnerError(f"FARM result does not match requested links (missing={missing}, extra={extra})")
    network_events = {}
    packets = {}
    timestamps = {}
    if network_result is not None:
        packets = {(str(row["animal_id"]), float(row["timestamp_s"])): row
                   for row in network_result.get("packets", [])}
        network_events = {(str(row["animal_id"]), float(row["timestamp_s"]), str(row["gateway_id"])): row
                          for row in network_result.get("gateway_events", [])}
        timestamps = {(str(row["animal_id"]), float(row["timestamp_s"]), str(row["gateway_id"])): row
                      for row in (temporal_rows or [])}
    for observation in observations:
        if network_result is None:
            continue
        tag = tags[observation["source_tag_ref"]]
        animal_id = str(tag["animal_ref"])
        timestamp = float(observation["timestamp_s"])
        gateway_id = str(receivers[observation["source_receiver_ref"]]["gateway_ref"])
        packet = packets.get((animal_id, timestamp))
        event = network_events.get((animal_id, timestamp, gateway_id))
        if packet is None or packet.get("tx_start_s") is None:
            observation["tx_state"], observation["rx_state"] = "NOT_TRANSMITTED", "NOT_APPLICABLE"
        else:
            observation["tx_state"] = "TRANSMITTED"
            outcome = event.get("outcome") if event else None
            if outcome == "RX":
                observation["rx_state"] = "PHY_RECEIVED"
                time_row = timestamps.get((animal_id, timestamp, gateway_id))
                if time_row:
                    observation["metrics"]["snr_db"] = time_row.get("snr_db")
            elif outcome == "NOT_TRANSMITTED":
                observation["tx_state"], observation["rx_state"] = "NOT_TRANSMITTED", "NOT_APPLICABLE"
            elif outcome == "NO_PATH" or observation["channel_state"] == "NO_PATH":
                observation["rx_state"] = "NOT_RECEIVED"
            elif outcome is None:
                observation["rx_state"] = "DATA_UNAVAILABLE"
            else:
                observation["rx_state"] = "PHY_NOT_RECEIVED"
    locations = []
    if network_result is not None and localization is not None:
        packet_by_id = {str(row["event_index"]): row for row in network_result.get("packets", [])}
        tx_to_tag = {row["transmitter_ref"]: row for row in request["tags"]}
        device_to_tag = {row["device_ref"]: row for row in request["tags"]}
        for estimate in localization.get("estimates", []):
            packet = packet_by_id.get(str(estimate.get("packet_id")))
            tag = device_to_tag.get(str(estimate.get("device_id")))
            if packet is None or tag is None:
                raise RunnerError("TDoA result references an unknown packet or RIOSE device")
            source_tx = tag["transmitter_ref"]
            if tx_to_tag.get(source_tx) is not tag:
                raise RunnerError("TDoA result transmitter mapping is inconsistent")
            position = estimate.get("tdoa_position_m") if estimate.get("tdoa_status") == "CONVERGED" else None
            if position is not None and (not isinstance(position, list) or len(position) < 2):
                raise RunnerError("FREQUENCIA TDoA estimate has malformed coordinates")
            quality = _quality_assessment(request, str(estimate.get("tdoa_status", "UNKNOWN")),
                                          [float(position[0]), float(position[1])] if position is not None else None)
            locations.append({"timestamp_s": float(packet["timestamp_s"]),
                              "source_tag_ref": source_tx, "tag_id": tag["tag_ref"],
                              "position_m": [float(position[0]), float(position[1])] if position is not None else None,
                              "quality": None, "method": f"FREQUENCIA_TDOA:{estimate.get('tdoa_status', 'UNKNOWN')}",
                              "status": "SIMULATED", "solver_status": estimate.get("tdoa_status", "UNKNOWN"),
                              **quality})
    result = {"schema_version": "riose.simulation.result/v1",
              "campaign_id": request["campaign_id"], "scenario_id": request["scenario_id"],
              "backend": "frequencia.sionna-rt",
              "solver_version": manifest.get("repository_provenance", {}).get("sionna_rt_version"),
              "status": "SIMULATED", "id_mappings": mappings,
              "observations": observations, "locations": locations,
              "warnings": (["phase_rad, when present, is the earliest-arriving path coefficient phase, not combined channel phase."]
                           if any(row["metrics"]["phase_rad"] is not None for row in observations) else []),
              "limitations": [
                  "The FARM route is a synthetic transmitter trajectory, not an animal behavior model.",
                  "PHY_RECEIVED means gateway PHY reception; application/server delivery is not modeled.",
                  "2D TDoA estimates contain east/north only; altitude is not estimated.",
                  "The Sionna run uses the declared idealized isotropic antenna and uncalibrated synthetic FARM geometry/materials.",
              ],
              "provenance": {"request_sha256": request_hash, "output_sha256": raw_hash,
                             "completed_at": _utc_now()}}
    return validate_result(result)


def run_farm_sionna(request: dict, request_hash: str, *, repo: str | Path | None,
                    expected_sha: str, output_root: str | Path | None,
                    timeout_seconds: float, allow_dirty: bool, dry_run: bool = False) -> dict[str, Any]:
    """Execute the real, explicit Sionna backend via frequencia's ExperimentSpec."""
    inspection = _engine_inspection(repo, expected_sha)
    _check_inspection(inspection, allow_dirty=allow_dirty)
    engine_root = Path(inspection["path"])
    network_config, temporal_config = _network_config(request)
    required = (engine_root / "hub" / "run.py", engine_root / "scripts" / "run_farm_sionna_experiment.py")
    if any(not item.is_file() for item in required):
        raise RunnerError("frequencia's generic FARM Sionna ExperimentSpec runner is unavailable")
    engine_python = _engine_python(engine_root)
    for reference in request["input_references"]:
        source = (engine_root / reference["name"]).resolve()
        if not source.is_relative_to(engine_root) or not source.is_file():
            raise RunnerError(f"declared input reference is missing or outside frequencia: {reference['name']}")
        if hashlib.sha256(source.read_bytes()).hexdigest() != reference["sha256"]:
            raise RunnerError(f"declared input reference hash does not match: {reference['name']}")
    run_id, workspace = _new_workspace(Path(output_root).expanduser().resolve() if output_root else
                                       (Path.home() / ".cache" / "RIOSE" / "simulation_runs").resolve())
    _write_json(workspace / "request" / "request.json", request)
    engine_sha, engine_dirty = inspection["actual_sha"], inspection["dirty"]
    riose_root = Path(__file__).resolve().parents[3]
    riose_sha, riose_dirty = _git_provenance(riose_root)
    base_config, trajectory, spec = _prepare_inputs(request, workspace, engine_root, run_id)
    engine_output = Path(engine_root / "results" / "riose_simulation_lab" /
                         request["campaign_id"] / run_id / "engine").resolve()
    command = [str(engine_python), "-m", "hub.run", str(spec)]
    started_at, start = _utc_now(), time.monotonic()
    if dry_run:
        manifest = {
            "schema_version": "riose.simulation.run-manifest/v1", "run_id": run_id,
            "campaign_id": request["campaign_id"],
            "riose": {"revision": riose_sha, "dirty": riose_dirty},
            "engine": {"repository_url": FREQUENCIA_URL, "path": str(engine_root),
                       "expected_sha": expected_sha, "actual_sha": engine_sha, "dirty": engine_dirty,
                       "python": str(engine_python)},
            "backend_requested": "sionna-rt", "backend_used": None,
            "evidence_classification": "SIMULATED", "request_sha256": request_hash,
            "generated_config_sha256": hashlib.sha256(base_config.read_bytes()).hexdigest(),
            "trajectory_sha256": hashlib.sha256(trajectory.read_bytes()).hexdigest(),
            "experiment_spec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest(),
            "seed": request["seed"], "command": command, "working_directory": str(engine_root),
            "started_at": started_at, "finished_at": _utc_now(),
            "duration_seconds": time.monotonic() - start, "dry_run": True, "exit_code": None,
            "engine_output": str(engine_output),
            "warnings": ["Dry run validated and prepared request inputs; no FREQUENCIA campaign was started."],
        }
        _write_json(workspace / "manifest.json", manifest)
        return {"run_id": run_id, "workspace": str(workspace), "manifest": manifest,
                "result": None, "status": "PLANNED"}
    _keep_results_out_of_git(engine_root)
    exit_code, process_error = _run_process(command, cwd=engine_root, logs=workspace / "logs",
                                            timeout_seconds=float(timeout_seconds), output_dir=engine_output)
    if process_error:
        raise RunnerError(process_error)
    if exit_code != 0:
        raise RunnerError(f"frequencia Sionna runner exited with code {exit_code}; see {workspace / 'logs'}")
    required_artifacts = {"raw": engine_output / "raw_snapshot_data.json",
                          "summary": engine_output / "summary.json",
                          "metrics": engine_output / "metrics.json",
                          "manifest": engine_output / "environment_manifest.json"}
    if any(not path.is_file() for path in required_artifacts.values()):
        raise RunnerError("frequencia exited successfully without the required Sionna result artifacts")
    raw = _json(required_artifacts["raw"])
    summary = _json(required_artifacts["summary"])
    metrics = _json(required_artifacts["metrics"])
    engine_manifest = _json(required_artifacts["manifest"])
    if summary.get("environment") != "FARM" or summary.get("backend") != "sionna-rt" or summary.get("status") != "PASS":
        raise RunnerError("frequencia output does not attest a successful FARM Sionna RT campaign")
    parameter_binding = _validate_sionna_binding(request, summary, engine_manifest)
    if raw.get("classification") != "SIMULATED_SYNTHETIC_REFERENCE_NOT_FIELD_MEASUREMENT":
        raise RunnerError("frequencia raw output is missing the expected simulated-evidence classification")
    if raw.get("coordinate_system") != "ENU local":
        raise RunnerError("frequencia output changed the declared FARM coordinate frame")
    raw_hash = hashlib.sha256(required_artifacts["raw"].read_bytes()).hexdigest()
    network_result = None
    temporal_rows = None
    localization = None
    scoring = None
    ns3_root = None
    if network_config is not None and network_config["enabled"]:
        ns3_root = Path(os.environ.get(
            "FREQUENCIA_NS3_ROOT", str(Path.home() / ".local/share/frequencia/ns-3.48"))).expanduser().resolve()
        if not (engine_root / "network" / "adapter.py").is_file():
            raise RunnerError("the pinned FREQUENCIA checkout does not provide its network adapter")
        if not (ns3_root / "ns3").is_file() or not (ns3_root / "build/lib/libns3.48-lorawan-default.so").is_file():
            raise RunnerError(f"ns-3 3.48/LoRaWAN v0.3.7 is unavailable under {ns3_root}; no RF-only fallback was used")
        network_input_path = workspace / "network" / "inputs.json"
        network_output_path = workspace / "network" / "pipeline.json"
        network_payload = _network_input(request, raw, run_id, request_hash)
        network_payload["ns3_root"] = str(ns3_root)
        _write_json(network_input_path, network_payload)
        helper = Path(__file__).with_name("frequencia_network.py")
        network_command = [str(engine_python), str(helper), str(network_input_path),
                           str(network_output_path), str(engine_root)]
        network_input_hash = hashlib.sha256(network_input_path.read_bytes()).hexdigest()
        remaining = max(1.0, float(timeout_seconds) - (time.monotonic() - start))
        network_exit, network_error = _run_process(network_command, cwd=engine_root,
            logs=workspace / "logs" / "network", timeout_seconds=remaining)
        if network_error:
            raise RunnerError(f"FREQUENCIA network/temporal/localization execution failed: {network_error}")
        if network_exit != 0 or not network_output_path.is_file():
            raise RunnerError(f"FREQUENCIA network pipeline exited with code {network_exit}; see {workspace / 'logs' / 'network'}")
        payload_result = _json(network_output_path)
        network_result = payload_result.get("network")
        temporal_rows = payload_result.get("timestamps")
        localization = payload_result.get("localization")
        temporal_runtime = payload_result.get("temporal_runtime")
        if not isinstance(network_result, dict) or not isinstance(temporal_rows, list) or not isinstance(localization, dict):
            raise RunnerError("FREQUENCIA network pipeline returned malformed artifacts")
        _validate_network_result(request, network_result)
        _validate_localization_result(request, network_result, localization)
        temporal_binding = _validate_temporal_runtime(request, temporal_runtime, run_id, request_hash,
                                                      network_input_hash)
        temporal_binding["runtime_artifact_sha256"] = hashlib.sha256(network_output_path.read_bytes()).hexdigest()
        expected_rx = {(str(row["event_index"]), str(row["gateway_id"]))
                       for row in network_result["gateway_events"] if row["outcome"] == "RX"}
        received_timestamps: set[tuple[str, str]] = set()
        for row in temporal_rows:
            key = (str(row.get("packet_id")), str(row.get("gateway_id")))
            if key not in expected_rx or key in received_timestamps or row.get("classification") != "SIMULATED":
                raise RunnerError("FREQUENCIA temporal artifact contains an unknown or duplicate gateway timestamp")
            stamp = row.get("clock_timestamp_s")
            if stamp is not None and (isinstance(stamp, bool) or not isinstance(stamp, (int, float))
                                      or not math.isfinite(stamp)):
                raise RunnerError("FREQUENCIA temporal artifact contains a non-finite clock timestamp")
            received_timestamps.add(key)
        if received_timestamps != expected_rx:
            raise RunnerError("FREQUENCIA temporal artifact omits a PHY reception")
        scoring = _score_after_estimation(request, network_result, localization)
        _write_json(workspace / "network" / "network_results.json", network_result)
        _write_json(workspace / "network" / "gateway_timestamps.json", {
            "schema_version": "riose.simulation.timestamps/v1",
            "classification": "SIMULATED_CLOCK_TIMESTAMP_MODEL",
            "time_resolution_ps": network_result.get("time_resolution_ps"),
            "resolution_is_hardware_precision": False, "records": temporal_rows})
        _write_json(workspace / "network" / "localization.json", localization)
        _write_json(workspace / "network" / "scoring.json", scoring)
    result = _result(request, raw, summary, engine_manifest, request_hash, raw_hash,
                     network_result, temporal_rows, localization)
    parameter_binding["trajectory"] = {
        "requested_sha256": content_hash(request["trajectory"]),
        "effective_csv_sha256": hashlib.sha256(trajectory.read_bytes()).hexdigest(),
        "link_set_status": "VERIFIED",
        "status": "VERIFIED",
    }
    parameter_binding["network"] = {
        "requested": network_config,
        "effective": ({key: network_result.get(source) for key, source in (
            ("seed", "seed"), ("frequency_hz", "frequency_hz"),
            ("tx_power_dbm", "tx_power_dbm"), ("spreading_factor", "sf"),
            ("payload_bytes", "payload_bytes"), ("traffic_interval_s", "traffic_interval_s"),
        )} | {"bandwidth_hz": request["radio"]["bandwidth_hz"]} if network_result else None),
        "bandwidth_verification": "request constrained to the pinned adapter's single 125 kHz channel and forwarded to LoRaPhyConfig" if network_result else None,
        "status": "VERIFIED" if network_result else "NOT_RUN",
    }
    parameter_binding["temporal"] = (temporal_binding if network_result else {
        "requested": temporal_config, "forwarded": None, "effective": None,
        "status": "NOT_APPLICABLE" if temporal_config is None else "NOT_RUN",
    })
    _write_json(workspace / "result" / "result.json", result)
    from riose.simulation_adapter import convert_result

    adapted = convert_result(result)
    adapter_payload = {
        "observations": [asdict(row) for row in adapted.observations],
        "estimates": [asdict(row) for row in adapted.estimates],
        "observation_provenance": list(adapted.observation_provenance),
        "estimate_provenance": list(adapted.estimate_provenance),
        "report": asdict(adapted.report),
    }
    adapter_path = workspace / "adapter" / "adapter_output.json"
    _write_json(adapter_path, adapter_payload)
    (workspace / "artifacts.json").write_text(
        canonical_json({key: str(value) for key, value in required_artifacts.items()}) + "\n", encoding="utf-8")
    status_counts = metrics.get("status_counts", {})
    geometry_hashes = {}
    for name, relative in engine_manifest.get("static_meshes", {}).items():
        mesh_path = (engine_output / relative).resolve()
        if not mesh_path.is_relative_to(engine_output) or not mesh_path.is_file():
            raise RunnerError(f"FARM engine manifest references an invalid geometry artifact: {name}")
        geometry_hashes[name] = hashlib.sha256(mesh_path.read_bytes()).hexdigest()
    network_report = _network_summary(network_result, localization, scoring)
    duration_seconds = time.monotonic() - start
    summary_path = workspace / "summary.md"
    summary_path.write_text(_summary_markdown(request, metrics, status_counts,
                           network_report, duration_seconds), encoding="utf-8")
    summary_sha256 = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    network_artifacts = {}
    for name in ("inputs.json", "pipeline.json", "network_results.json", "gateway_timestamps.json",
                 "localization.json", "scoring.json"):
        path = workspace / "network" / name
        if path.is_file():
            network_artifacts[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    run_manifest = {
        "schema_version": "riose.simulation.run-manifest/v1", "run_id": run_id,
        "campaign_id": request["campaign_id"], "riose": {"revision": riose_sha, "dirty": riose_dirty},
        "engine": {"repository_url": FREQUENCIA_URL, "path": str(engine_root),
                   "expected_sha": expected_sha, "actual_sha": engine_sha,
                   "dirty": engine_dirty, "python": str(engine_python),
                   "sionna_version": engine_manifest.get("repository_provenance", {}).get("sionna_rt_version"),
                   "device": "CPU (frequencia RF adapter sets CUDA_VISIBLE_DEVICES=-1)"},
        "backend_requested": "sionna-rt", "backend_used": result["backend"],
        "evidence_classification": "SIMULATED", "request_sha256": request_hash,
        "parameter_binding": parameter_binding,
        "generated_config_sha256": hashlib.sha256(base_config.read_bytes()).hexdigest(),
        "base_config_path": "configs/farm_sionna_smoke.yaml",
        "base_config_sha256": hashlib.sha256(
            (engine_root / "configs" / "farm_sionna_smoke.yaml").read_bytes()).hexdigest(),
        "trajectory_sha256": hashlib.sha256(trajectory.read_bytes()).hexdigest(),
        "experiment_spec_sha256": hashlib.sha256(spec.read_bytes()).hexdigest(),
        "raw_output_sha256": raw_hash, "frequency_hz": summary.get("frequency_hz"),
        "summary_artifact": str(summary_path), "summary_sha256": summary_sha256,
        "seed": request["seed"], "coordinate_frame": request["coordinate_frame"],
        "network": {"enabled": bool(network_config and network_config.get("enabled")),
                    "backend": network_result.get("network_backend") if network_result else None,
                    "ns3_version": "3.48" if network_result else None,
                    "lorawan_module": "v0.3.7" if network_result else None,
                    "ns3_root": str(ns3_root) if ns3_root else None,
                    "frequency_hz": network_result.get("frequency_hz") if network_result else None,
                    "bandwidth_hz": network_result.get("bandwidth_hz", 125_000) if network_result else None,
                    "spreading_factor": network_result.get("sf") if network_result else None,
                    "tx_power_dbm": network_result.get("tx_power_dbm") if network_result else None,
                    "payload_bytes": network_result.get("payload_bytes") if network_result else None,
                    "traffic_interval_s": network_result.get("traffic_interval_s") if network_result else None,
                    "packet_delivery_ratio": network_report["pdr"],
                    "network_drop_events": network_report["drops"],
                    "no_path_events": network_report["no_path"],
                    "not_transmitted_events": network_report["not_transmitted"],
                    "gateway_events": network_report["outcomes"],
                    "temporal_model": temporal_config,
                    "localization_method": "FREQUENCIA TDoA" if localization else None,
                    "localization_metrics": network_report["localization"],
                    "artifact_sha256": network_artifacts,
                    "timestamp_classification": "SIMULATED_CLOCK_TIMESTAMP_MODEL" if network_result else None,
                    "time_resolution_ps": network_result.get("time_resolution_ps") if network_result else None,
                    "resolution_is_hardware_precision": False if network_result else None},
        "solver_configuration": engine_manifest.get("solver_configuration"),
        "antenna_assumptions": engine_manifest.get("antenna_assumptions"),
        "material_provenance": engine_manifest.get("material_provenance"),
        "geometry_used": engine_manifest.get("static_meshes"), "geometry_sha256": geometry_hashes,
        "scenario_metadata": engine_manifest.get("scenario_metadata"),
        "started_at": started_at, "finished_at": _utc_now(),
        "duration_seconds": duration_seconds, "exit_code": exit_code,
        "engine_output": str(engine_output), "adapter_output": str(adapter_path),
        "warnings": result["limitations"],
    }
    _write_json(workspace / "manifest.json", run_manifest)
    return {"run_id": run_id, "workspace": str(workspace), "manifest": run_manifest,
            "result": result, "adapter_output": str(adapter_path),
            "summary_artifact": str(summary_path),
            "adapter_report": asdict(adapted.report),
            "summary": {"transmitters": len(request["tags"]),
                "gateways": len(request["receivers"]), "timestamps": metrics.get("snapshot_count"),
                "links": metrics.get("observations"), "LOS": status_counts.get("LOS", 0),
                "NLOS": status_counts.get("NLOS", 0), "NO_PATH": status_counts.get("NO_PATH", 0),
                "received_power_dbm": metrics.get("received_power_dbm"),
                "backend": summary["backend"], "runtime_seconds": run_manifest["duration_seconds"],
                "network": network_report},
            "status": "SIMULATED"}
