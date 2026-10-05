"""Deterministic dynamic Localization V2 stress campaign (SIMULATED only).

The analytic radio stage turns synthetic truth positions into receiver arrival
timestamps. The V2 estimator receives only anchors, timestamps, uncertainty,
and calibration records. Truth is used by the scorer after estimation.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import subprocess
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from riose.products.livestock_tracking.localization.tdoa_v2 import (  # noqa: E402
    SPEED_OF_LIGHT_M_S,
    ClockCalibration,
    estimate_tdoa_v2,
    fit_clock_calibration,
)

BOUNDS = ((0.0, 1000.0), (0.0, 1000.0))
BAD_POSITION_ERROR_M = 10.0  # Predeclared engineering evaluation threshold; not a physical limit.
ANCHORS = {
    "A": (0.0, 0.0), "B": (1000.0, 50.0),
    "C": (920.0, 1000.0), "D": (100.0, 870.0),
}
EPOCHS = 24
DT_S = 1.0


@dataclass(frozen=True)
class Case:
    name: str
    trajectory: str
    fault: str = "none"
    fault_start: int | None = None
    fault_end: int | None = None
    clock_offset_ns: float = 0.0
    clock_drift_ppm: float = 0.0
    jitter_ns: float = 0.0
    quantum_ns: float = 0.0
    packet_loss_probability: float = 0.0
    geometry: str = "good"


CASES = (
    Case("static_control", "STATIC"),
    Case("straight_walk", "STRAIGHT_WALK"),
    Case("turn", "TURN"),
    Case("stop_and_go", "STOP_AND_GO"),
    Case("curve", "CURVE"),
    Case("boundary_crossing", "BOUNDARY_CROSSING"),
    Case("bad_geometry", "STRAIGHT_WALK", geometry="near_collinear"),
    Case("bad_zone_crossing", "STRAIGHT_WALK", "anchor_off_pair", 10, 15),
    Case("anchor_loss_recovery", "STRAIGHT_WALK", "anchor_off", 8, 14),
    Case("two_anchor_loss_recovery", "STRAIGHT_WALK", "anchor_off_pair", 8, 14),
    Case("clock_offset_identity", "STATIC", "identity_calibration", clock_offset_ns=20.0),
    Case("clock_drift_corrected", "STRAIGHT_WALK", "none", clock_drift_ppm=20.0),
    Case("clock_drift_wrong_calibration", "STRAIGHT_WALK", "wrong_calibration", clock_drift_ppm=20.0),
    Case("clock_drift_missing_calibration", "STRAIGHT_WALK", "missing_calibration", clock_drift_ppm=20.0),
    Case("clock_drift_stale_calibration", "STRAIGHT_WALK", "stale_calibration", clock_drift_ppm=20.0),
    Case("jitter_2ns", "STRAIGHT_WALK", "none", jitter_ns=2.0),
    Case("jitter_10ns", "STRAIGHT_WALK", "none", jitter_ns=10.0),
    Case("quantization_1ns", "STRAIGHT_WALK", "none", quantum_ns=1.0),
    Case("missing_timestamp", "STRAIGHT_WALK", "timestamp_missing", 9, 10),
    Case("corrupted_timestamp", "STRAIGHT_WALK", "timestamp_corrupt", 9, 10),
    Case("stale_timestamp", "STRAIGHT_WALK", "timestamp_stale", 9, 10),
    Case("duplicate_timestamp", "STRAIGHT_WALK", "timestamp_duplicate", 9, 10),
    Case("packet_loss_25pct", "CURVE", "packet_loss", packet_loss_probability=0.25),
    Case("burst_packet_loss", "CURVE", "packet_loss_burst", 8, 12),
    Case("move_plus_anchor_loss", "TURN", "anchor_off", 8, 14),
    Case("bad_geometry_plus_jitter", "STRAIGHT_WALK", "none", jitter_ns=10.0, geometry="near_collinear"),
    Case("drift_plus_packet_loss", "CURVE", "packet_loss", clock_drift_ppm=20.0, packet_loss_probability=0.25),
    Case("jitter_plus_recovery", "STOP_AND_GO", "anchor_off", 8, 14, jitter_ns=2.0),
)


def trajectory(kind: str, t: float) -> tuple[float, float]:
    """Return a deterministic synthetic kinematic path in the 0–1000 m area."""
    if kind == "STATIC":
        return 500.0, 500.0
    if kind == "STRAIGHT_WALK":
        return 180.0 + 22.0 * t, 420.0
    if kind == "TURN":
        if t < 10:
            return 250.0 + 25.0 * t, 300.0
        return 500.0, 300.0 + 25.0 * (t - 10.0)
    if kind == "STOP_AND_GO":
        distance = 0.0 if t < 4 else 20.0 * min(t - 4, 6) if t < 10 else 120.0
        distance += 20.0 * max(t - 14, 0.0)
        return 250.0 + distance, 400.0
    if kind == "CURVE":
        angle = t * 0.075
        return 500.0 + 260.0 * math.cos(angle), 500.0 + 260.0 * math.sin(angle)
    if kind == "BOUNDARY_CROSSING":
        return 15.0 + 30.0 * t, 500.0
    raise ValueError(f"unknown trajectory {kind}")


def _active(case: Case, fault: str, epoch: int) -> bool:
    return case.fault == fault and case.fault_start is not None and case.fault_start <= epoch < case.fault_end


def _fault_active(case: Case, epoch: int) -> bool:
    if case.fault_start is not None:
        return any(_active(case, fault, epoch) for fault in (
            "anchor_off", "anchor_off_pair", "timestamp_missing", "timestamp_corrupt",
            "timestamp_stale", "timestamp_duplicate", "packet_loss_burst"))
    return (case.fault != "none" or case.clock_offset_ns != 0.0
            or case.clock_drift_ppm != 0.0 or case.jitter_ns != 0.0
            or case.quantum_ns != 0.0 or case.packet_loss_probability != 0.0
            or case.geometry != "good")


def _geometry(case: Case) -> dict[str, tuple[float, float]]:
    if case.geometry == "near_collinear":
        return {"A": (0.0, 490.0), "B": (330.0, 500.0),
                "C": (670.0, 510.0), "D": (1000.0, 520.0)}
    return ANCHORS


def _calibrations(case: Case, seed: int, *, wrong: bool = False) -> dict[str, ClockCalibration]:
    records = {}
    refs = np.linspace(0.0, 30.0, 7)
    for index, anchor in enumerate(ANCHORS):
        factor = (-1.0, -1 / 3, 1 / 3, 1.0)[index]
        offset = case.clock_offset_ns * 1e-9 * factor
        drift = case.clock_drift_ppm * factor
        local = refs + offset + (refs - refs[0]) * drift * 1e-6
        rng = np.random.default_rng(seed + 7919 * (index + 1))
        # Calibration timestamps share the declared sensor jitter/quantization.
        if case.jitter_ns:
            local += rng.normal(0.0, case.jitter_ns * 1e-9, len(refs))
        if case.quantum_ns:
            quantum_s = case.quantum_ns * 1e-9
            local = np.round(local / quantum_s) * quantum_s
        record = fit_clock_calibration(refs, local)
        if wrong:
            record = ClockCalibration(
                offset_s=record.offset_s + 200e-9,
                drift_ppm=record.drift_ppm + 20.0,
                reference_epoch_s=record.reference_epoch_s,
                offset_std_s=record.offset_std_s,
                drift_std_ppm=record.drift_std_ppm,
                calibration_epoch_s=record.calibration_epoch_s,
                sample_count=record.sample_count,
                offset_drift_cov_s_ppm=record.offset_drift_cov_s_ppm,
                sample_start_epoch_s=record.sample_start_epoch_s,
                sample_end_epoch_s=record.sample_end_epoch_s,
                fit_residual_rms_s=record.fit_residual_rms_s,
                design_condition_number=record.design_condition_number,
            )
        records[anchor] = record
    return records


def _identity_calibrations() -> dict[str, ClockCalibration]:
    return {anchor: ClockCalibration(0.0, 0.0, 0.0, 0.0, 0.0, 30.0, 0,
                                     calibration_source="ASSUMED_IDENTITY")
            for anchor in ANCHORS}


def run_case(case: Case, seed: int) -> list[dict[str, Any]]:
    """Run all epochs; GroundTruth is joined only after each solver call."""
    anchor_positions = _geometry(case)
    rng = np.random.default_rng(seed)
    calibrations = _identity_calibrations() if case.fault == "identity_calibration" else _calibrations(
        case, seed, wrong=case.fault == "wrong_calibration")
    if case.fault == "missing_calibration":
        calibrations.pop("D")
    elif case.fault == "stale_calibration":
        calibrations = {anchor: ClockCalibration(
            offset_s=record.offset_s, drift_ppm=record.drift_ppm,
            reference_epoch_s=record.reference_epoch_s, offset_std_s=record.offset_std_s,
            drift_std_ppm=record.drift_std_ppm, calibration_epoch_s=-500.0,
            sample_count=record.sample_count, offset_drift_cov_s_ppm=record.offset_drift_cov_s_ppm,
            sample_start_epoch_s=record.sample_start_epoch_s, sample_end_epoch_s=record.sample_end_epoch_s,
            fit_residual_rms_s=record.fit_residual_rms_s,
            design_condition_number=record.design_condition_number,
            calibration_source=record.calibration_source,
        ) for anchor, record in calibrations.items()}
    prior_by_anchor: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    for epoch in range(EPOCHS):
        t = epoch * DT_S
        truth = trajectory(case.trajectory, t)
        truth_eval = truth  # Offline-only value; never included in estimator arguments.
        runtime_epoch = 100.0 + t
        timestamps: dict[str, float] = {}
        positions: dict[str, tuple[float, float]] = {}
        for anchor, position in anchor_positions.items():
            if ((_active(case, "anchor_off", epoch) and anchor == "D")
                    or (_active(case, "anchor_off_pair", epoch) and anchor in {"C", "D"})):
                continue
            if _active(case, "timestamp_missing", epoch) and anchor == "D":
                continue
            if case.fault == "packet_loss" and rng.random() < case.packet_loss_probability:
                continue
            if _active(case, "packet_loss_burst", epoch) and anchor in {"C", "D"}:
                continue
            factor = (-1.0, -1 / 3, 1 / 3, 1.0)[list(ANCHORS).index(anchor)]
            offset = case.clock_offset_ns * 1e-9 * factor
            drift = case.clock_drift_ppm * factor
            emission = runtime_epoch
            arrival = emission + math.dist(truth, position) / SPEED_OF_LIGHT_M_S
            local = arrival + offset + emission * drift * 1e-6
            if case.jitter_ns:
                local += rng.normal(0.0, case.jitter_ns * 1e-9)
            if case.quantum_ns:
                q = case.quantum_ns * 1e-9
                local = round(local / q) * q
            if _active(case, "timestamp_corrupt", epoch) and anchor == "D":
                local += 10.0
            elif _active(case, "timestamp_stale", epoch) and anchor == "D" and anchor in prior_by_anchor:
                local = prior_by_anchor[anchor]
            elif _active(case, "timestamp_duplicate", epoch) and anchor == "D" and anchor in prior_by_anchor:
                local = prior_by_anchor[anchor]
            prior_by_anchor[anchor] = local
            timestamps[anchor] = local
            positions[anchor] = position

        timestamp_std = {anchor: math.hypot(case.jitter_ns * 1e-9,
                                               case.quantum_ns * 1e-9 / math.sqrt(12.0))
                         for anchor in timestamps}
        usable_calibrations = {anchor: calibrations[anchor] for anchor in timestamps if anchor in calibrations}
        # Runtime contract contains no trajectory label, truth position, or fault schedule.
        estimate = estimate_tdoa_v2(
            positions, timestamps, usable_calibrations,
            timestamp_std_s=timestamp_std, now_s=runtime_epoch,
            max_calibration_age_s=200.0, bounds_m=BOUNDS,
        )
        point = None if estimate.x_m is None else (estimate.x_m, estimate.y_m)
        quality = ("ACCEPTED" if estimate.status == "CONVERGED" and point is not None
                   and BOUNDS[0][0] <= point[0] <= BOUNDS[0][1]
                   and BOUNDS[1][0] <= point[1] <= BOUNDS[1][1]
                   else "REJECTED" if estimate.status in {
                       "INSUFFICIENT_ANCHORS", "CLOCK_UNCALIBRATED", "CLOCK_UNQUALIFIED",
                       "UNOBSERVABLE_GEOMETRY", "AMBIGUOUS", "BOUNDARY_SOLUTION",
                       "ILL_CONDITIONED", "INVALID_INPUT"} or point is not None
                   else "NOT_EVALUATED")
        error = None if point is None else math.dist(point, truth_eval)
        calibration_sha = hashlib.sha256(json.dumps({
            anchor: asdict(record) for anchor, record in usable_calibrations.items()
        }, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        inputs_sha = hashlib.sha256(json.dumps({
            "anchors": positions, "timestamps_s": timestamps,
            "timestamp_std_s": timestamp_std,
            "calibration_status": estimate.calibration_trust,
        }, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        rows.append({
            "case": case.name, "trajectory": case.trajectory, "seed": seed,
            "epoch": epoch, "timestamp_s": t, "fault": case.fault,
            "fault_active": _fault_active(case, epoch),
            "total_anchors": len(ANCHORS), "eligible_anchor_count": len(timestamps),
            "input_available": len(timestamps) >= 3,
            "status": estimate.status, "numerically_converged": estimate.status == "CONVERGED",
            "quality_status": quality, "accepted": quality == "ACCEPTED",
            "estimated_position_m": None if point is None else list(point),
            "error_m": error, "bad_accepted": bool(quality == "ACCEPTED" and error is not None
                                                       and error > BAD_POSITION_ERROR_M),
            "rejected_good_numerical_point": bool(quality == "REJECTED" and error is not None
                                                    and error <= BAD_POSITION_ERROR_M),
            "calibration_trust": estimate.calibration_trust,
            "calibration_source": estimate.calibration_source,
            "runtime_ms": estimate.runtime_ms,
            "observed_input_sha256": inputs_sha,
            "calibration_records_sha256": calibration_sha,
            "ground_truth_in_estimator_input": False,
            "fault_schedule_in_estimator_input": False,
        })
    return rows


def _quantile(values: list[float], p: float) -> float | None:
    return float(np.percentile(values, p)) if values else None


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    errors = [float(row["error_m"]) for row in rows if row["error_m"] is not None]
    accepted_errors = [float(row["error_m"]) for row in rows
                       if row["accepted"] and row["error_m"] is not None]
    accepted = sum(row["accepted"] for row in rows)
    converged = sum(row["numerically_converged"] for row in rows)
    eligible = sum(row["input_available"] for row in rows)
    bad = sum(row["bad_accepted"] for row in rows)
    accepted_points = [row["estimated_position_m"] for row in rows if row["accepted"]]
    step_distances = [math.dist(a, b) for a, b in zip(accepted_points, accepted_points[1:])]
    accepted_epoch_ids = [row["epoch"] for row in rows if row["accepted"]]
    accepted_gaps = [b - a - 1 for a, b in zip(accepted_epoch_ids, accepted_epoch_ids[1:])]
    rejected_good = sum(row["rejected_good_numerical_point"] for row in rows)
    truth_good = sum(row["error_m"] is not None and row["error_m"] <= BAD_POSITION_ERROR_M for row in rows)
    return {
        "epochs": n, "epochs_with_enough_anchors": eligible,
        "numerically_converged": converged, "quality_accepted": accepted,
        "rejected": sum(row["quality_status"] == "REJECTED" for row in rows),
        "not_evaluated": sum(row["quality_status"] == "NOT_EVALUATED" for row in rows),
        "ground_truth_evaluable": n,
        "error_evaluable_estimates": len(errors),
        "input_availability_attempts": eligible / n if n else None,
        "numerical_availability_attempts": converged / n if n else None,
        "accepted_availability_attempts": accepted / n if n else None,
        "accepted_rate_given_input": accepted / eligible if eligible else None,
        "false_confidence_count": bad,
        "false_confidence_denominator_accepted": accepted,
        "false_confidence_rate_accepted": bad / accepted if accepted else None,
        "rejected_good_numerical_point_count": rejected_good,
        "rejected_good_numerical_point_denominator": truth_good,
        "rejected_good_numerical_point_rate": rejected_good / truth_good if truth_good else None,
        "accepted_estimate_step_p95_m": _quantile(step_distances, 95),
        "accepted_estimate_step_max_m": max(step_distances) if step_distances else None,
        "longest_gap_between_accepted_epochs": max(accepted_gaps) if accepted_gaps else None,
        "ground_truth_evaluable_coverage": n / n if n else None,
        "error_evaluable_estimate_coverage": len(errors) / n if n else None,
        "rmse_m_all_numerical": math.sqrt(statistics.mean(e * e for e in errors)) if errors else None,
        "mae_m": statistics.mean(errors) if errors else None,
        "median_error_m": statistics.median(errors) if errors else None,
        "p90_error_m": _quantile(errors, 90), "p95_error_m": _quantile(errors, 95),
        "max_error_m": max(errors) if errors else None,
        "accepted_rmse_m": math.sqrt(statistics.mean(e * e for e in accepted_errors)) if accepted_errors else None,
        "calibration_trust_counts": {key: sum(r["calibration_trust"] == key for r in rows)
                                     for key in sorted({r["calibration_trust"] for r in rows})},
    }


def recovery(rows: list[dict[str, Any]], case: Case) -> dict[str, Any] | None:
    if case.fault_start is None or case.fault_end is None:
        return None
    window = [r for r in rows if case.fault_start <= r["epoch"] < case.fault_end]
    after = [r for r in rows if r["epoch"] >= case.fault_end]
    first_numerical = next((r for r in after if r["numerically_converged"]), None)
    first_accepted = next((r for r in after if r["accepted"]), None)
    first_loss = next((r for r in window if not r["accepted"]), None)
    sustained_start = next((
        after[i]["epoch"] for i in range(max(len(after) - 2, 0))
        if all(after[j]["accepted"] for j in (i, i + 1, i + 2))
    ), None)
    service_lost = first_loss is not None
    return {
        "seed": rows[0]["seed"] if rows else None,
        "fault": case.fault, "fault_start_epoch": case.fault_start,
        "fault_end_epoch": case.fault_end,
        "estimate_loss_detected_epoch": None if first_loss is None else first_loss["epoch"],
        "loss_detection_latency_s": None if first_loss is None else (first_loss["epoch"] - case.fault_start) * DT_S,
        "service_continued_through_fault": not service_lost,
        "recovery_not_applicable": not service_lost,
        "fault_window_accepted_epochs": sum(r["accepted"] for r in window),
        "first_numerical_epoch_after_fault": None if first_numerical is None else first_numerical["epoch"],
        "first_numerical_recovery_latency_s": None if first_numerical is None else (first_numerical["epoch"] - case.fault_end) * DT_S,
        "first_accepted_epoch_after_fault": None if first_accepted is None else first_accepted["epoch"],
        "first_accepted_latency_after_fault_s": None if first_accepted is None else (first_accepted["epoch"] - case.fault_end) * DT_S,
        "first_sustained_accepted_epoch_after_fault": sustained_start,
        "recovery_latency_s": None if not service_lost or sustained_start is None
        else (sustained_start - case.fault_end) * DT_S,
        "false_accepted_during_fault": sum(r["bad_accepted"] for r in window),
    }


def run(seeds: int = 3, start_seed: int = 100) -> dict[str, Any]:
    all_rows = []
    summaries = []
    recoveries = []
    for case in CASES:
        case_rows = []
        for seed in range(start_seed, start_seed + seeds):
            case_rows.extend(run_case(case, seed))
        all_rows.extend(case_rows)
        summaries.append({"case": case.name, "trajectory": case.trajectory,
                          "fault": case.fault, **aggregate(case_rows)})
        recovery_rows = [recovery(run_case(case, seed), case)
                         for seed in range(start_seed, start_seed + seeds)]
        recovery_rows = [row for row in recovery_rows if row is not None]
        if recovery_rows:
            recoveries.append({"case": case.name, "seeds": recovery_rows})
    source = ROOT / "src/riose/products/livestock_tracking/localization/tdoa_v2.py"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    script_source = Path(__file__)
    return {
        "schema_version": "riose.dynamic-localization-faults/v1",
        "classification": "SIMULATED", "riose_sha": git_sha,
        "riose_worktree_dirty": bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
        "localization_v2_source_sha256": source_hash,
        "campaign_source_sha256": hashlib.sha256(script_source.read_bytes()).hexdigest(),
        "frequencia_sha": None,
        "frequencia_execution": "NOT_USED_ANALYTIC_LOCALIZATION_HARNESS",
        "seed_start": start_seed, "seeds_per_case": seeds,
        "attempt_count": len(all_rows), "case_count": len(CASES),
        "trajectory_epochs_per_seed": EPOCHS, "requested_parameters": {
            "cases": [asdict(case) for case in CASES], "epoch_interval_s": DT_S,
            "bad_position_evaluation_threshold_m": BAD_POSITION_ERROR_M,
        },
        "effective_parameters": {
            "estimator": "RIOSE Localization V2 estimate_tdoa_v2",
            "calibration": "seven deterministic synthetic beacon pairs spanning 30 s; fitted records remain UNVERIFIED",
            "radio_model": "2D geometric LOS; affine clock offset/drift; seeded Gaussian jitter; quantization; explicit observation removal",
            "ground_truth_boundary": "not supplied to estimator; used only by post-estimation scorer",
            "quality_gate": "V2 numerical convergence and declared 0-1000 m bounds; no GroundTruth comparison",
            "not_modeled": ["NLOS", "hardware clock accuracy", "RSSI/PHY decoding", "duplicate records at transport layer", "unknown anchor identity contract"],
        },
        "summaries": summaries, "recovery_matrix": recoveries,
        "raw_rows": all_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--start-seed", type=int, default=100)
    parser.add_argument("--output", type=Path, default=Path("docs/research/dynamic-localization/results.json"))
    args = parser.parse_args()
    if args.seeds < 1:
        parser.error("--seeds must be positive")
    result = run(args.seeds, args.start_seed)
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    output.write_text(data, encoding="utf-8")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    summaries = result["summaries"]
    report = [
        "# Dynamic Localization & Fault Injection", "", "All outputs are **SIMULATED**.", "",
        f"- RIOSE source revision: `{result['riose_sha']}`",
        f"- Localization V2 source SHA-256: `{result['localization_v2_source_sha256']}`",
        f"- Cases / seeds / epoch attempts: {result['case_count']} / {args.seeds} / {result['attempt_count']}",
        f"- Full trace: `{output}` (SHA-256 `{digest}`)",
        f"- False-position threshold: >{BAD_POSITION_ERROR_M:g} m (predeclared engineering evaluation threshold)",
        "- Quality gate: Localization V2 numerical status plus declared 0–1000 m operating bounds; GroundTruth is joined after estimation.",
        "- Radio model: analytic 2D LOS geometry with affine clock offsets/drift, seeded jitter, quantization and explicit observation loss.",
        "- Timing resolution is a simulation input; it is not evidence of hardware clock accuracy.", "",
        "## Per-case metrics", "",
        "| Case | N | Input avail. | Numerical avail. | Accepted avail. | RMSE m | P95 m | False confidence / accepted | Recovery |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    recovery_by_case = {item["case"]: item["seeds"] for item in result["recovery_matrix"]}
    for row in summaries:
        recovery_state = "—"
        recs = recovery_by_case.get(row["case"], [])
        if recs:
            continued = sum(r["service_continued_through_fault"] for r in recs)
            latencies = [r["recovery_latency_s"] for r in recs if r["recovery_latency_s"] is not None]
            if continued == len(recs):
                recovery_state = f"service continued ({continued}/{len(recs)})"
            else:
                recovery_state = (f"{len(latencies)}/{len(recs)} sustained recovery; max {max(latencies):g} s"
                                  if latencies else f"loss observed; sustained recovery 0/{len(recs)}")
        fc = f"{row['false_confidence_count']}/{row['false_confidence_denominator_accepted']}"
        report.append("| " + " | ".join(str(value) for value in (
            row["case"], row["epochs"], row["input_availability_attempts"],
            row["numerical_availability_attempts"], row["accepted_availability_attempts"],
            row["rmse_m_all_numerical"], row["p95_error_m"], fc, recovery_state)) + " |")
    report += ["", "## Interpretation and limits", "",
               "Availability denominators include every requested epoch. Every trajectory epoch is GroundTruth-evaluable, but spatial error metrics are conditional on an estimate and report their own denominator. False confidence is bad accepted estimates / accepted estimates. `rejected_good_numerical_point` is limited to returned numerical points rejected by the bounds gate whose offline error is within 10 m; it is not a general false-rejection rate for missing estimates.",
               "",
               "The fitted beacon calibration uses synthetic reference times and path-delay-free LOS assumptions. Every fitted calibration remains `UNVERIFIED`; identity is an explicit zero-correction comparator. Convergence and the bounds gate do not establish accuracy.",
               "",
               "NLOS, physical clock behavior, RSSI/PHY decoding, transport-layer duplicate identity, and unknown-anchor contract behavior are not modeled by this analytic campaign. FREQUENCIA/Sionna/ns-3 results are not substituted for missing inputs. No physical, field, animal-behavior, or hardware claim is made.", ""]
    output.with_name("results.md").write_text("\n".join(report), encoding="utf-8")
    recovery_doc = ["# Recovery Matrix", "", "All values are **SIMULATED**. Latencies use the 1 s synthetic epoch interval. Estimate-loss detection means the first epoch without a quality-accepted estimate; an explicit fault announcement is not modeled. Recovery requires three consecutive accepted epochs after an observed service loss. If acceptance continues through the fault window, recovery latency is not applicable.", "",
        "| Case | Fault | Seed | Start | End | Estimate loss detected | Detection s | First numerical | First accepted | Sustained accepted | Recovery s | Service continued | Bad accepted during fault |",
                    "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for item in result["recovery_matrix"]:
        for row in item["seeds"]:
            recovery_doc.append("| " + " | ".join(str(value) for value in (
                item["case"], row["fault"], row["seed"], row["fault_start_epoch"], row["fault_end_epoch"],
                row["estimate_loss_detected_epoch"], row["loss_detection_latency_s"],
                row["first_numerical_epoch_after_fault"], row["first_accepted_epoch_after_fault"],
                row["first_sustained_accepted_epoch_after_fault"], row["recovery_latency_s"],
                row["service_continued_through_fault"], row["false_accepted_during_fault"])) + " |")
    output.with_name("recovery-matrix.md").write_text("\n".join(recovery_doc) + "\n", encoding="utf-8")
    print(f"classification=SIMULATED cases={result['case_count']} seeds={args.seeds} attempts={result['attempt_count']}")
    print(f"output={output} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
