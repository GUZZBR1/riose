"""Deterministic one-factor RF sweep planning and failure-preserving results."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Callable

from . import SCENARIOS
from .geometry import build_geometry
from .openems_backend import expected_input_hash

SWEEP_STATUS = {"COMPLETED", "FAILED", "NOT_AVAILABLE", "NON_CONVERGED", "INVALID_INPUT"}
SWEEP_TARGETS = {
    "materials.enclosure_relative_permittivity": "enclosure_relative_permittivity",
    "mechanical.enclosure.wall_thickness_mm": "enclosure_wall_thickness_mm",
    "antenna.feed_gap_mm": "feed_gap_mm",
    "antenna.animal_orientation_deg": "animal_orientation_deg",
}
SWEEP_UNITS = {"material": "ratio", "thickness": "mm", "gap": "mm", "animal_orientation": "deg"}


class SweepError(ValueError):
    """Sweep configuration is invalid or incomplete."""


def plan_sweeps(spec: dict[str, Any], *, spec_hash: str | None = None) -> list[dict[str, Any]]:
    """Expand the central sweep spec into stable, individually hashed cases."""
    config = spec.get("antenna", {}).get("sweeps")
    if not isinstance(config, dict):
        raise SweepError("antenna.sweeps must define material, thickness, gap and animal_orientation")
    missing = sorted(set(("material", "thickness", "gap", "animal_orientation")) - config.keys())
    if missing:
        raise SweepError(f"missing required sweep axes: {', '.join(missing)}")
    spec_hash = spec_hash or hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":"),
                                                       allow_nan=False).encode("utf-8")).hexdigest()
    cases: list[dict[str, Any]] = []
    for name in ("material", "thickness", "gap", "animal_orientation"):
        axis = config[name]
        if not isinstance(axis, dict):
            raise SweepError(f"antenna.sweeps.{name} must be a mapping")
        parameter = axis.get("parameter")
        scenario = axis.get("scenario")
        target = SWEEP_TARGETS.get(parameter)
        if target is None:
            raise SweepError(f"unsupported sweep parameter for {name}: {parameter!r}")
        if scenario not in SCENARIOS:
            raise SweepError(f"unknown antenna scenario in {name} sweep: {scenario!r}")
        values = axis.get("values")
        if not isinstance(values, list) or not values:
            raise SweepError(f"antenna.sweeps.{name}.values must be a non-empty list")
        seen_values: set[tuple[str, str]] = set()
        for index, item in enumerate(values):
            if not isinstance(item, dict) or not {"value", "unit", "source", "status"} <= item.keys():
                raise SweepError(f"antenna.sweeps.{name}.values[{index}] needs value, unit, source and status")
            if not isinstance(item["source"], str) or not item["source"].strip():
                raise SweepError(f"antenna.sweeps.{name}.values[{index}].source must be a non-empty string")
            if str(item["unit"]).strip().lower() != SWEEP_UNITS[name]:
                raise SweepError(
                    f"antenna.sweeps.{name}.values[{index}].unit must be {SWEEP_UNITS[name]}"
                )
            status = str(item["status"]).upper()
            if status not in {"ASSUMED", "DATASHEET", "SIMULATED"}:
                raise SweepError(f"antenna.sweeps.{name}.values[{index}] has forbidden status {status}")
            value = item["value"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise SweepError(f"antenna.sweeps.{name}.values[{index}].value must be finite numeric")
            if name != "animal_orientation" and value <= 0:
                raise SweepError(f"antenna.sweeps.{name}.values[{index}].value must be positive")
            if name == "animal_orientation" and value not in (0, 90):
                raise SweepError("animal_orientation sweep currently supports 0 and 90 degrees")
            key = (str(value), str(item["unit"]))
            if key in seen_values:
                raise SweepError(f"duplicate sweep value in {name}: {value} {item['unit']}")
            seen_values.add(key)
            case = {
                "sweep": name,
                "index": index,
                "scenario": scenario,
                "parameter": parameter,
                "override_key": target,
                "value": value,
                "unit": str(item["unit"]),
                "source": str(item["source"]),
                "provenance": status,
            }
            overrides = {target: value}
            try:
                geometry = build_geometry(spec, scenario, overrides)
                case["input_hash_sha256"] = expected_input_hash(spec_hash, geometry, overrides)
            except (ValueError, KeyError, TypeError) as exc:
                # A bad override is a case-level result; preserve it in the manifest
                # and continue planning the other values in this sweep.
                case["status"] = "INVALID_INPUT"
                case["detail"] = f"{type(exc).__name__}: {exc}"
                case["input_hash_sha256"] = hashlib.sha256(json.dumps(
                    {"spec_hash": spec_hash, "case": case}, sort_keys=True,
                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
            case["case_id"] = f"{name}-{index:03d}-{case['input_hash_sha256'][:12]}"
            cases.append(case)
    return cases


def run_sweeps(spec: dict[str, Any], simulate: Callable[..., dict[str, Any]], *,
               spec_hash: str | None = None) -> list[dict[str, Any]]:
    """Run planned cases; exceptions and bad result states remain visible."""
    results = []
    for case in plan_sweeps(spec, spec_hash=spec_hash):
        if case.get("status") == "INVALID_INPUT":
            results.append({**case, "detail": case["detail"], "metrics": None,
                            "evidence": None, "s11_curve": None,
                            "radiation_pattern": None})
            continue
        try:
            result = simulate(scenario=case["scenario"],
                              overrides={case["override_key"]: case["value"]},
                              output_id=case["case_id"], input_hash=case["input_hash_sha256"])
            status = result.get("status") if isinstance(result, dict) else None
            if status not in SWEEP_STATUS:
                status, detail = "FAILED", "sweep simulator returned an invalid result status"
            else:
                detail = str(result.get("detail", ""))
            row = {**case, "status": status, "detail": detail}
            if isinstance(result, dict):
                row["metrics"] = result.get("metrics")
                row["evidence"] = result.get("evidence")
                row["s11_curve"] = result.get("s11_curve")
                row["radiation_pattern"] = result.get("radiation_pattern")
        except Exception as exc:  # retain a row instead of dropping failed cases
            row = {**case, "status": "FAILED", "detail": f"{type(exc).__name__}: {exc}",
                   "metrics": None, "evidence": None, "s11_curve": None,
                   "radiation_pattern": None}
        results.append(row)
    return results
