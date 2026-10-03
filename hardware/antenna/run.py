"""Run auditable, headless openEMS antenna experiments."""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import SCENARIOS
from .geometry import GeometryError, build_geometry
from .openems_backend import (MESH_REFINEMENT_COARSE_FACTOR, expected_input_hash,
                              runtime_status, simulate_scenario)
from .sweeps import run_sweeps

SCHEMA_VERSION = "riose.antenna.experiments/v2"
MESH_RESONANCE_TOLERANCE_FRACTION = 0.02
REFINEMENT_METRICS = (
    "resonant_frequency_hz", "s11_min_db", "input_impedance_real_ohm",
    "input_impedance_imag_ohm", "vswr_min", "efficiency_fraction", "gain_dbi",
    "directivity_dbi", "s11_at_target_db", "input_impedance_real_at_target_ohm",
    "input_impedance_imag_at_target_ohm", "vswr_at_target",
)
MESH_ABSOLUTE_TOLERANCES = {
    "s11_min_db": 1.0,
    "input_impedance_real_ohm": 5.0,
    "input_impedance_imag_ohm": 5.0,
    "vswr_min": 0.5,
    "efficiency_fraction": 0.05,
    "gain_dbi": 0.5,
    "directivity_dbi": 0.5,
    "s11_at_target_db": 1.0,
    "input_impedance_real_at_target_ohm": 5.0,
    "input_impedance_imag_at_target_ohm": 5.0,
    "vswr_at_target": 0.5,
}


