"""Create the compact, seed-aware network capacity envelope from run ledgers."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any


GROUP_FIELDS = ("tags", "gateways", "cadence_s", "schedule", "phase_window_s",
                "sf", "payload_bytes", "distribution", "epochs")
METRIC_FIELDS = ("pdr_phy", "mean_phy_latency_s", "mean_airtime_s",
                 "localization_input_availability", "interference_gateway_events",
                 "gateway_reception_diversity_mean", "pdr_conditional_on_rf_path", "runtime_s")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _summary(values: list[float]) -> dict[str, float | int | None]:
    return {"n": len(values),
            "mean": statistics.mean(values) if values else None,
            "sample_sd": statistics.stdev(values) if len(values) > 1 else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None}


def _quality_status(pdr: float | None, schedule_completion: float | None) -> str:
    if pdr is None:
        return "NOT_TESTED"
    if schedule_completion is not None and schedule_completion < 0.95:
        return "INCOMPLETE_SCHEDULE_SIMULATED"
    if pdr >= 0.95:
        return "ROBUST_SIMULATED"
    if pdr >= 0.70:
        return "DEGRADED_SIMULATED"
    if pdr > 0:
        return "OVERLOADED_SIMULATED"
    return "OUTAGE_SIMULATED"


def summarize(inputs: list[Path]) -> dict[str, Any]:
    source_files = []
    records: list[dict[str, Any]] = []
    for path in inputs:
        document = json.loads(path.read_text(encoding="utf-8"))
        source_files.append({"path": str(path.resolve()), "sha256": _sha256(path),
                             "requested_runs": document.get("requested_runs"),
                             "unique_requests": document.get("unique_requests"),
                             "completed_runs": document.get("completed_runs"),
                             "failed_runs": document.get("failed_runs"),
                             "spec_sha256": document.get("spec_sha256")})
        records.extend(document.get("runs", []))

    unique: dict[str, dict[str, Any]] = {}
    for row in records:
        digest = row.get("request_sha256")
        if digest and digest not in unique:
            unique[digest] = row
    runs = list(unique.values())
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in runs:
        config = dict(row.get("configuration", {}))
        config.setdefault("epochs", 3)
        if config.get("schedule") == "SOURCE_TIMESTAMP":
            config["phase_window_s"] = None
        elif config.get("schedule") == "SEEDED_PHASE" and config.get("phase_window_s") is None:
            config["phase_window_s"] = config["cadence_s"]
        elif config.get("schedule") == "NEAR_SYNCHRONIZED" and config.get("phase_window_s") is None:
            config["phase_window_s"] = 0.01
        key = tuple(config.get(field) for field in GROUP_FIELDS)
        groups[key].append({**row, "configuration": config})

    configurations = []
    for key, rows in sorted(groups.items(), key=lambda item: item[0]):
        config = dict(zip(GROUP_FIELDS, key, strict=True))
        completed = [row for row in rows if row.get("status") == "SIMULATED"]
        failed = [row for row in rows if row.get("status") != "SIMULATED"]
        means = {}
        for field in METRIC_FIELDS:
            values = [float(row[field]) for row in completed if row.get(field) is not None]
            means[field] = _summary(values)
        pdr_mean = means["pdr_phy"]["mean"]
        outcomes: Counter[str] = Counter()
        packet_outcomes: Counter[str] = Counter()
        for row in completed:
            outcomes.update(row.get("gateway_outcomes", {}))
            packet_outcomes.update(row.get("packet_outcome_counts", {}))
        tx_attempted = sum(int(row.get("tx_attempted", 0)) for row in completed)
        phy_received = sum(int(row.get("phy_received_packets", 0)) for row in completed)
        rf_reachable = sum(int(row.get("rf_reachable_tx_packets", 0)) for row in completed)
        rf_reachable_received = sum(int(row.get("rf_reachable_received_packets", 0)) for row in completed)
        requested_packets = sum(int(row.get("requested_packets", 0)) for row in completed)
        schedule_completion = tx_attempted / requested_packets if requested_packets else None
        runtime = [float(row["runtime_s"]) for row in completed if row.get("runtime_s") is not None]
        run_evidence = []
        for row in completed:
            workspace = Path(row["workspace"])
            manifest_path = workspace / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            run_evidence.append({
                "run_id": row["run_id"], "seed": row["configuration"]["seed"],
                "request_sha256": row["request_sha256"],
                "manifest_sha256": _sha256(manifest_path),
                "raw_output_sha256": row.get("raw_output_sha256"),
                "network_output_sha256": row.get("network_output_sha256"),
                "generated_config_sha256": manifest.get("generated_config_sha256"),
                "trajectory_sha256": manifest.get("trajectory_sha256"),
                "experiment_spec_sha256": manifest.get("experiment_spec_sha256"),
                "network_artifact_sha256": manifest.get("network", {}).get("artifact_sha256", {}),
                "riose_sha": row.get("riose_sha"), "riose_dirty": row.get("riose_dirty"),
                "frequencia_sha": row.get("frequencia_sha"),
                "frequencia_dirty": row.get("frequencia_dirty"),
                "tx_attempted": row.get("tx_attempted"),
                "phy_received_packets": row.get("phy_received_packets"),
                "pdr_phy": row.get("pdr_phy"), "pdr_denominator": row.get("pdr_denominator"),
                "tx_schedule_completion_rate": row.get("tx_schedule_completion_rate"),
                "pdr_over_requested_packets": row.get("pdr_over_requested_packets"),
                "packet_outcome_counts": row.get("packet_outcome_counts"),
                "packet_outcome_denominator_tx": row.get("packet_outcome_denominator_tx"),
                "packet_outcome_requested_denominator": row.get("packet_outcome_requested_denominator"),
                "rf_reachable_tx_packets": row.get("rf_reachable_tx_packets"),
                "rf_reachable_received_packets": row.get("rf_reachable_received_packets"),
                "pdr_conditional_on_rf_path": row.get("pdr_conditional_on_rf_path"),
                "requested_config": row.get("requested_config"),
                "effective_config": row.get("effective_config"),
                "runtime_s": row.get("runtime_s"),
            })
        configurations.append({
            "configuration": config,
            "quality_status_by_mean_pdr": _quality_status(pdr_mean, schedule_completion),
            "quality_thresholds": {"robust_min_pdr_phy": 0.95,
                                   "degraded_min_pdr_phy": 0.70,
                                   "thresholds_are_product_requirements": False},
            "run_count": len(rows), "completed_run_count": len(completed),
            "failed_run_count": len(failed), "seeds": sorted({
                int(row["configuration"]["seed"]) for row in rows
                if row.get("configuration", {}).get("seed") is not None}),
            "set_ids": sorted({row.get("set_id") for row in rows if row.get("set_id")}),
            "pdr_phy_numerator": phy_received, "pdr_phy_denominator": tx_attempted,
            "pdr_phy_pooled": phy_received / tx_attempted if tx_attempted else None,
            "pdr_over_requested_packets": phy_received / requested_packets if requested_packets else None,
            "tx_schedule_completion_rate": tx_attempted / requested_packets if requested_packets else None,
            "rf_reachable_tx_packets": rf_reachable,
            "rf_reachable_received_packets": rf_reachable_received,
            "pdr_conditional_on_rf_path_pooled": (
                rf_reachable_received / rf_reachable if rf_reachable else None),
            "requested_packet_count": requested_packets,
            "gateway_event_outcomes": dict(sorted(outcomes.items())),
            "packet_outcome_counts": dict(sorted(packet_outcomes.items())),
            "packet_outcome_denominator_tx": tx_attempted,
            "packet_outcome_requested_denominator": requested_packets,
            "metrics": means,
            "runtime": {"total_s": sum(runtime), "max_s": max(runtime) if runtime else None,
                        "sample_count": len(runtime)},
            "request_hashes": sorted({row["request_sha256"] for row in rows if row.get("request_sha256")}),
            "run_ids": sorted({row["run_id"] for row in completed if row.get("run_id")}),
            "run_evidence": run_evidence,
            "failed_runs": [{"request_sha256": row.get("request_sha256"),
                             "error": row.get("error"),
                             "configuration": row.get("configuration")} for row in failed],
        })

    failed_runs = [row for row in runs if row.get("status") != "SIMULATED"]
    return {
        "schema_version": "riose.network-scale-capacity-envelope/v1",
        "classification": "SIMULATED",
        "pdr_definition": "unique packets received by at least one gateway / packets with TX start",
        "latency_definition": "ns-3 gateway PHY RX end timestamp minus TX start timestamp",
        "localization_input_definition": (
            "transmitted packet epochs with at least 3 distinct non-null detector/clock timestamps "
            "divided by packets with TX start"),
        "quality_status_is_pdr_only": True,
        "sources": source_files,
        "requested_run_rows": len(records), "unique_request_count": len(runs),
        "completed_unique_runs": sum(row.get("status") == "SIMULATED" for row in runs),
        "failed_unique_runs": len(failed_runs),
        "failed_runs": [{"request_sha256": row.get("request_sha256"),
                         "error": row.get("error"),
                         "configuration": row.get("configuration")} for row in failed_runs],
        "configurations": configurations,
        "limitations": [
            "PDR ends at gateway PHY; application delivery is not modeled.",
            "Duty-cycle limiting and gateway outage/recovery are not modeled.",
            "A PDR shortfall must be separated from Sionna NO_PATH and sensitivity outcomes before attributing it to contention.",
            "The status thresholds are analysis labels, not product requirements or field capacity claims.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True,
                        help="campaign-results.json; repeat for supplemental ledgers")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False,
                                      allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"unique_request_count": result["unique_request_count"],
                      "completed_unique_runs": result["completed_unique_runs"],
                      "failed_unique_runs": result["failed_unique_runs"],
                      "configurations": len(result["configurations"]),
                      "output": str(args.output)}, indent=2))
    return 0 if not result["failed_unique_runs"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
