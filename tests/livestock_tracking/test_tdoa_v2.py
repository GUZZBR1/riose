from inspect import signature

import numpy as np
import pytest

from riose.products.livestock_tracking.localization.tdoa_v2 import (
    SPEED_OF_LIGHT_M_S,
    ClockCalibration,
    estimate_tdoa_v2,
    fit_clock_calibration,
)


ANCHORS = {"a": (0.0, 0.0), "b": (1000.0, 0.0),
           "c": (1000.0, 1000.0), "d": (0.0, 1000.0)}


def exact_observations(x=320.0, y=410.0, t0=56.0):
    return {key: t0 + np.linalg.norm(np.array(pos) - (x, y)) / SPEED_OF_LIGHT_M_S
            for key, pos in ANCHORS.items()}


def perfect_calibrations(epoch=56.0):
    return {key: ClockCalibration(0, 0, epoch, 0, 0, epoch, 4) for key in ANCHORS}


def test_clock_fit_recovers_affine_offset_and_drift_from_paired_events():
    ref = np.array([0.0, 10.0, 100.0, 1000.0])
    local = ref + 0.002 + (ref - ref[0]) * 12e-6
    cal = fit_clock_calibration(ref, local)
    assert cal.offset_s == pytest.approx(0.002, abs=1e-12)
    assert cal.drift_ppm == pytest.approx(12.0, abs=1e-7)
    assert cal.correct(local[-1]) == pytest.approx(ref[-1], abs=1e-9)
    assert cal.sample_count == 4
    assert cal.sample_start_epoch_s == pytest.approx(0.0)
    assert cal.sample_end_epoch_s == pytest.approx(1000.0)
    assert cal.fit_residual_rms_s == pytest.approx(0.0, abs=1e-12)
    assert cal.design_condition_number >= 1


def test_clock_fit_rejects_forged_calibration_freshness():
    ref = [0.0, 10.0, 100.0, 1000.0]
    local = [value + 0.001 for value in ref]
    with pytest.raises(ValueError, match="calibration epoch"):
        fit_clock_calibration(ref, local, calibration_epoch_s=1200.0)


@pytest.mark.parametrize("ref,local", [([1, 2], [1, 2]), ([1, 1, 1], [1, 1, 1]),
                                        ([1, 2, 3], [1, float("nan"), 3])])
def test_clock_fit_rejects_unobservable_or_invalid_samples(ref, local):
    with pytest.raises(ValueError):
        fit_clock_calibration(ref, local)


def test_calibration_is_required_and_stale_calibration_fails_closed():
    times = exact_observations()
    missing = estimate_tdoa_v2(ANCHORS, times, {})
    assert missing.status == "CLOCK_UNCALIBRATED"
    assert missing.calibration_trust == "UNAVAILABLE"
    stale = {key: ClockCalibration(0, 0, 0, 0, 0, 0, 4) for key in ANCHORS}
    result = estimate_tdoa_v2(ANCHORS, times, stale, now_s=10000, max_calibration_age_s=10)
    assert result.status == "CLOCK_UNQUALIFIED"
    assert result.calibration_trust == "REJECTED_STALE"


def test_exact_tdoa_localizes_without_any_truth_input():
    result = estimate_tdoa_v2(ANCHORS, exact_observations(), perfect_calibrations())
    assert result.status == "CONVERGED"
    assert result.x_m == pytest.approx(320, abs=1e-3)
    assert result.y_m == pytest.approx(410, abs=1e-3)
    assert result.residual_rms_m < 1e-3
    assert result.rank == 3
    assert "ground_truth" not in signature(estimate_tdoa_v2).parameters
    assert "truth" not in signature(estimate_tdoa_v2).parameters
    assert result.calibration_trust == "UNVERIFIED"
    assert result.calibration_fit_diagnostics == "INCOMPLETE"
    assert result.calibration_sample_count_min == 4


