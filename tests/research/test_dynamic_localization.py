from __future__ import annotations

import importlib.util
import inspect
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "dynamic_localization_experiment",
    ROOT / "research/dynamic-localization-faults/experiment.py",
)
assert SPEC and SPEC.loader
experiment = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = experiment
SPEC.loader.exec_module(experiment)


def test_trajectory_catalog_is_deterministic_and_stays_in_bounds():
    for kind in ("STATIC", "STRAIGHT_WALK", "TURN", "STOP_AND_GO", "CURVE", "BOUNDARY_CROSSING"):
        first = [experiment.trajectory(kind, i) for i in range(experiment.EPOCHS)]
        assert first == [experiment.trajectory(kind, i) for i in range(experiment.EPOCHS)]
        assert all(0 <= x <= 1000 and 0 <= y <= 1000 for x, y in first)


def test_ground_truth_and_fault_schedule_are_absent_from_estimator_contract():
    assert "ground_truth" not in inspect.signature(experiment.estimate_tdoa_v2).parameters
    case = next(case for case in experiment.CASES if case.name == "static_control")
    row = experiment.run_case(case, 101)[0]
    assert row["ground_truth_in_estimator_input"] is False
    assert row["fault_schedule_in_estimator_input"] is False
    assert "ground_truth_position_m" not in row
    assert "truth" not in row


def test_anchor_loss_has_defined_inputs_and_recovers_after_window():
    case = next(case for case in experiment.CASES if case.name == "anchor_loss_recovery")
    rows = experiment.run_case(case, 2026)
    assert all(row["eligible_anchor_count"] == 3 for row in rows[8:14])
    assert all(row["eligible_anchor_count"] == 4 for row in rows[14:])
    metrics = experiment.recovery(rows, case)
    assert metrics["fault_window_accepted_epochs"] == 6
    assert metrics["service_continued_through_fault"] is True
    assert metrics["recovery_not_applicable"] is True
    assert metrics["recovery_latency_s"] is None
    assert metrics["first_numerical_epoch_after_fault"] is not None
    assert metrics["first_accepted_epoch_after_fault"] is not None


def test_two_anchor_loss_is_detected_and_requires_sustained_recovery():
    case = next(case for case in experiment.CASES if case.name == "two_anchor_loss_recovery")
    rows = experiment.run_case(case, 2026)
    assert all(row["eligible_anchor_count"] == 2 for row in rows[8:14])
    metrics = experiment.recovery(rows, case)
    assert metrics["estimate_loss_detected_epoch"] == 8
    assert metrics["service_continued_through_fault"] is False
    assert metrics["first_numerical_epoch_after_fault"] == 14
    assert metrics["first_sustained_accepted_epoch_after_fault"] == 14
    assert metrics["recovery_latency_s"] == 0


def test_low_coverage_zone_is_a_predeclared_time_window_on_a_moving_path():
    case = next(case for case in experiment.CASES if case.name == "bad_zone_crossing")
    rows = experiment.run_case(case, 82)
    assert rows[9]["eligible_anchor_count"] == 4
    assert all(row["eligible_anchor_count"] == 2 for row in rows[10:15])
    assert all(row["eligible_anchor_count"] == 4 for row in rows[15:])


def test_missing_and_corrupted_timestamps_are_explicitly_characterized():
    missing = next(case for case in experiment.CASES if case.name == "missing_timestamp")
    corrupted = next(case for case in experiment.CASES if case.name == "corrupted_timestamp")
    missing_rows = experiment.run_case(missing, 4)
    corrupted_rows = experiment.run_case(corrupted, 4)
    assert missing_rows[9]["eligible_anchor_count"] == 3
    assert corrupted_rows[9]["eligible_anchor_count"] == 4
    assert corrupted_rows[9]["observed_input_sha256"] != corrupted_rows[10]["observed_input_sha256"]


def test_missing_and_stale_calibration_fail_closed():
    missing = next(case for case in experiment.CASES if case.name == "clock_drift_missing_calibration")
    stale = next(case for case in experiment.CASES if case.name == "clock_drift_stale_calibration")
    assert {row["status"] for row in experiment.run_case(missing, 78)} == {"CLOCK_UNCALIBRATED"}
    assert {row["status"] for row in experiment.run_case(stale, 78)} == {"CLOCK_UNQUALIFIED"}


def test_clock_drift_corrected_and_wrong_calibration_are_distinguished():
    corrected = next(case for case in experiment.CASES if case.name == "clock_drift_corrected")
    wrong = next(case for case in experiment.CASES if case.name == "clock_drift_wrong_calibration")
    corrected_rows = experiment.run_case(corrected, 100)
    wrong_rows = experiment.run_case(wrong, 100)
    assert all(row["numerically_converged"] for row in corrected_rows)
    assert any(row["bad_accepted"] for row in wrong_rows)


def test_duplicate_timestamp_is_deterministic_and_packet_loss_keeps_attempts():
    duplicate = next(case for case in experiment.CASES if case.name == "duplicate_timestamp")
    first = experiment.run_case(duplicate, 9001)
    second = experiment.run_case(duplicate, 9001)
    assert [row["observed_input_sha256"] for row in first] == [row["observed_input_sha256"] for row in second]
    loss = next(case for case in experiment.CASES if case.name == "packet_loss_25pct")
    rows = experiment.run_case(loss, 9001)
    metrics = experiment.aggregate(rows)
    assert metrics["epochs"] == experiment.EPOCHS
    assert metrics["ground_truth_evaluable_coverage"] == 1.0
    assert metrics["input_availability_attempts"] <= 1.0


def test_false_confidence_and_rejection_metrics_keep_denominators():
    case = next(case for case in experiment.CASES if case.name == "clock_offset_identity")
    rows = experiment.run_case(case, 333)
    metrics = experiment.aggregate(rows)
    assert metrics["false_confidence_denominator_accepted"] == metrics["quality_accepted"]
    assert metrics["ground_truth_evaluable"] <= metrics["epochs"]
    assert math.isclose(metrics["input_availability_attempts"], 1.0)
    assert "rejected_good_numerical_point_denominator" in metrics