def _mesh_hash_from_evidence(mesh: Any) -> str | None:
    """Recompute a mesh hash from its serialized coordinate lines."""
    if not isinstance(mesh, dict) or not isinstance(mesh.get("lines"), dict):
        return None
    lines = mesh["lines"]
    if set(lines) != {"x", "y", "z"}:
        return None
    normalized: dict[str, list[float]] = {}
    for axis in "xyz":
        values = lines[axis]
        if not isinstance(values, list) or len(values) < 2:
            return None
        try:
            coords = [float(value) for value in values]
        except (TypeError, ValueError, OverflowError):
            return None
        if any(isinstance(value, bool) for value in values):
            return None
        if not all(math.isfinite(value) for value in coords) or any(
                right <= left for left, right in itertools.pairwise(coords)):
            return None
        normalized[axis] = coords
    counts = {axis: len(coords) - 1 for axis, coords in normalized.items()}
    if mesh.get("cell_counts") != counts or mesh.get("cell_count_total") != math.prod(counts.values()):
        return None
    packed = json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def _mesh_refinement(coarse: dict[str, Any], fine: dict[str, Any]) -> dict[str, Any]:
    """Compare actual coarse/fine solver results; missing evidence fails closed."""
    if coarse.get("status") != "COMPLETED" or fine.get("status") != "COMPLETED":
        return {
            "status": "BLOCKED", "converged": False,
            "coarse_status": coarse.get("status", "FAILED"),
            "fine_status": fine.get("status", "FAILED"),
            "detail": "both coarse and fine native solver runs must complete",
            "metric_deltas": {field: None for field in REFINEMENT_METRICS},
        }
    coarse_metrics, fine_metrics = coarse.get("metrics"), fine.get("metrics")
    if not isinstance(coarse_metrics, dict) or not isinstance(fine_metrics, dict):
        return {"status": "BLOCKED", "converged": False,
                "detail": "coarse/fine solver metrics are missing",
                "metric_deltas": {field: None for field in REFINEMENT_METRICS}}
    coarse_mesh = coarse.get("evidence", {}).get("mesh")
    fine_mesh = fine.get("evidence", {}).get("mesh")
    coarse_mesh_hash = coarse_mesh.get("mesh_hash_sha256") if isinstance(coarse_mesh, dict) else None
    fine_mesh_hash = fine_mesh.get("mesh_hash_sha256") if isinstance(fine_mesh, dict) else None
    if (not isinstance(coarse_mesh_hash, str) or len(coarse_mesh_hash) != 64
            or not isinstance(fine_mesh_hash, str) or len(fine_mesh_hash) != 64
            or _mesh_hash_from_evidence(coarse_mesh) != coarse_mesh_hash
            or _mesh_hash_from_evidence(fine_mesh) != fine_mesh_hash):
        return {"status": "BLOCKED", "converged": False,
                "detail": "coarse/fine mesh hashes do not match valid serialized coordinate lines",
                "metric_deltas": {field: None for field in REFINEMENT_METRICS}}
    if coarse_mesh_hash == fine_mesh_hash:
        return {"status": "NON_CONVERGED", "converged": False,
                "detail": "coarse and fine solver results use the same mesh hash",
                "coarse_mesh_hash_sha256": coarse_mesh_hash,
                "fine_mesh_hash_sha256": fine_mesh_hash,
                "metric_deltas": {field: None for field in REFINEMENT_METRICS}}
    deltas: dict[str, float | None] = {}
    for field in REFINEMENT_METRICS:
        left, right = coarse_metrics.get(field), fine_metrics.get(field)
        if (isinstance(left, bool) or isinstance(right, bool)
                or not isinstance(left, (int, float)) or not isinstance(right, (int, float))
                or not math.isfinite(float(left)) or not math.isfinite(float(right))):
            deltas[field] = None
        else:
            deltas[field] = float(right) - float(left)
    fine_frequency = fine_metrics.get("resonant_frequency_hz")
    frequency_delta = (abs(deltas["resonant_frequency_hz"]) / abs(float(fine_frequency))
                       if isinstance(fine_frequency, (int, float)) and not isinstance(fine_frequency, bool)
                       and math.isfinite(float(fine_frequency)) and fine_frequency != 0
                       and deltas["resonant_frequency_hz"] is not None else None)
    failed_metrics = [field for field in MESH_ABSOLUTE_TOLERANCES
                      if deltas[field] is None or abs(deltas[field]) > MESH_ABSOLUTE_TOLERANCES[field]]
    frequency_converged = (frequency_delta is not None
                           and frequency_delta <= MESH_RESONANCE_TOLERANCE_FRACTION)
    converged = frequency_converged and not failed_metrics
    return {
        "status": "COMPLETED" if converged else "NON_CONVERGED",
        "converged": converged,
        "coarse_status": coarse["status"], "fine_status": fine["status"],
        "coarse_input_hash_sha256": coarse.get("evidence", {}).get("input_hash_sha256"),
        "fine_input_hash_sha256": fine.get("evidence", {}).get("input_hash_sha256"),
        "coarse_mesh": coarse_mesh,
        "fine_mesh": fine_mesh,
        "coarse_mesh_hash_sha256": coarse_mesh_hash,
        "fine_mesh_hash_sha256": fine_mesh_hash,
        "mesh_hashes_distinct": True,
        "resonant_frequency_relative_delta": frequency_delta,
        "s11_min_delta_db": (abs(deltas["s11_min_db"])
                              if deltas["s11_min_db"] is not None else None),
        "failed_metrics": failed_metrics,
        "criteria": {"resonance_max_relative_delta": MESH_RESONANCE_TOLERANCE_FRACTION,
                      "absolute_metric_tolerances": MESH_ABSOLUTE_TOLERANCES},
        "metric_deltas_fine_minus_coarse": deltas,
        "detail": None if converged else (
            "coarse/fine resonance exceeds its declared tolerance" if not frequency_converged
            else f"coarse/fine metrics exceed declared tolerances: {', '.join(failed_metrics)}"),
    }


def _load_spec(path: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if path is None:
        raise ValueError("A central hardware specification is required for a solver run")
    if not path.is_file():
        raise FileNotFoundError(f"Hardware specification not found: {path}")
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("Reading hardware/spec.yaml requires PyYAML") from exc
    raw = path.read_bytes()
    parsed = yaml.safe_load(raw) or {}
    if not isinstance(parsed, dict):
        raise ValueError("hardware spec YAML root must be a mapping")
    return parsed, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "status": "LOADED"}


def _record(spec: dict[str, Any], key: str) -> dict[str, Any]:
    value = spec.get("antenna", {}).get(key)
    if not isinstance(value, dict) or not {"value", "unit", "source", "status"} <= value.keys():
        raise ValueError(f"antenna.{key} must contain value, unit, source, and status")
    if not isinstance(value["source"], str) or not value["source"].strip():
        raise ValueError(f"antenna.{key}.source must be a non-empty string")
    item = dict(value)
    if str(item["status"]).upper() == "MEASURED":
        raise ValueError(f"antenna.{key} cannot be MEASURED in the digital-only MVP2")
    return item


