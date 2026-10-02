"""Optional Sionna RT capability/scenario runner; never blocks core validation."""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import re
from importlib import metadata
from pathlib import Path
from typing import Any

from .capabilities import detect_capabilities


SCHEMA_VERSION = "riose.sionna.experiment/v1"
SCENARIOS = ("TAG_TO_RECEIVER_10M", "TAG_TO_RECEIVER_WITH_OBSTACLE", "TAG_TO_RECEIVER_ORIENTATION_VARIANT")


def _version(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def _sionna_version() -> str | None:
    return _version("sionna-rt") or _version("sionna")


def run_experiment(output_dir: Path, spec_path: Path | None = None,
                   capabilities: dict[str, Any] | None = None,
                   adapter_name: str | None = None) -> dict[str, Any]:
    caps = capabilities or detect_capabilities()
    adapter_name = adapter_name or os.environ.get("RIOSE_SIONNA_ADAPTER")
    output_dir.mkdir(parents=True, exist_ok=True)
    # Prevent artifacts from an earlier successful run being mistaken for the
    # results of a skipped or failed run.
    for scenario in SCENARIOS:
        (output_dir / f"{scenario.lower()}.json").unlink(missing_ok=True)
    (output_dir / "obstacle.obj").unlink(missing_ok=True)
    rows: list[dict[str, Any]] = []
    eligible = bool(caps.get("CUDA_AVAILABLE") and caps.get("SIONNA_AVAILABLE"))
    for scenario in SCENARIOS:
        base = {"scenario": scenario, "experiment": "OPTIONAL_GPU_EXPERIMENT",
                "gpu_type": caps.get("GPU_TYPE", "UNKNOWN"),
                "cuda_available": bool(caps.get("CUDA_AVAILABLE")),
                "sionna_available": bool(caps.get("SIONNA_AVAILABLE")),
                "sionna_version": _sionna_version() if caps.get("SIONNA_AVAILABLE") else None,
                "status": "SIMULATED"}
        if not eligible:
            rows.append({**base, "status": "SKIPPED_OPTIONAL",
                         "detail": "CUDA and Sionna RT are both required for this optional experiment",
                         "result_class": "ENVIRONMENT_CAPABILITY_ONLY", "metrics": None})
            continue
        try:
            if adapter_name:
                adapter = importlib.import_module(adapter_name)
                result = adapter.simulate(scenario=scenario, spec_path=str(spec_path) if spec_path else None,
                                          output_dir=str(output_dir))
            else:
                from . import sionna_adapter
                result = sionna_adapter.simulate(scenario=scenario, spec_path=spec_path,
                                                 output_dir=output_dir)
            if not isinstance(result, dict) or result.get("status") != "COMPLETED":
                rows.append({**base, "status": "FAILED",
                             "detail": result.get("detail", "adapter did not complete") if isinstance(result, dict) else "invalid adapter response",
                             "result_class": "NO_SIMULATION_RESULT", "metrics": None})
                continue
            metrics = result.get("metrics")
            evidence = result.get("evidence")
            valid_metrics = (
                isinstance(metrics, dict)
                and type(metrics.get("path_count")) is int
                and metrics["path_count"] >= 0
                and type(metrics.get("tag_receiver_distance_m")) in (int, float)
                and math.isclose(metrics["tag_receiver_distance_m"], 10.0)
                and type(metrics.get("summed_path_coefficient_power_linear")) in (int, float)
                and math.isfinite(metrics["summed_path_coefficient_power_linear"])
                and metrics["summed_path_coefficient_power_linear"] >= 0
            )
            evidence_fields = ("solver", "solver_version", "mitsuba_variant", "seed",
                               "deterministic", "frequency_hz", "spec_sha256", "obstacle_sha256")
            valid_evidence = (
                isinstance(evidence, dict)
                and all(field in evidence for field in evidence_fields)
                and all(isinstance(evidence[field], str) and evidence[field]
                        for field in ("solver", "solver_version", "mitsuba_variant"))
                and evidence["mitsuba_variant"].startswith("cuda_")
                and evidence["seed"] == 42
                and evidence["deterministic"] is True
                and type(evidence["frequency_hz"]) in (int, float)
                and math.isfinite(evidence["frequency_hz"])
                and evidence["frequency_hz"] > 0
                and _valid_optional_sha256(evidence["spec_sha256"], required=spec_path is not None)
                and _valid_optional_sha256(
                    evidence["obstacle_sha256"],
                    required=scenario == "TAG_TO_RECEIVER_WITH_OBSTACLE",
                )
            )
            if not valid_metrics or not valid_evidence:
                rows.append({**base, "status": "FAILED",
                             "detail": "Sionna adapter returned incomplete metrics or solver evidence",
                             "result_class": "NO_SIMULATION_RESULT", "metrics": None})
                continue
            rows.append({**base, "status": "COMPLETED", "result_class": "SIMULATED",
                         "detail": result.get("detail", ""), "metrics": metrics,
                         "evidence": evidence})
        except Exception as exc:  # optional plugin failures are recorded, never promoted to core failures
            rows.append({**base, "status": "FAILED", "detail": f"{type(exc).__name__}: {exc}",
                         "result_class": "NO_SIMULATION_RESULT", "metrics": None})
    statuses = {row["status"] for row in rows}
    status = "SKIPPED_OPTIONAL" if statuses == {"SKIPPED_OPTIONAL"} else (
        "COMPLETED" if rows and statuses == {"COMPLETED"} else "PARTIAL_OR_BLOCKED"
    )
    manifest = {"schema_version": SCHEMA_VERSION, "experiment": "OPTIONAL_GPU_EXPERIMENT",
                "status": status, "required": False, "capabilities": caps,
                "scenarios": rows, "physical_hardware_used": False,
                "limitations": ["Sionna RT results are exploratory and do not replace openEMS or physical RF validation."]}
    (output_dir / "sionna_experiment.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def _valid_optional_sha256(value: Any, *, required: bool) -> bool:
    if value is None:
        return not required
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results/mvp2/antenna/sionna"))
    args = parser.parse_args(argv)
    result = run_experiment(args.output, args.spec)
    print(json.dumps({"status": result["status"], "scenarios": len(result["scenarios"]),
                      "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
