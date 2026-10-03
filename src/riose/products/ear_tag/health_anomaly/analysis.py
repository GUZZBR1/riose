"""Individual, past-only robust deviation scoring for behavior summaries.

This experimental screen reports behavioral deviations for investigation. It
does not estimate disease probability or determine an animal's health status.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from statistics import median
from typing import Iterable

from riose.products.livestock_tracking.domain.contracts import EvidenceStatus

MIN_BASELINE_SAMPLES = 7
ROBUST_Z_THRESHOLD = 3.5
_FEATURES = (
    ("activity", "ACTIVITY_DEVIATION", 1.0),
    ("rumination_minutes", "RUMINATION_DEVIATION", 5.0),
    ("locomotion_steps", "LOCOMOTION_DEVIATION", 5.0),
)


class DeviationState(StrEnum):
    NO_SIGNIFICANT_BEHAVIORAL_DEVIATION = "NO_SIGNIFICANT_BEHAVIORAL_DEVIATION"
    INVESTIGATE = "INVESTIGATE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class BehaviorObservation:
    """A single summarized observation; missing metrics remain ``None``.

    ``activity`` and ``locomotion_steps`` are non-negative sensor-derived
    summaries in caller-defined units. Rumination is minutes in a 24-hour
    interval. The caller must use the same metric definitions over time.
    """

    animal_id: str
    timestamp_s: float
    sensor_position: str
    activity: float | None = None
    rumination_minutes: float | None = None
    locomotion_steps: float | None = None
    evidence_status: EvidenceStatus = EvidenceStatus.EXPERIMENTAL

    def __post_init__(self) -> None:
        if type(self.animal_id) is not str or not self.animal_id.strip():
            raise ValueError("animal_id must be a non-empty string")
        if not _finite(self.timestamp_s) or self.timestamp_s < 0:
            raise ValueError("timestamp_s must be finite and non-negative")
        if type(self.sensor_position) is not str or not self.sensor_position.strip():
            raise ValueError("sensor_position must be a non-empty string")
        if not isinstance(self.evidence_status, EvidenceStatus):
            raise ValueError("evidence_status must be an EvidenceStatus")
        for name, value in ((name, getattr(self, name)) for name, _, _ in _FEATURES):
            if value is None:
                continue
            if not _finite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative, or None")
            if name == "rumination_minutes" and value > 1440:
                raise ValueError("rumination_minutes cannot exceed 1440")


@dataclass(frozen=True, slots=True)
class FeatureDeviation:
    feature: str
    observed_value: float
    baseline_median: float
    robust_scale: float
    robust_z_score: float


@dataclass(frozen=True, slots=True)
class DeviationResult:
    animal_id: str
    observed_at_s: float
    sensor_position: str
    state: DeviationState
    reason_codes: tuple[str, ...]
    score: float | None
    threshold: float
    baseline_sample_count: int
    baseline_start_s: float | None
    baseline_end_s: float | None
    deviations: tuple[FeatureDeviation, ...]
    evidence_status: EvidenceStatus
    input_evidence_statuses: tuple[EvidenceStatus, ...]
    limitations: tuple[str, ...]


def analyze_behavior(
    observations: Iterable[BehaviorObservation],
    *,
    animal_id: str,
    observed_at_s: float,
    sensor_position: str,
    min_baseline_samples: int = MIN_BASELINE_SAMPLES,
    threshold: float = ROBUST_Z_THRESHOLD,
) -> DeviationResult:
    """Compare one observation with that animal's earlier same-position data.

    Only the requested animal, exact sensor position, and observations at or
    before ``observed_at_s`` are considered. Baseline rows must be strictly
    earlier. Missing metrics are omitted rather than interpreted as zero.
    """

    if type(animal_id) is not str or not animal_id.strip():
        raise ValueError("animal_id must be a non-empty string")
    if type(sensor_position) is not str or not sensor_position.strip():
        raise ValueError("sensor_position must be a non-empty string")
    if not _finite(observed_at_s) or observed_at_s < 0:
        raise ValueError("observed_at_s must be finite and non-negative")
    if type(min_baseline_samples) is not int or min_baseline_samples < 1:
        raise ValueError("min_baseline_samples must be a positive integer")
    if not _finite(threshold) or threshold <= 0:
        raise ValueError("threshold must be finite and positive")

    records = tuple(observations)
    if any(type(item) is not BehaviorObservation for item in records):
        raise ValueError("observations must contain only BehaviorObservation values")
    relevant = tuple(
        item
        for item in records
        if item.animal_id == animal_id
        and item.sensor_position == sensor_position
        and item.timestamp_s <= observed_at_s
    )
    at_time = tuple(item for item in relevant if item.timestamp_s == observed_at_s)
    if len(at_time) > 1:
        raise ValueError("multiple observations exist for the animal, position, and time")
    current = at_time[0] if at_time else None
    prior = tuple(item for item in relevant if item.timestamp_s < observed_at_s)
    if len({item.timestamp_s for item in prior}) != len(prior):
        raise ValueError("baseline timestamps must be unique for the animal and position")
    prior = tuple(sorted(prior, key=lambda item: item.timestamp_s)[-min_baseline_samples:])

    input_rows = (*prior, *((current,) if current is not None else ()))
    statuses = tuple(
        sorted({item.evidence_status for item in input_rows}, key=lambda status: status.value)
    )
    evidence_status = _derived_status(statuses)
    start = prior[0].timestamp_s if prior else None
    end = prior[-1].timestamp_s if prior else None
    limitations = (
        "Behavioral deviation is a low-specificity investigation signal, not a diagnosis.",
        "A normal screen does not rule out disease.",
        "No field validation or clinical performance is claimed.",
    )

    if current is None or not prior:
        return _insufficient(
            animal_id,
            observed_at_s,
            sensor_position,
            threshold,
            len(prior),
            start,
            end,
            evidence_status,
            statuses,
            (*limitations, "Current observation or individual baseline is unavailable."),
        )

    deviations: list[FeatureDeviation] = []
    unavailable = False
    for feature, reason, scale_floor in _FEATURES:
        values = [getattr(row, feature) for row in prior if getattr(row, feature) is not None]
        observed = getattr(current, feature)
        if observed is None:
            unavailable = True
            continue
        if len(values) < min_baseline_samples:
            unavailable = True
            continue
        center = median(values)
        mad = median([abs(value - center) for value in values])
        scale = max(1.4826 * mad, scale_floor)
        z_score = abs(observed - center) / scale
        deviations.append(FeatureDeviation(feature, observed, center, scale, z_score))

    if not deviations:
        return _insufficient(
            animal_id,
            observed_at_s,
            sensor_position,
            threshold,
            len(prior),
            start,
            end,
            evidence_status,
            statuses,
            (*limitations, "Insufficient valid coverage for any behavior metric."),
        )

    score = max(item.robust_z_score for item in deviations)
    flagged_features = {
        item.feature for item in deviations if item.robust_z_score >= threshold
    }
    reasons = tuple(reason for feature, reason, _ in _FEATURES if feature in flagged_features)
    if unavailable:
        limitations = (*limitations, "Some behavior metrics had insufficient coverage and were omitted.")
    return DeviationResult(
        animal_id=animal_id,
        observed_at_s=observed_at_s,
        sensor_position=sensor_position,
        state=(
            DeviationState.INVESTIGATE
            if reasons
            else DeviationState.NO_SIGNIFICANT_BEHAVIORAL_DEVIATION
        ),
        reason_codes=reasons,
        score=score,
        threshold=threshold,
        baseline_sample_count=len(prior),
        baseline_start_s=start,
        baseline_end_s=end,
        deviations=tuple(deviations),
        evidence_status=evidence_status,
        input_evidence_statuses=statuses,
        limitations=limitations,
    )


def _insufficient(
    animal_id: str,
    observed_at_s: float,
    sensor_position: str,
    threshold: float,
    sample_count: int,
    start: float | None,
    end: float | None,
    evidence_status: EvidenceStatus,
    statuses: tuple[EvidenceStatus, ...],
    limitations: tuple[str, ...],
) -> DeviationResult:
    return DeviationResult(
        animal_id=animal_id,
        observed_at_s=observed_at_s,
        sensor_position=sensor_position,
        state=DeviationState.INSUFFICIENT_DATA,
        reason_codes=("INSUFFICIENT_COVERAGE",),
        score=None,
        threshold=threshold,
        baseline_sample_count=sample_count,
        baseline_start_s=start,
        baseline_end_s=end,
        deviations=(),
        evidence_status=evidence_status,
        input_evidence_statuses=statuses,
        limitations=limitations,
    )


def _derived_status(statuses: tuple[EvidenceStatus, ...]) -> EvidenceStatus:
    # Analysis never upgrades evidence to VALIDATED.
    for status in (EvidenceStatus.SIMULATED, EvidenceStatus.FUTURE, EvidenceStatus.ASSUMED):
        if status in statuses:
            return status
    return EvidenceStatus.EXPERIMENTAL


def _finite(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False