def test_low_residual_synthetic_calibration_is_never_mislabeled_trusted():
    ref = np.array([0.0, 10.0, 100.0, 1000.0])
    local = ref + 20e-9 + (ref - ref[0]) * 0.2e-6
    fitted = fit_clock_calibration(ref, local)
    # Perfectly self-consistent pairs still cannot authenticate the reference
    # clock or path delay; runtime must expose that the calibration is unverified.
    calibrations = {key: fitted for key in ANCHORS}
    observations = exact_observations()
    result = estimate_tdoa_v2(ANCHORS, observations, calibrations, now_s=1000.0)
    assert result.calibration_trust == "UNVERIFIED"
    assert result.calibration_fit_diagnostics == "AVAILABLE"
    assert result.calibration_residual_rms_s_max == pytest.approx(0.0, abs=1e-12)
    assert result.calibration_span_s_min == pytest.approx(1000.0)
    assert result.calibration_age_s == pytest.approx(0.0)
    assert result.calibration_prediction_uncertainty_s_max == pytest.approx(0.0, abs=1e-12)


def test_assumed_identity_is_explicitly_not_a_beacon_fit_or_trusted_calibration():
    anchors = dict(list(ANCHORS.items())[:3])
    identity = {
        key: ClockCalibration(0.0, 0.0, 56.0, 0.0, 0.0, 56.0, 0,
                              calibration_source="ASSUMED_IDENTITY")
        for key in anchors
    }
    result = estimate_tdoa_v2(anchors, exact_observations(), identity, now_s=56.0)
    assert result.status == "CONVERGED"
    assert result.calibration_trust == "UNVERIFIED"
    assert result.calibration_source == "ASSUMED_IDENTITY"
    assert result.calibration_sample_count_min == 0
    assert result.calibration_fit_diagnostics == "ASSUMED_IDENTITY"
    assert result.x_m == pytest.approx(320.0, abs=1e-3)


def test_one_bad_arrival_is_flagged_ambiguous_with_four_and_rejected_with_five_anchors():
    times = exact_observations()
    times["d"] += 250.0 / SPEED_OF_LIGHT_M_S
    ambiguous = estimate_tdoa_v2(ANCHORS, times, perfect_calibrations(), robust_scale_m=2)
    assert ambiguous.status == "AMBIGUOUS"
    assert ambiguous.x_m is None and ambiguous.y_m is None

    anchors5 = {**ANCHORS, "e": (500.0, 500.0)}
    times5 = {key: 56.0 + np.linalg.norm(np.asarray(position) - (320, 410)) / SPEED_OF_LIGHT_M_S
              for key, position in anchors5.items()}
    times5["d"] += 250.0 / SPEED_OF_LIGHT_M_S
    calibrations5 = {key: ClockCalibration(0, 0, 56, 0, 0, 56, 4) for key in anchors5}
    result = estimate_tdoa_v2(anchors5, times5, calibrations5, robust_scale_m=2)
    assert result.status == "CONVERGED"
    assert np.hypot(result.x_m - 320, result.y_m - 410) < 3
    assert result.anchors_used == ("a", "b", "c", "e")


def test_under_supported_and_collinear_geometries_are_explicit_failures():
    times = exact_observations()
    assert estimate_tdoa_v2(dict(list(ANCHORS.items())[:2]), times, perfect_calibrations()).status == "INSUFFICIENT_ANCHORS"
    linear = {"a": (0, 0), "b": (10, 0), "c": (20, 0), "d": (30, 0)}
    linear_times = {k: exact_observations()[k] for k in linear}
    assert estimate_tdoa_v2(linear, linear_times, perfect_calibrations()).status == "UNOBSERVABLE_GEOMETRY"


def test_bounds_report_failure_instead_of_returning_clamped_coordinate():
    result = estimate_tdoa_v2(ANCHORS, exact_observations(1200, 410), perfect_calibrations(),
                              bounds_m=((0, 1000), (0, 1000)))
    assert result.status == "BOUNDARY_SOLUTION"
    assert result.x_m is None and result.y_m is None


def test_three_anchor_boundary_solution_is_still_rejected():
    anchors = dict(list(ANCHORS.items())[:3])
    calibrations = {key: perfect_calibrations()[key] for key in anchors}
    arrivals = {key: exact_observations(1200, 410)[key] for key in anchors}
    result = estimate_tdoa_v2(anchors, arrivals, calibrations,
                              bounds_m=((0, 1000), (0, 1000)))
    assert result.status == "BOUNDARY_SOLUTION"
    assert result.x_m is None and result.y_m is None


def test_nonfinite_timestamp_is_rejected():
    times = exact_observations()
    times["a"] = float("nan")
    assert estimate_tdoa_v2(ANCHORS, times, perfect_calibrations()).status == "INVALID_INPUT"