def _scenario_row(name: str, result: dict[str, Any], geometry: dict[str, Any] | None) -> dict[str, Any]:
    status = result.get("status", "FAILED")
    row: dict[str, Any] = {
        "scenario": name,
        "status": status,
        "result_class": "SIMULATED" if status == "COMPLETED" else "NO_SIMULATION_RESULT",
        "detail": result.get("detail", ""),
        "failure_class": result.get("failure_class"),
        "assumptions": "; ".join((geometry or {}).get("material_approximations", [])),
        "input_hash_sha256": result.get("evidence", {}).get("input_hash_sha256"),
        "geometry_hash_sha256": (geometry or {}).get("geometry_hash_sha256"),
        "geometry": geometry,
    }
    metrics = result.get("metrics") if status == "COMPLETED" else None
    row.update(metrics or {
        "resonant_frequency_hz": None, "s11_min_db": None,
        "input_impedance_real_ohm": None, "input_impedance_imag_ohm": None,
        "vswr_min": None, "efficiency_fraction": None, "gain_dbi": None,
        "directivity_dbi": None, "target_frequency_hz": None,
        "s11_at_target_db": None, "input_impedance_real_at_target_ohm": None,
        "input_impedance_imag_at_target_ohm": None, "vswr_at_target": None,
        "s11_curve_path": None,
        "radiation_pattern_path": None, "radiation_pattern_samples": None,
    })
    row["s11_curve"] = result.get("s11_curve") if status == "COMPLETED" else None
    row["radiation_pattern"] = result.get("radiation_pattern") if status == "COMPLETED" else None
    row["solver_evidence"] = result.get("evidence", {})
    return row


