"""Clock-qualified robust TDoA localization, isolated from the V1 baseline.

Inference accepts only receiver-side timestamps and an explicit calibration
record. Ground truth and simulator clock components have no representation in
this module's API.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping, Sequence

import numpy as np
from scipy.optimize import least_squares

SPEED_OF_LIGHT_M_S = 299_792_458.0


@dataclass(frozen=True, slots=True)
class ClockCalibration:
    """Affine local-clock to reference-clock calibration fitted from beacon pairs."""

    offset_s: float
    drift_ppm: float
    reference_epoch_s: float
    offset_std_s: float
    drift_std_ppm: float
    calibration_epoch_s: float
    sample_count: int
    offset_drift_cov_s_ppm: float = 0.0
    sample_start_epoch_s: float | None = None
    sample_end_epoch_s: float | None = None
    fit_residual_rms_s: float | None = None
    design_condition_number: float | None = None
    calibration_source: str = "BEACON_FIT"

    def correct(self, local_timestamp_s: float) -> float:
        rate = 1.0 + self.drift_ppm * 1e-6
        return self.reference_epoch_s + (
            local_timestamp_s - self.reference_epoch_s - self.offset_s
        ) / rate

    def uncertainty_s(self, local_timestamp_s: float) -> float:
        rate = 1.0 + self.drift_ppm * 1e-6
        elapsed = local_timestamp_s - self.reference_epoch_s - self.offset_s
        grad_offset = -1.0 / rate
        grad_drift_ppm = -elapsed * 1e-6 / (rate * rate)
        variance = (
            grad_offset**2 * self.offset_std_s**2
            + grad_drift_ppm**2 * self.drift_std_ppm**2
            + 2.0 * grad_offset * grad_drift_ppm * self.offset_drift_cov_s_ppm
        )
        return float(np.sqrt(max(variance, 0.0)))


@dataclass(frozen=True, slots=True)
class TdoaEstimate:
    status: str
    x_m: float | None
    y_m: float | None
    residual_rms_m: float | None
    condition_number: float | None
    rank: int
    anchors_used: tuple[str, ...]
    runtime_ms: float
    message: str = ""
    # A good numerical fit cannot establish that reference time and path-delay
    # inputs were truthful. Keep that provenance uncertainty explicit.
    calibration_trust: str = "UNKNOWN"
    calibration_fit_diagnostics: str = "UNAVAILABLE"
    calibration_age_s: float | None = None
    calibration_sample_count_min: int | None = None
    calibration_span_s_min: float | None = None
    calibration_residual_rms_s_max: float | None = None
    calibration_prediction_uncertainty_s_max: float | None = None
    calibration_extrapolation_s_max: float | None = None
    calibration_source: str = "UNKNOWN"


def fit_clock_calibration(
    reference_times_s: Sequence[float],
    local_times_s: Sequence[float],
    *,
    calibration_epoch_s: float | None = None,
) -> ClockCalibration:
    """Fit local = reference + offset + drift*(reference-reference[0]).

    Input pairs represent an explicit time-transfer/calibration event with
    known reference times and compensated path delay. At least three distinct
    epochs are required to retain residual degrees of freedom.
    """
    ref = np.asarray(reference_times_s, dtype=float)
    local = np.asarray(local_times_s, dtype=float)
    if ref.ndim != 1 or local.ndim != 1 or ref.size != local.size or ref.size < 3:
        raise ValueError("at least three paired calibration samples are required")
    if not np.all(np.isfinite(ref)) or not np.all(np.isfinite(local)):
        raise ValueError("calibration samples must be finite")
    epoch = float(ref[0])
    elapsed = ref - epoch
    if np.ptp(ref) <= 0:
        raise ValueError("calibration samples must span distinct epochs")
    design = np.column_stack((np.ones(ref.size), elapsed))
    beta, _, rank, _ = np.linalg.lstsq(design, local - ref, rcond=None)
    if rank != 2:
        raise ValueError("calibration epochs do not identify offset and drift")
    errors = (local - ref) - design @ beta
    dof = ref.size - 2
    variance = float(errors @ errors / dof)
    covariance = variance * np.linalg.inv(design.T @ design)
    latest_sample_epoch = float(np.max(ref))
    earliest_sample_epoch = float(np.min(ref))
    freshness_epoch = latest_sample_epoch if calibration_epoch_s is None else float(calibration_epoch_s)
    if (not isfinite(freshness_epoch) or freshness_epoch < float(np.min(ref))
            or freshness_epoch > latest_sample_epoch):
        raise ValueError("calibration epoch must fall within accepted calibration sample epochs")
    return ClockCalibration(
        offset_s=float(beta[0]), drift_ppm=float(beta[1] * 1e6),
        reference_epoch_s=epoch,
        offset_std_s=float(np.sqrt(max(covariance[0, 0], 0.0))),
        drift_std_ppm=float(np.sqrt(max(covariance[1, 1], 0.0)) * 1e6),
        calibration_epoch_s=freshness_epoch,
        sample_count=int(ref.size),
        offset_drift_cov_s_ppm=float(covariance[0, 1] * 1e6),
        sample_start_epoch_s=earliest_sample_epoch,
        sample_end_epoch_s=latest_sample_epoch,
        fit_residual_rms_s=float(np.sqrt(np.mean(errors**2))),
        design_condition_number=float(np.linalg.cond(design)),
    )


def estimate_tdoa_v2(
    anchor_positions_m: Mapping[str, Sequence[float]],
    local_timestamps_s: Mapping[str, float],
    calibrations: Mapping[str, ClockCalibration],
    *,
    timestamp_std_s: Mapping[str, float] | None = None,
    now_s: float | None = None,
    max_calibration_age_s: float = 3600.0,
    bounds_m: tuple[tuple[float, float], tuple[float, float]] | None = None,
    robust_scale_m: float = 3.0,
) -> TdoaEstimate:
    """Estimate planar position from calibrated arrival times only.

    Uses robust range-equivalent arrival residuals with a nuisance emission
    range, avoiding a noisy shared reference row. Deterministic starts are
    used; positions on the declared bounds are reported as unqualified.
    """
    from time import perf_counter

    started = perf_counter()
    calibration_trust = "UNKNOWN"
    calibration_fit_diagnostics = "UNAVAILABLE"
    calibration_age_s = None
    calibration_sample_count_min = None
    calibration_span_s_min = None
    calibration_residual_rms_s_max = None
    calibration_prediction_uncertainty_s_max = None
    calibration_extrapolation_s_max = None
    calibration_source = "UNKNOWN"

    def calibration_assessment_fields() -> dict[str, object]:
        return {
            "calibration_trust": calibration_trust,
            "calibration_fit_diagnostics": calibration_fit_diagnostics,
            "calibration_age_s": calibration_age_s,
            "calibration_sample_count_min": calibration_sample_count_min,
            "calibration_span_s_min": calibration_span_s_min,
            "calibration_residual_rms_s_max": calibration_residual_rms_s_max,
            "calibration_prediction_uncertainty_s_max": calibration_prediction_uncertainty_s_max,
            "calibration_extrapolation_s_max": calibration_extrapolation_s_max,
            "calibration_source": calibration_source,
        }

    def failed(status: str, message: str, ids: tuple[str, ...] = ()) -> TdoaEstimate:
        return TdoaEstimate(status, None, None, None, None, 0, ids,
                            (perf_counter() - started) * 1000.0, message,
                            **calibration_assessment_fields())

    try:
        controls_valid = (isfinite(float(max_calibration_age_s)) and max_calibration_age_s >= 0
                          and isfinite(float(robust_scale_m)) and robust_scale_m > 0
                          and (now_s is None or isfinite(float(now_s))))
    except (TypeError, ValueError, OverflowError):
        controls_valid = False
    if not controls_valid:
        return failed("INVALID_INPUT", "age, robust scale, and current time must be finite and valid")
    ids = tuple(sorted(set(anchor_positions_m) & set(local_timestamps_s)))
    if len(ids) < 3:
        return failed("INSUFFICIENT_ANCHORS", "at least three timestamped anchors are required", ids)
    if any(anchor_id not in calibrations for anchor_id in ids):
        calibration_trust = "UNAVAILABLE"
        calibration_source = "UNAVAILABLE"
        return failed("CLOCK_UNCALIBRATED", "every used anchor requires clock calibration", ids)
    if now_s is not None and any(
        now_s - calibrations[i].calibration_epoch_s > max_calibration_age_s
        or now_s < calibrations[i].calibration_epoch_s
        for i in ids
    ):
        calibration_trust = "REJECTED_STALE"
        calibration_source = "STALE"
        return failed("CLOCK_UNQUALIFIED", "clock calibration is stale or from the future", ids)
    try:
        anchors = np.asarray([anchor_positions_m[i] for i in ids], dtype=float)
        local = np.asarray([local_timestamps_s[i] for i in ids], dtype=float)
        provided_std = np.asarray([(timestamp_std_s or {}).get(i, 0.0) for i in ids], dtype=float)
        if np.any(~np.isfinite(provided_std)) or np.any(provided_std < 0):
            return failed("INVALID_INPUT", "timestamp uncertainty must be finite and nonnegative", ids)
        if anchors.shape != (len(ids), 2) or not np.all(np.isfinite(anchors)) or not np.all(np.isfinite(local)):
            return failed("INVALID_INPUT", "positions and timestamps must be finite 2D data", ids)
        corrected = np.asarray([calibrations[i].correct(t) for i, t in zip(ids, local, strict=True)])
        std_s = np.asarray([
            np.hypot(float(provided_std[k]), calibrations[i].uncertainty_s(local[k]))
            for k, i in enumerate(ids)
        ])
    except (TypeError, ValueError, KeyError, OverflowError, ZeroDivisionError):
        return failed("INVALID_INPUT", "invalid anchor, timestamp, or calibration values", ids)
    calibration_values = [
        value for calibration in (calibrations[i] for i in ids)
        for value in (calibration.offset_s, calibration.drift_ppm,
                      calibration.reference_epoch_s, calibration.offset_std_s,
                      calibration.drift_std_ppm, calibration.calibration_epoch_s,
                      calibration.offset_drift_cov_s_ppm)
    ]
    calibration_sources = {calibrations[i].calibration_source for i in ids}
    calibration_source = next(iter(calibration_sources)) if len(calibration_sources) == 1 else "MIXED"
    if (not np.all(np.isfinite(calibration_values))
            or any(calibrations[i].sample_count < (0 if calibrations[i].calibration_source == "ASSUMED_IDENTITY" else 3) for i in ids)
            or any(calibrations[i].calibration_source not in {"BEACON_FIT", "ASSUMED_IDENTITY"} for i in ids)
            or any(calibrations[i].calibration_source == "ASSUMED_IDENTITY" and (
                calibrations[i].sample_count != 0 or calibrations[i].offset_s != 0
                or calibrations[i].drift_ppm != 0 or calibrations[i].offset_std_s != 0
                or calibrations[i].drift_std_ppm != 0
                or calibrations[i].offset_drift_cov_s_ppm != 0
            ) for i in ids)
            or any(calibrations[i].calibration_source == "ASSUMED_IDENTITY" and calibration_sources != {"ASSUMED_IDENTITY"} for i in ids)
            or any(1.0 + calibrations[i].drift_ppm * 1e-6 <= 0 for i in ids)):
        calibration_trust = "INVALID"
        return failed("CLOCK_UNQUALIFIED", "clock calibration parameters are invalid or under-sampled", ids)
    if not np.all(np.isfinite(corrected)) or not np.all(np.isfinite(std_s)) or np.any(std_s < 0):
        return failed("INVALID_INPUT", "corrected times and uncertainties must be finite", ids)

    # Observable fit statistics describe the supplied beacon data only. They
    # cannot certify the reference clock or path-delay model, so valid fits
    # remain UNVERIFIED unless an independent trust authority is added.
    calibration_trust = "UNVERIFIED"
    sample_counts = [calibrations[i].sample_count for i in ids]
    spans = [
        calibrations[i].sample_end_epoch_s - calibrations[i].sample_start_epoch_s
        for i in ids
        if calibrations[i].sample_start_epoch_s is not None
        and calibrations[i].sample_end_epoch_s is not None
    ]
    residuals = [calibrations[i].fit_residual_rms_s for i in ids]
    condition_numbers = [calibrations[i].design_condition_number for i in ids]
    diagnostics_complete = (
        len(spans) == len(ids)
        and all(isfinite(value) and value >= 0 for value in spans)
        and all(value is not None and isfinite(value) and value >= 0 for value in residuals)
        and all(value is not None and isfinite(value) and value >= 1 for value in condition_numbers)
    )
    calibration_fit_diagnostics = (
        "ASSUMED_IDENTITY" if calibration_source == "ASSUMED_IDENTITY"
        else "AVAILABLE" if diagnostics_complete else "INCOMPLETE"
    )
    calibration_sample_count_min = min(sample_counts)
    calibration_span_s_min = min(spans) if len(spans) == len(ids) else None
    calibration_residual_rms_s_max = (
        max(float(value) for value in residuals) if diagnostics_complete else None
    )
    prediction_uncertainties = [
        calibrations[i].uncertainty_s(local[k]) for k, i in enumerate(ids)
    ]
    calibration_prediction_uncertainty_s_max = max(prediction_uncertainties)
    if now_s is not None:
        calibration_age_s = max(now_s - calibrations[i].calibration_epoch_s for i in ids)
    extrapolations = []
    for k, i in enumerate(ids):
        calibration = calibrations[i]
        if calibration.sample_start_epoch_s is None or calibration.sample_end_epoch_s is None:
            continue
        reference_time = corrected[k]
        extrapolations.append(max(
            calibration.sample_start_epoch_s - reference_time,
            reference_time - calibration.sample_end_epoch_s,
            0.0,
        ))
    calibration_extrapolation_s_max = max(extrapolations) if len(extrapolations) == len(ids) else None
    if np.linalg.matrix_rank(anchors - anchors.mean(axis=0)) < 2:
        return failed("UNOBSERVABLE_GEOMETRY", "anchor coordinates are collinear", ids)

    # Center arrival times to avoid losing sub-microsecond differences to the
    # large absolute simulation epoch. Convert all residuals to range metres.
    relative_range = SPEED_OF_LIGHT_M_S * (corrected - float(np.min(corrected)))
    sigma_m = np.maximum(SPEED_OF_LIGHT_M_S * std_s, 0.03)
    weights = 1.0 / sigma_m
    scale = max(float(robust_scale_m), 1e-6)
    if bounds_m is None:
        lo = np.array([-np.inf, -np.inf, -np.inf])
        hi = np.array([np.inf, np.inf, np.inf])
    else:
        lo = np.array([bounds_m[0][0], bounds_m[1][0], -np.inf], dtype=float)
        hi = np.array([bounds_m[0][1], bounds_m[1][1], np.inf], dtype=float)
        if not np.all(np.isfinite([lo[0], lo[1], hi[0], hi[1]])) or np.any(lo[:2] >= hi[:2]):
            return failed("INVALID_BOUNDS", "spatial bounds must be finite and increasing", ids)

    def residual(p: np.ndarray) -> np.ndarray:
        return (np.linalg.norm(p[:2] - anchors, axis=1) - relative_range - p[2]) * weights

    def jacobian(p: np.ndarray) -> np.ndarray:
        delta = p[:2] - anchors
        distance = np.linalg.norm(delta, axis=1)
        unit = np.divide(delta, distance[:, None], out=np.zeros_like(delta),
                         where=distance[:, None] > 1e-12)
        return np.column_stack((unit * weights[:, None], -weights))

    starts = [anchors.mean(axis=0)]
    seed_candidates: list[np.ndarray] = []
    if len(ids) == 3:
        starts.extend(anchors)
    else:
        # Seed each robust fit from a deterministic leave-one-anchor-out fit.
        # Four anchors are the minimum for one-outlier redundancy; at most
        # eight anchors are expected on edge, so this remains a small bounded
        # set of fixed-size problems.
        for omitted in range(len(ids)):
            keep = np.arange(len(ids)) != omitted
            subset_anchors = anchors[keep]
            subset_ranges = relative_range[keep]
            subset_weights = weights[keep]

            def subset_residual(p: np.ndarray) -> np.ndarray:
                return (np.linalg.norm(p[:2] - subset_anchors, axis=1)
                        - subset_ranges - p[2]) * subset_weights

            def subset_jacobian(p: np.ndarray) -> np.ndarray:
                delta = p[:2] - subset_anchors
                distance = np.linalg.norm(delta, axis=1)
                unit = np.divide(delta, distance[:, None], out=np.zeros_like(delta),
                                 where=distance[:, None] > 1e-12)
                return np.column_stack((unit * subset_weights[:, None], -subset_weights))

            seed_xy = subset_anchors.mean(axis=0)
            seed_b = float(np.median(np.linalg.norm(seed_xy - subset_anchors, axis=1) - subset_ranges))
            try:
                seed_fit = least_squares(subset_residual, np.array([*seed_xy, seed_b]),
                                         jac=subset_jacobian, bounds=(lo, hi), loss="linear",
                                         max_nfev=100, xtol=1e-9, ftol=1e-9, gtol=1e-9)
                if seed_fit.success and np.all(np.isfinite(seed_fit.x)):
                    starts.append(seed_fit.x)
                    seed_candidates.append(seed_fit.x.copy())
            except (ValueError, FloatingPointError, np.linalg.LinAlgError):
                continue
    if bounds_m is not None:
        starts.append(np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2]))
    solutions = []
    try:
        for start in starts:
            start_xy = start[:2]
            xy = np.maximum(np.minimum(start_xy, hi[:2] - 1e-9), lo[:2] + 1e-9)
            b0 = (float(start[2]) if start.size == 3 else
                  float(np.median(np.linalg.norm(xy - anchors, axis=1) - relative_range)))
            # Residuals are normalized by per-anchor range uncertainty; scale
            # the Huber knee into those normalized units.
            normalized_scale = scale / float(np.median(sigma_m))
            # Three anchors provide no redundant timestamp with which to
            # identify an outlier. Linear loss avoids Huber's per-iteration
            # work in this minimum-observation case. The objectives can differ
            # for inconsistent or bound-constrained data; retain the ambiguity
            # and boundary checks below for those outcomes.
            loss = "linear" if len(ids) == 3 else "huber"
            fit = least_squares(residual, np.array([xy[0], xy[1], b0]), jac=jacobian,
                                bounds=(lo, hi),
                                loss=loss, f_scale=normalized_scale, max_nfev=250,
                                xtol=1e-10, ftol=1e-10, gtol=1e-10)
            if fit.success and np.all(np.isfinite(fit.x)):
                solutions.append(fit)
    except (ValueError, FloatingPointError, np.linalg.LinAlgError):
        return failed("NUMERICAL_FAILURE", "nonlinear fit failed", ids)
    if not solutions:
        return failed("NO_CONVERGENCE", "no deterministic start converged", ids)
    best = min(solutions, key=lambda fit: float(fit.cost))
    chosen = best.x
    used_ids = ids
    if len(ids) == 3:
        best_cost = float(best.cost)
        if any(np.linalg.norm(fit.x[:2] - best.x[:2]) > 1.0
               and abs(float(fit.cost) - best_cost) <= max(1e-8, 1e-6 * max(best_cost, 1.0))
               for fit in solutions):
            return TdoaEstimate("AMBIGUOUS", None, None, None, None, 0, ids,
                                (perf_counter() - started) * 1000.0,
                                "multiple spatial solutions have indistinguishable fit costs",
                                **calibration_assessment_fields())
    if len(ids) >= 4:
        def raw_residual(p: np.ndarray) -> np.ndarray:
            return np.linalg.norm(p[:2] - anchors, axis=1) - relative_range - p[2]

        candidate_params = seed_candidates + [fit.x for fit in solutions]
        threshold_m = np.maximum(scale, 3.0 * sigma_m)
        scored = []
        for params in candidate_params:
            raw = raw_residual(params)
            inliers = np.abs(raw) <= threshold_m
            count = int(np.count_nonzero(inliers))
            cost = float(np.sum((raw[inliers] / sigma_m[inliers]) ** 2)) if count else float("inf")
            scored.append((count, cost, params, inliers))
        max_inliers = max(row[0] for row in scored)
        top = [row for row in scored if row[0] == max_inliers]
        top.sort(key=lambda row: row[1])
        best_consensus = top[0]
        distinct = []
        for row in top:
            if not any(np.linalg.norm(row[2][:2] - existing[2][:2]) <= 1.0
                       for existing in distinct):
                distinct.append(row)
        if len(distinct) > 1:
            return TdoaEstimate("AMBIGUOUS", None, None, None, None, 0, ids,
                                (perf_counter() - started) * 1000.0,
                                "multiple anchor subsets support distinct positions",
                                **calibration_assessment_fields())
        if max_inliers >= 3:
            chosen = best_consensus[2]
            used_ids = tuple(anchor_id for anchor_id, inlier in zip(ids, best_consensus[3], strict=True)
                             if inlier)
    selected_indices = np.asarray([ids.index(anchor_id) for anchor_id in used_ids], dtype=int)
    selected_delta = chosen[:2] - anchors[selected_indices]
    selected_distance = np.linalg.norm(selected_delta, axis=1)
    selected_unit = np.divide(selected_delta, selected_distance[:, None],
                              out=np.zeros_like(selected_delta),
                              where=selected_distance[:, None] > 1e-12)
    selected_jac = np.column_stack((selected_unit * weights[selected_indices, None],
                                    -weights[selected_indices]))
    singular = np.linalg.svd(selected_jac, compute_uv=False)
    rank = int(np.linalg.matrix_rank(selected_jac))
    condition = float(singular[0] / singular[-1]) if singular.size and singular[-1] > 0 else None
    x, y = map(float, chosen[:2])
    if bounds_m is not None and (
        min(x - lo[0], hi[0] - x, y - lo[1], hi[1] - y) <= 1e-6
    ):
        return TdoaEstimate("BOUNDARY_SOLUTION", None, None, None, condition, rank, ids,
                            (perf_counter() - started) * 1000.0,
                            "optimum reached a declared spatial bound",
                            **calibration_assessment_fields())
    raw = np.linalg.norm(chosen[:2] - anchors, axis=1) - relative_range - chosen[2]
    return TdoaEstimate("CONVERGED" if rank == 3 and condition is not None and isfinite(condition) else "ILL_CONDITIONED",
                        x if rank == 3 else None, y if rank == 3 else None,
                        float(np.sqrt(np.mean(raw**2))), condition, rank, used_ids,
                        (perf_counter() - started) * 1000.0,
                        "" if rank == 3 else "arrival geometry does not identify position and emission time",
                        **calibration_assessment_fields())
