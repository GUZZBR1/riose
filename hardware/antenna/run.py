"""Headless openEMS experiment contract for the RIOSE ear-tag antenna.

This command deliberately refuses to manufacture RF metrics. A solver adapter
must return raw, solver-derived data before metric fields can be populated.
When openEMS Python bindings are absent, it still emits a machine-readable
manifest for all five requested scenarios with NOT_AVAILABLE status.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import SCENARIOS

SCHEMA_VERSION = "riose.antenna.experiments/v1"
METRIC_FIELDS = (
    "resonant_frequency_hz", "s11_min_db", "input_impedance_real_ohm",
    "input_impedance_imag_ohm", "vswr_min", "efficiency_fraction",
    "gain_dbi", "s11_curve_path", "radiation_pattern_path",
)
NUMERIC_METRICS = tuple(field for field in METRIC_FIELDS if not field.endswith("_path"))
SCENARIO_ASSUMPTIONS = {
    "ANTENNA_FREE_SPACE": [],
    "ANTENNA_WITH_PCB": ["PCB geometry/material approximation required"],
    "ANTENNA_WITH_BATTERY": ["Battery geometry/material approximation required"],
    "ANTENNA_WITH_ENCLOSURE": ["Enclosure geometry/material approximation required"],
    "ANTENNA_NEAR_ANIMAL_APPROXIMATION": [
        "Experimental homogeneous dielectric approximation; not animal tissue validation"
    ],
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _record(spec: dict[str, Any], key: str, default: dict[str, Any]) -> dict[str, Any]:
    value = spec.get("antenna", {}).get(key)
    if isinstance(value, dict) and "value" in value:
        return value
    return default


def _load_spec(path: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if path is None:
        return {}, {"path": None, "sha256": None, "status": "NO_SPEC_PROVIDED"}
    if not path.is_file():
        raise FileNotFoundError(f"Hardware specification not found: {path}")
    try:
        import yaml  # optional; project may choose to make PyYAML a dependency
    except ImportError as exc:
        raise RuntimeError("Reading hardware/spec.yaml requires PyYAML") from exc
    raw = path.read_bytes()
    parsed = yaml.safe_load(raw) or {}
    if not isinstance(parsed, dict):
        raise ValueError("hardware spec YAML root must be a mapping")
    return parsed, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "status": "LOADED"}


def _openems_available() -> tuple[bool, str | None]:
    try:
        present = importlib.util.find_spec("openEMS") is not None and importlib.util.find_spec("CSXCAD") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        present = False
    return present, ("openEMS and CSXCAD Python bindings detected" if present else None)


def _scenario_row(name: str, solver_status: str, detail: str | None,
                  assumptions: list[str], frequency: dict[str, Any], topology: dict[str, Any],
                  element_length: dict[str, Any], feed: dict[str, Any], clearance: dict[str, Any]) -> dict[str, Any]:
    row = {
        "scenario": name,
        "status": solver_status,
        "result_class": "SIMULATED" if solver_status == "COMPLETED" else "NO_SIMULATION_RESULT",
        "detail": detail or "",
        "assumptions": "; ".join(assumptions),
        "center_frequency_hz": frequency["value"],
        "center_frequency_status": frequency.get("status", "ASSUMED"),
        "topology": topology["value"],
        "topology_status": topology.get("status", "ASSUMED"),
        "element_length_mm": element_length["value"],
        "element_length_status": element_length.get("status", "ASSUMED"),
        "feed_mm": feed["value"],
        "feed_status": feed.get("status", "ASSUMED"),
        "clearance_mm": clearance["value"],
        "clearance_status": clearance.get("status", "ASSUMED"),
    }
    # A missing solver must be represented by empty CSV cells/JSON nulls, not
    # analytic placeholders or guessed simulation values.
    row.update({field: None for field in METRIC_FIELDS})
    return row


def run_experiments(spec_path: Path | None, output_dir: Path,
                    selected: list[str] | None = None) -> dict[str, Any]:
    spec, spec_provenance = _load_spec(spec_path)
    antenna_spec = spec.get("antenna", {}) if isinstance(spec.get("antenna", {}), dict) else {}
    freq = _record(spec, "center_frequency_hz", {
        "value": 915_000_000, "unit": "Hz", "source": "MVP2 initial sub-GHz candidate",
        "status": "ASSUMED",
    })
    topology = _record(spec, "topology", {
        "value": "meandered_monopole_reference", "unit": "text",
        "source": "MVP2 initial reference; requires design review", "status": "ASSUMED",
    })
    element_length = _record(spec, "element_length_mm", {
        "value": 82.0, "unit": "mm", "source": "approximately free-space quarter-wave at 915 MHz",
        "status": "ASSUMED",
    })
    feed = _record(spec, "feed_mm", {
        "value": 0.0, "unit": "mm", "source": "initial antenna coordinate convention",
        "status": "ASSUMED",
    })
    clearance = _record(spec, "clearance_mm", {
        "value": 2.0, "unit": "mm", "source": "initial design placeholder", "status": "ASSUMED",
    })
    # Enforce milestone provenance: no field may claim physical measurement.
    for label, item in (("center_frequency_hz", freq), ("topology", topology),
                        ("element_length_mm", element_length), ("feed_mm", feed),
                        ("clearance_mm", clearance)):
        if str(item.get("status", "")).upper() == "MEASURED":
            raise ValueError(f"antenna.{label} cannot be MEASURED in the digital-only MVP2")
        if "value" not in item or "unit" not in item or "source" not in item or "status" not in item:
            raise ValueError(f"antenna.{label} must contain value, unit, source, and status")
    if not isinstance(freq["value"], (int, float)) or not math.isfinite(float(freq["value"])) or freq["value"] <= 0:
        raise ValueError("antenna.center_frequency_hz must be a positive finite number")
    names = selected or list(SCENARIOS)
    invalid = sorted(set(names) - set(SCENARIOS))
    if invalid:
        raise ValueError(f"Unknown antenna scenarios: {', '.join(invalid)}")
    available, _ = _openems_available()
    adapter = os.environ.get("RIOSE_OPENEMS_ADAPTER")
    if available and adapter:
        # Optional adapter contract: a Python module exposing simulate(spec,
        # scenario, output_dir) -> dict with status and solver-derived metrics.
        import importlib
        backend = importlib.import_module(adapter)
    else:
        backend = None

    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in names:
        if backend is None:
            status = "NOT_AVAILABLE" if not available else "ADAPTER_NOT_CONFIGURED"
            detail = ("openEMS/CSXCAD bindings are absent; no RF metrics were generated"
                      if not available else "Bindings detected, but RIOSE_OPENEMS_ADAPTER is not configured")
            rows.append(_scenario_row(name, status, detail, SCENARIO_ASSUMPTIONS[name],
                                      freq, topology, element_length, feed, clearance))
            continue
        result = backend.simulate(spec=spec, scenario=name, output_dir=str(output_dir))
        if not isinstance(result, dict) or result.get("status") != "COMPLETED":
            detail = result.get("detail", "solver adapter did not complete") if isinstance(result, dict) else "invalid adapter response"
            rows.append(_scenario_row(name, "FAILED", detail, SCENARIO_ASSUMPTIONS[name],
                                      freq, topology, element_length, feed, clearance))
            continue
        metrics = result.get("metrics", {})
        evidence = result.get("evidence", {})
        missing = [field for field in METRIC_FIELDS if metrics.get(field) in (None, "")]
        for field in NUMERIC_METRICS:
            try:
                if not math.isfinite(float(metrics.get(field))):
                    missing.append(field)
            except (TypeError, ValueError):
                missing.append(field)
        for field in ("solver_version", "geometry_hash", "mesh", "converged"):
            if evidence.get(field) in (None, "", False):
                missing.append(f"evidence.{field}")
        geometry_hash = str(evidence.get("geometry_hash", ""))
        if geometry_hash and (len(geometry_hash) != 64 or any(c not in "0123456789abcdef" for c in geometry_hash.lower())):
            missing.append("evidence.geometry_hash_sha256")
        artifact_paths = [metrics.get("s11_curve_path"), metrics.get("radiation_pattern_path")]
        for artifact in artifact_paths:
            if artifact and not (output_dir / artifact).is_file():
                missing.append(f"artifact.{artifact}")
        if missing:
            detail = "incomplete openEMS result/provenance: " + ", ".join(sorted(set(missing)))
            rows.append(_scenario_row(name, "FAILED", detail, SCENARIO_ASSUMPTIONS[name],
                                      freq, topology, element_length, feed, clearance))
            continue
        row = _scenario_row(name, "COMPLETED", result.get("detail"),
                            SCENARIO_ASSUMPTIONS[name], freq, topology, element_length, feed, clearance)
        row.update({field: metrics[field] for field in METRIC_FIELDS})
        row["solver_evidence"] = evidence
        rows.append(row)

    aggregate_status = "COMPLETED" if rows and all(row["status"] == "COMPLETED" for row in rows) else (
        "NOT_AVAILABLE" if rows and all(row["status"] == "NOT_AVAILABLE" for row in rows) else "PARTIAL_OR_BLOCKED"
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "experiment": "RIOSE_MVP2_OPENEMS_ANTENNA",
        "status": aggregate_status,
        "result_class": "SIMULATED" if aggregate_status == "COMPLETED" else "NO_SIMULATION_RESULT",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "host": {"platform": platform.platform(), "python": sys.version.split()[0]},
        "solver": {"name": "openEMS", "python_bindings_available": available,
                   "execution_mode": "headless", "adapter": adapter if backend else None},
        "spec_provenance": spec_provenance,
        "geometry_contract": {
            "mechanical_root_key": "mechanical",
            "expected_records": "{value, unit, source, status}",
            "consumed_geometry": "Adapter may consume mechanical PCB, battery, and enclosure records or a validated mesh export.",
            "note": "No geometry is inferred from dimensions unless the adapter reports the generated mesh provenance.",
        },
        "antenna_parameters": {"center_frequency_hz": freq, "topology": topology,
                               "element_length_mm": element_length, "feed_mm": feed,
                               "clearance_mm": clearance},
        "scenario_order": names,
        "scenarios": rows,
        "limitations": [
            "The animal-proximity case is an experimental material approximation, not tissue validation.",
            "Assumed geometry/material properties are not measured physical results.",
            "A missing solver or adapter produces no RF metrics; null fields are intentional.",
        ],
    }
    json_path = output_dir / "antenna_experiments.json"
    json_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    csv_path = output_dir / "antenna.csv"
    fields = list(rows[0]) if rows else []
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=Path("hardware/spec.yaml"))
    parser.add_argument("--output", type=Path, default=Path("results/mvp2/antenna"))
    parser.add_argument("--scenario", action="append", choices=SCENARIOS,
                        help="Run only named scenario(s); default is all five")
    args = parser.parse_args(argv)
    try:
        result = run_experiments(args.spec if args.spec.exists() else None,
                                 args.output, args.scenario)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        parser.error(str(exc))
    print(json.dumps({"status": result["status"], "result_class": result["result_class"],
                      "output": str(args.output), "scenarios": len(result["scenarios"])}, sort_keys=True))
    return 0 if result["status"] in ("COMPLETED", "NOT_AVAILABLE") else 2


if __name__ == "__main__":
    raise SystemExit(main())