def _validate_completion(result: dict[str, Any], output_dir: Path, *,
                         expected_spec_hash: str, expected_geometry_hash: str,
                         expected_input_hash: str) -> str | None:
    """Accept completion only with native solver, mesh, convergence and artifact evidence."""
    evidence = result.get("evidence")
    metrics = result.get("metrics")
    if not isinstance(evidence, dict) or not isinstance(metrics, dict):
        return "completed result is missing structured metrics or evidence"
    if (evidence.get("spec_hash_sha256") != expected_spec_hash
            or evidence.get("geometry_hash_sha256") != expected_geometry_hash
            or evidence.get("input_hash_sha256") != expected_input_hash):
        return "completed result hashes do not match the requested spec, geometry and input"
    convergence = evidence.get("convergence")
    if not isinstance(convergence, dict) or convergence.get("converged") is not True:
        return "completed result does not prove boolean time-domain convergence"
    try:
        residual = float(convergence["energy_residual_fraction"])
        end_criteria = float(convergence["end_criteria"])
        final_step = int(convergence["final_time_step"])
        step_limit = int(convergence["max_time_steps"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return "completed result is missing numeric convergence evidence"
    if not math.isfinite(residual) or not math.isfinite(end_criteria) or residual > end_criteria or final_step >= step_limit:
        return "completed result convergence evidence does not meet its stated threshold"
    mesh = evidence.get("mesh")
    mesh_hash = mesh.get("mesh_hash_sha256") if isinstance(mesh, dict) else None
    if (not isinstance(mesh_hash, str) or len(mesh_hash) != 64
            or _mesh_hash_from_evidence(mesh) != mesh_hash):
        return "completed result is missing a valid mesh hash tied to its coordinate lines"
    runtime = evidence.get("runtime")
    if not isinstance(runtime, dict) or runtime.get("available") is not True or not runtime.get("solver_version"):
        return "completed result is missing openEMS version evidence"
    for key in ("input_hash_sha256", "spec_hash_sha256", "geometry_hash_sha256"):
        value = evidence.get(key)
        if not isinstance(value, str) or len(value) != 64:
            return f"completed result is missing valid {key}"
    for field in ("resonant_frequency_hz", "s11_min_db", "input_impedance_real_ohm",
                  "input_impedance_imag_ohm", "efficiency_fraction", "gain_dbi"):
        value = metrics.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return f"completed result has invalid metric {field}"
    target_frequency = metrics.get("target_frequency_hz")
    if (isinstance(target_frequency, bool) or not isinstance(target_frequency, (int, float))
            or not math.isfinite(target_frequency) or target_frequency <= 0):
        return "completed result is missing valid target_frequency_hz"
    for field in ("s11_at_target_db", "input_impedance_real_at_target_ohm",
                  "input_impedance_imag_at_target_ohm"):
        value = metrics.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return f"completed result has invalid metric {field}"
    if (isinstance(metrics.get("vswr_at_target"), bool)
            or not isinstance(metrics.get("vswr_at_target"), (int, float))
            or not math.isfinite(metrics["vswr_at_target"])):
        return "completed result has invalid metric vswr_at_target"
    if (isinstance(metrics.get("vswr_min"), bool)
            or not isinstance(metrics.get("vswr_min"), (int, float))
            or not math.isfinite(metrics["vswr_min"])):
        return "completed result has invalid metric vswr_min"
    artifacts = evidence.get("artifacts", {})
    for path_key, hash_key in (("s11_curve_path", "s11_curve_sha256"),
                               ("radiation_pattern_path", "radiation_pattern_sha256")):
        relative = metrics.get(path_key)
        artifact_hash = artifacts.get(hash_key)
        if not isinstance(relative, str) or not isinstance(artifact_hash, str):
            return f"completed result is missing {path_key} evidence"
        artifact = (output_dir / relative).resolve()
        if output_dir.resolve() not in artifact.parents or not artifact.is_file():
            return f"completed result artifact is missing or outside output directory: {relative}"
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if digest != artifact_hash:
            return f"completed result artifact hash does not match: {relative}"
    for key in ("s11_curve", "radiation_pattern"):
        if not isinstance(result.get(key), list) or not result[key]:
            return f"completed result is missing parsed {key} data"
    pattern = result["radiation_pattern"]
    try:
        theta = {float(point["theta_deg"]) for point in pattern}
        phi = {float(point["phi_deg"]) for point in pattern}
    except (KeyError, TypeError, ValueError, OverflowError):
        return "completed result radiation pattern has invalid angular coordinates"
    if (len(theta) < 91 or len(phi) < 181 or min(theta) != 0 or max(theta) != 180
            or min(phi) != 0 or max(phi) != 360):
        return "completed result radiation pattern does not cover the full sphere"
    return None


def _deltas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = next((row for row in rows if row["scenario"] == SCENARIOS[0]), None)
    outcomes = []
    fields = ("resonant_frequency_hz", "s11_min_db", "input_impedance_real_ohm",
              "input_impedance_imag_ohm", "vswr_min", "efficiency_fraction", "gain_dbi")
    for row in rows:
        can_compare = bool(baseline and baseline["status"] == row["status"] == "COMPLETED")
        delta = {field: (float(row[field]) - float(baseline[field])
                         if can_compare and row.get(field) is not None and baseline.get(field) is not None else None)
                 for field in fields}
        outcomes.append({"scenario": row["scenario"], "baseline_scenario": SCENARIOS[0],
                         "status": "COMPLETED" if can_compare else "NOT_COMPARABLE",
                         "delta": delta})
    return outcomes


def _simulate_mesh(spec: dict[str, Any], spec_hash: str, geometry: dict[str, Any],
                   output_dir: Path, mesh_resolution_factor: float) -> dict[str, Any]:
    input_hash = expected_input_hash(spec_hash, geometry,
                                     mesh_resolution_factor=mesh_resolution_factor)
    try:
        result = simulate_scenario(
            spec, spec_hash, geometry, output_dir, input_hash=input_hash,
            mesh_resolution_factor=mesh_resolution_factor)
        if isinstance(result, dict) and result.get("status") == "COMPLETED":
            issue = _validate_completion(
                result, output_dir, expected_spec_hash=spec_hash,
                expected_geometry_hash=geometry["geometry_hash_sha256"],
                expected_input_hash=input_hash)
            if issue:
                return {**result, "status": "FAILED", "detail": issue, "metrics": None}
        return result
    except Exception as exc:
        return {"status": "INVALID_INPUT" if isinstance(exc, (GeometryError, ValueError)) else "FAILED",
                "detail": f"{type(exc).__name__}: {exc}", "metrics": None,
                "evidence": {"input_hash_sha256": input_hash}}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: (json.dumps(value, sort_keys=True, allow_nan=False)
                                   if isinstance(value, (dict, list)) else
                                   (None if isinstance(value, float) and not math.isfinite(value) else value))
                             for key, value in row.items()})


