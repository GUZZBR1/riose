"""Offline, event-aligned reproductive research summaries.

This module reports descriptive activity around separately typed reproductive
events. It does not train a reproductive classifier or make veterinary claims.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import StrEnum
import json
import math
from statistics import fmean
from typing import Iterable, Mapping

from .domain.contracts import EvidenceStatus


class ReproductiveEventType(StrEnum):
    ESTRUS = "ESTRUS"
    INSEMINATION = "INSEMINATION"
    MATING = "MATING"
    PREGNANCY_CONFIRMED = "PREGNANCY_CONFIRMED"
    PREGNANCY_NEGATIVE = "PREGNANCY_NEGATIVE"
    CALVING = "CALVING"
    PREGNANCY_LOSS = "PREGNANCY_LOSS"
    UNKNOWN = "UNKNOWN"


class EventSource(StrEnum):
    VETERINARY_EXAM = "VETERINARY_EXAM"
    HORMONE_TEST = "HORMONE_TEST"
    INSEMINATION_RECORD = "INSEMINATION_RECORD"
    OBSERVED_CALVING = "OBSERVED_CALVING"
    USER_ENTRY = "USER_ENTRY"
    SIMULATED = "SIMULATED"
    MODEL_OUTPUT = "MODEL_OUTPUT"
    BEHAVIOR_SIGNAL = "BEHAVIOR_SIGNAL"
    UNKNOWN = "UNKNOWN"


_GROUND_TRUTH_SOURCES = {
    EventSource.VETERINARY_EXAM,
    EventSource.HORMONE_TEST,
    EventSource.INSEMINATION_RECORD,
    EventSource.OBSERVED_CALVING,
}

_NON_GROUND_TRUTH_SOURCES = {
    EventSource.SIMULATED,
    EventSource.MODEL_OUTPUT,
    EventSource.BEHAVIOR_SIGNAL,
    EventSource.UNKNOWN,
}


def _aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ActivityObservation:
    animal_id: str
    observed_at: datetime
    activity: float
    sensor: str
    sensor_position: str
    evidence_status: EvidenceStatus
    source_ref: str

    def __post_init__(self) -> None:
        _aware(self.observed_at, "observed_at")
        if not self.animal_id.strip() or not self.sensor.strip() or not self.sensor_position.strip():
            raise ValueError("animal_id, sensor and sensor_position are required")
        if (not isinstance(self.activity, (int, float)) or isinstance(self.activity, bool)
                or not math.isfinite(self.activity)):
            raise ValueError("activity must be a finite number")
        if not isinstance(self.evidence_status, EvidenceStatus):
            raise ValueError("evidence_status must be an EvidenceStatus")
        if not self.source_ref.strip():
            raise ValueError("source_ref is required")


@dataclass(frozen=True, slots=True)
class ReproductiveEvent:
    animal_id: str
    event_type: ReproductiveEventType
    occurred_at: datetime
    recorded_at: datetime
    source: EventSource
    source_ref: str
    evidence_status: EvidenceStatus

    def __post_init__(self) -> None:
        _aware(self.occurred_at, "occurred_at")
        _aware(self.recorded_at, "recorded_at")
        if self.recorded_at < self.occurred_at:
            raise ValueError("recorded_at cannot precede occurred_at")
        if not self.animal_id.strip() or not self.source_ref.strip():
            raise ValueError("animal_id and source_ref are required")
        if not isinstance(self.event_type, ReproductiveEventType):
            raise ValueError("event_type must be a ReproductiveEventType")
        if not isinstance(self.source, EventSource):
            raise ValueError("source must be an EventSource")
        if not isinstance(self.evidence_status, EvidenceStatus):
            raise ValueError("evidence_status must be an EvidenceStatus")
        if self.source in _NON_GROUND_TRUTH_SOURCES and self.evidence_status is EvidenceStatus.VALIDATED:
            raise ValueError("synthetic, model and behavior outputs cannot be validated ground truth")

    @property
    def ground_truth(self) -> bool:
        return self.source in _GROUND_TRUTH_SOURCES and self.evidence_status is not EvidenceStatus.SIMULATED


@dataclass(frozen=True, slots=True)
class EventActivitySummary:
    animal_id: str
    target: ReproductiveEventType
    event_at: str
    event_recorded_at: str
    feature_window_start: str
    feature_window_end: str
    horizon: str
    observation_count: int
    mean_activity: float | None
    baseline_mean_activity: float | None
    activity_change: float | None
    activity_change_ratio: float | None
    sensor: str | None
    sensor_position: str | None
    feature_source_refs: tuple[str, ...]
    evidence_status: EvidenceStatus
    event_source: EventSource
    event_source_ref: str
    ground_truth: bool
    model_version: str
    score: None
    confidence: None
    status: str
    limitation: str


def summarize_event_activity(
    event: ReproductiveEvent,
    observations: Iterable[ActivityObservation],
    *,
    history: timedelta = timedelta(hours=24),
    baseline: timedelta = timedelta(hours=24),
) -> EventActivitySummary:
    """Summarize preceding activity; the event is an outcome anchor, not a feature."""
    if history <= timedelta(0) or baseline <= timedelta(0):
        raise ValueError("history and baseline windows must be positive")
    relevant = [o for o in observations if o.animal_id == event.animal_id]
    # Event labels may be recorded after occurrence for retrospective analysis.
    # Sensor features remain strictly bounded by the event occurrence time.
    relevant = [o for o in relevant if o.observed_at <= event.occurred_at]
    start = event.occurred_at - history
    baseline_start = start - baseline
    current = [o for o in relevant if start <= o.observed_at <= event.occurred_at]
    reference = [o for o in relevant if baseline_start <= o.observed_at < start]
    current_mean = fmean(o.activity for o in current) if current else None
    baseline_mean = fmean(o.activity for o in reference) if reference else None
    ratio = None
    if current_mean is not None and baseline_mean is not None and baseline_mean > 0:
        ratio = current_mean / baseline_mean
    statuses = {o.evidence_status for o in current + reference}
    evidence = EvidenceStatus.SIMULATED if EvidenceStatus.SIMULATED in statuses else (
        EvidenceStatus.EXPERIMENTAL if statuses else event.evidence_status
    )
    sensors = {(o.sensor, o.sensor_position) for o in current + reference}
    if len(sensors) > 1:
        raise ValueError("sensor and sensor position must be consistent within one summary")
    sensor, position = next(iter(sensors)) if len(sensors) == 1 else (None, None)
    sufficient = len(current) >= 2 and len(reference) >= 2
    status = "DESCRIPTIVE_ONLY" if sufficient else "INSUFFICIENT_EVIDENCE"
    return EventActivitySummary(
        animal_id=event.animal_id,
        target=event.event_type,
        event_at=event.occurred_at.isoformat(),
        event_recorded_at=event.recorded_at.isoformat(),
        feature_window_start=start.isoformat(),
        feature_window_end=event.occurred_at.isoformat(),
        horizon="retrospective event-aligned; not a prediction horizon",
        observation_count=len(current),
        mean_activity=current_mean,
        baseline_mean_activity=baseline_mean,
        activity_change=current_mean - baseline_mean if sufficient else None,
        activity_change_ratio=ratio if sufficient else None,
        sensor=sensor,
        sensor_position=position,
        feature_source_refs=tuple(sorted({o.source_ref for o in current + reference})),
        evidence_status=evidence,
        event_source=event.source,
        event_source_ref=event.source_ref,
        ground_truth=event.ground_truth,
        model_version="event-activity-summary/1",
        score=None,
        confidence=None,
        status=status,
        limitation=(
            "Descriptive temporal association only; confounding and selection effects are uncontrolled. "
            "This output is not a diagnosis, prediction, or evidence of causation."
        ),
    )


def validate_animal_splits(splits: Mapping[str, Iterable[str]]) -> None:
    """Reject animal overlap across train/validation/test partitions."""
    owner: dict[str, str] = {}
    for split, animals in splits.items():
        for animal in animals:
            if not animal.strip():
                raise ValueError("split animal ids must be non-empty")
            previous = owner.setdefault(animal, split)
            if previous != split:
                raise ValueError(f"animal {animal!r} appears in both {previous!r} and {split!r}")


def summary_json(summary: EventActivitySummary) -> str:
    document = asdict(summary)
    document["target"] = summary.target.value
    document["evidence_status"] = summary.evidence_status.value
    document["event_source"] = summary.event_source.value
    return json.dumps(document, sort_keys=True, allow_nan=False, indent=2)