def run_experiments(spec_path: Path | None, output_dir: Path,
                    selected: list[str] | None = None, *, include_sweeps: bool = False) -> dict[str, Any]:
    spec, spec_provenance = _load_spec(spec_path)
    names = selected or list(SCENARIOS)
    invalid = sorted(set(names) - set(SCENARIOS))
    if invalid or len(set(names)) != len(names):
        raise ValueError(f"Invalid or duplicate antenna scenarios: {', '.join(invalid) or names}")
    if not names:
        raise ValueError("At least one antenna scenario must be selected")
    for key in ("center_frequency_hz", "element_length_mm", "topology", "trace_width_mm",
                "conductor_thickness_mm", "feed_gap_mm", "meander_turns", "clearance_mm"):
        _record(spec, key)
    antenna = spec["antenna"]
    frequency = antenna["center_frequency_hz"]["value"]
    if (isinstance(frequency, bool) or not isinstance(frequency, (int, float))
            or not math.isfinite(float(frequency)) or frequency <= 0):
        raise ValueError("antenna.center_frequency_hz must be positive")

    output_dir.mkdir(parents=True, exist_ok=True)
    spec_hash = spec_provenance["sha256"]
    runtime = runtime_status()
    rows = []
    refinements: list[dict[str, Any]] = []
    for name in names:
        geometry = None
        try:
            geometry = build_geometry(spec, name)
            coarse = _simulate_mesh(spec, spec_hash, geometry, output_dir,
                                    MESH_REFINEMENT_COARSE_FACTOR)
            result = _simulate_mesh(spec, spec_hash, geometry, output_dir, 1.0)
            refinement = _mesh_refinement(coarse, result)
            if not refinement["converged"] and result.get("status") == "COMPLETED":
                result = {**result, "status": "NON_CONVERGED",
                          "detail": refinement["detail"], "metrics": None}
        except Exception as exc:
            result = {"status": "INVALID_INPUT" if isinstance(exc, (GeometryError, ValueError)) else "FAILED",
                      "detail": f"{type(exc).__name__}: {exc}", "metrics": None,
                      "evidence": {"spec_hash_sha256": spec_hash}}
            refinement = {"status": "BLOCKED", "converged": False,
                          "detail": f"mesh refinement could not run: {type(exc).__name__}: {exc}"}
        rows.append(_scenario_row(name, result, geometry))
        rows[-1]["mesh_refinement"] = refinement
        refinements.append({"scenario": name, **refinement})

    sweeps = []
    if include_sweeps:
        def simulate_sweep(*, scenario: str, overrides: dict[str, Any], output_id: str,
                           input_hash: str) -> dict[str, Any]:
            try:
                geometry = build_geometry(spec, scenario, overrides)
                result = simulate_scenario(spec, spec_hash, geometry, output_dir,
                                           overrides=overrides, input_hash=input_hash)
                if isinstance(result, dict) and result.get("status") == "COMPLETED":
                    issue = _validate_completion(
                        result, output_dir, expected_spec_hash=spec_hash,
                        expected_geometry_hash=geometry["geometry_hash_sha256"],
                        expected_input_hash=input_hash)
                    if issue:
                        return {**result, "status": "FAILED", "detail": issue, "metrics": None}
                return result
            except Exception as exc:
                return {"status": "INVALID_INPUT" if isinstance(exc, (GeometryError, ValueError)) else "FAILED",
                        "detail": f"{type(exc).__name__}: {exc}", "metrics": None,
                        "evidence": {"input_hash_sha256": input_hash}}
        sweeps = run_sweeps(spec, simulate_sweep, spec_hash=spec_hash)
        by_scenario = {row["scenario"]: row for row in rows}
        delta_fields = ("resonant_frequency_hz", "s11_min_db", "input_impedance_real_ohm",
                        "input_impedance_imag_ohm", "vswr_min", "efficiency_fraction", "gain_dbi")
        for case in sweeps:
            nominal = by_scenario.get(case["scenario"])
            metrics = case.get("metrics")
            comparable = bool(nominal and nominal["status"] == case["status"] == "COMPLETED"
                              and isinstance(metrics, dict))
            case["delta_vs_nominal"] = {
                "status": "COMPLETED" if comparable else "NOT_COMPARABLE",
                "baseline_scenario": case["scenario"],
                "delta": {field: (float(metrics[field]) - float(nominal[field])
                                  if comparable and metrics.get(field) is not None and nominal.get(field) is not None
                                  else None)
                          for field in delta_fields},
            }
    requested_all = names == list(SCENARIOS)
    mesh_refinement = {
        "status": "COMPLETED" if refinements and all(item["converged"] for item in refinements) else "PARTIAL_OR_BLOCKED",
        "converged": bool(refinements) and all(item["converged"] for item in refinements),
        "coarse_mesh_resolution_factor": MESH_REFINEMENT_COARSE_FACTOR,
        "fine_mesh_resolution_factor": 1.0,
        "scenarios": refinements,
    }
    completed = (requested_all and all(row["status"] == "COMPLETED" for row in rows)
                 and mesh_refinement["converged"])
    aggregate_status = "COMPLETED" if completed else (
        "NOT_AVAILABLE" if requested_all and all(row["status"] == "NOT_AVAILABLE" for row in rows)
        else "PARTIAL_OR_BLOCKED")
    if include_sweeps and any(row["status"] != "COMPLETED" for row in sweeps):
        aggregate_status = "PARTIAL_OR_BLOCKED"
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "experiment": "RIOSE_MVP2_OPENEMS_ANTENNA",
        "status": aggregate_status,
        "result_class": "SIMULATED" if aggregate_status == "COMPLETED" else "NO_SIMULATION_RESULT",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "host": {"platform": platform.platform(), "python": sys.version.split()[0]},
        "solver": {"name": "openEMS", "execution_mode": "headless", **runtime},
        "spec_provenance": spec_provenance,
        "geometry_contract": {
            "geometry_method": "CSXCAD primitive reconstruction from hardware/spec.yaml",
            "mesh_convergence": "coarse/fine openEMS comparison; only converged scenarios contribute accepted metrics",
            "animal_case": "ASSUMED homogeneous dielectric sensitivity approximation, not tissue validation",
        },
        "antenna_parameters": {key: antenna[key] for key in (
            "center_frequency_hz", "topology", "element_length_mm", "trace_width_mm",
            "feed_gap_mm", "conductor_thickness_mm", "meander_turns", "clearance_mm")},
        "scenario_order": names,
        "scenarios": rows,
        "deltas_vs_free_space": _deltas(rows),
        "mesh_refinement": mesh_refinement,
        "sweeps": sweeps,
        "limitations": [
            "Assumed geometry and material properties are exploratory simulation inputs, not measured results.",
            "The animal case is a homogeneous dielectric approximation, not validated tissue data.",
            "A missing solver, mechanical clash, or failed convergence leaves the gate blocked.",
            "Mesh refinement compares lambda/20 fine and coarser meshes; time-domain energy convergence is checked independently for each mesh.",
        ],
    }
    (output_dir / "antenna_experiments.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    _write_csv(output_dir / "antenna.csv", rows)
    if include_sweeps:
        _write_csv(output_dir / "sweeps.csv", sweeps)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=Path("hardware/spec.yaml"))
    parser.add_argument("--output", type=Path, default=Path("results/mvp2/antenna"))
    parser.add_argument("--scenario", action="append", choices=SCENARIOS,
                        help="Run only named scenario(s); default is all five")
    parser.add_argument("--sweeps", action="store_true", help="Run the material, thickness, feed gap and animal orientation sweeps")
    args = parser.parse_args(argv)
    try:
        result = run_experiments(args.spec, args.output, args.scenario, include_sweeps=args.sweeps)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        parser.error(str(exc))
    print(json.dumps({"status": result["status"], "result_class": result["result_class"],
                      "output": str(args.output), "scenarios": len(result["scenarios"]),
                      "sweeps": len(result["sweeps"])}, sort_keys=True))
    return 0 if result["status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
