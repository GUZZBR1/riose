"""Causal, individual-only behavioral baseline and deviation scoring (BioSignature V1).

Inputs are complete, fixed-duration behavior profiles (normally one day) rather
than raw sensor events. No population prior or diagnosis is produced.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from statistics import median
from typing import Mapping, Sequence

from .contracts import EvidenceStatus

BIOSIGNATURE_VERSION = "biosignature-v1"
METHOD = "per-feature median and scaled MAD (normal-consistent robust z-score)"


class BioSignatureState(StrEnum):
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    NORMAL = "NORMAL"
    DEVIATION = "DEVIATION"
    STRONG_DEVIATION = "STRONG_DEVIATION"


@dataclass(frozen=True, slots=True)
class BehaviorWindow:
    """One fixed-duration profile for an animal and comparable time stratum.

    Features are behavior proportions in [0, 1], with zero explicitly meaning
    observed absence. None means missing/unmeasured. Coverage/confidence are
    independent quality gates; SIMULATED evidence is preserved end-to-end.
    """

    animal_id: str
    timestamp: float
    stratum: str
    features: Mapping[str, float | None]
    coverage: float
    confidence: float
    model_version: str
    taxonomy_version: str
    evidence_status: EvidenceStatus = EvidenceStatus.SIMULATED

    def __post_init__(self) -> None:
        if not isinstance(self.animal_id, str) or not self.animal_id.strip():
            raise ValueError("animal_id must be a non-empty string")
        if not math.isfinite(self.timestamp):
            raise ValueError("timestamp must be finite")
        if not self.stratum or not self.model_version or not self.taxonomy_version:
            raise ValueError("stratum and model/taxonomy versions are required")
        if not isinstance(self.features, Mapping) or not self.features:
            raise ValueError("features must be a non-empty mapping")
        if not 0 <= self.coverage <= 1 or not math.isfinite(self.coverage):
            raise ValueError("coverage must be finite and in [0, 1]")
        if not 0 <= self.confidence <= 1 or not math.isfinite(self.confidence):
            raise ValueError("confidence must be finite and in [0, 1]")
        if not isinstance(self.evidence_status, EvidenceStatus):
            raise ValueError("evidence_status must be an EvidenceStatus")
        for name, value in self.features.items():
            if not isinstance(name, str) or not name:
                raise ValueError("feature names must be non-empty strings")
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("feature proportions must be finite and in [0, 1]")
        if all(value is not None for value in self.features.values()) and not math.isclose(
            sum(float(value) for value in self.features.values()), 1.0, abs_tol=0.01
        ):
            raise ValueError("complete behavior proportions must sum to 1")
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))


@dataclass(frozen=True, slots=True)
class BioSignatureConfig:
    min_history: int = 7
    min_coverage: float = 0.8
    min_confidence: float = 0.5
    threshold: float = 3.5
    scale_floor: float = 0.02
    max_gap_seconds: float = 259200.0
    persistence_windows: int = 2
    rebase_after: int = 7
    baseline_window: int = 30

    def __post_init__(self) -> None:
        if self.min_history < 3 or self.persistence_windows < 1 or self.rebase_after < self.persistence_windows:
            raise ValueError("history/persistence parameters are inconsistent")
        if self.baseline_window < self.min_history:
            raise ValueError("baseline_window must be at least min_history")
        for name in ("min_coverage", "min_confidence"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if not math.isfinite(self.threshold) or self.threshold <= 0:
            raise ValueError("threshold must be finite and positive")
        if not math.isfinite(self.scale_floor) or self.scale_floor <= 0:
            raise ValueError("scale_floor must be finite and positive")
        if not math.isfinite(self.max_gap_seconds) or self.max_gap_seconds <= 0:
            raise ValueError("max_gap_seconds must be finite and positive")


@dataclass(frozen=True, slots=True)
class FeatureBaseline:
    feature: str
    median: float
    mad: float
    scale: float
    observations: int


@dataclass(frozen=True, slots=True)
class BioSignatureResult:
    animal_id: str
    timestamp: float
    stratum: str
    state: BioSignatureState
    reason_codes: tuple[str, ...]
    feature_scores: Mapping[str, float]
    feature_baselines: Mapping[str, FeatureBaseline]
    threshold: float
    baseline_start: float | None
    baseline_end: float | None
    baseline_observations: int
    method: str
    version: str
    model_version: str
    taxonomy_version: str
    coverage: float
    confidence: float
    evidence_status: EvidenceStatus
    observation_features: Mapping[str, float | None]

    def __post_init__(self) -> None:
        for name in ("feature_scores", "feature_baselines", "observation_features"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    @property
    def score(self) -> float | None:
        """Maximum absolute robust z-score, or None when history is insufficient."""
        return max((abs(value) for value in self.feature_scores.values()), default=None)


def _quality_reason(window: BehaviorWindow, config: BioSignatureConfig) -> str | None:
    if window.coverage < config.min_coverage:
        return "LOW_COVERAGE"
    if window.confidence < config.min_confidence:
        return "LOW_CONFIDENCE"
    if any(value is None for value in window.features.values()):
        return "MISSING_FEATURE"
    return None


def _robust_baselines(history: Sequence[BehaviorWindow], features: Sequence[str],
                      config: BioSignatureConfig) -> dict[str, FeatureBaseline]:
    result = {}
    for feature in features:
        values = [float(item.features[feature]) for item in history]
        center = median(values)
        mad = median([abs(value - center) for value in values])
        result[feature] = FeatureBaseline(feature, center, mad,
                                          max(1.4826 * mad, config.scale_floor), len(values))
    return result


def evaluate(windows: Sequence[BehaviorWindow],
             config: BioSignatureConfig = BioSignatureConfig()) -> tuple[BioSignatureResult, ...]:
    """Evaluate chronological windows without future leakage.

    The baseline uses only earlier quality-valid, non-deviation windows for the
    same animal/stratum/model/taxonomy. Deviations are held out. Once a shift
    persists for rebase_after windows, those windows form a new baseline;
    this bounds stale-baseline alerts while preserving each transition result.
    """
    if not windows:
        return ()
    history: list[BehaviorWindow] = []
    results: list[BioSignatureResult] = []
    previous_key: tuple[str, str] | None = None
    model_key: tuple[str, str] | None = None
    last_timestamp: float | None = None
    deviation_streak = 0
    shift_windows: list[BehaviorWindow] = []
    expected_features = tuple(sorted(windows[0].features))
    for window in windows:
        key = (window.animal_id, window.stratum)
        if previous_key is None:
            previous_key = key
        elif key != previous_key:
            raise ValueError("one evaluation sequence must use one animal, stratum, model and taxonomy")
        long_gap = False
        if last_timestamp is not None:
            if window.timestamp == last_timestamp:
                raise ValueError("duplicate timestamp")
            if window.timestamp < last_timestamp:
                raise ValueError("windows must be in strictly increasing timestamp order")
            long_gap = window.timestamp - last_timestamp > config.max_gap_seconds
        last_timestamp = window.timestamp
        version_key = (window.model_version, window.taxonomy_version)
        version_changed = model_key is not None and version_key != model_key
        if version_changed:
            history.clear()
            deviation_streak, shift_windows = 0, []
            expected_features = tuple(sorted(window.features))
        if long_gap:
            history.clear()
            deviation_streak, shift_windows = 0, []
        model_key = version_key
        if tuple(sorted(window.features)) != expected_features:
            reason = "FEATURE_SCHEMA_MISMATCH"
        else:
            reason = _quality_reason(window, config)
        if reason or version_changed or long_gap:
            reason_codes = ((reason,) if reason else
                            (("MODEL_VERSION_MISMATCH",) if version_changed else ("GAP_TOO_LONG",)))
            results.append(_result(window, BioSignatureState.INSUFFICIENT_HISTORY,
                                   reason_codes, {}, {}, config, history, history))
            # Invalid/missing windows break a run of consecutive deviations.
            deviation_streak, shift_windows = 0, []
            if not reason:
                history.append(window)
            continue
        if len(history) < config.min_history:
            results.append(_result(window, BioSignatureState.INSUFFICIENT_HISTORY,
                                   ("WARMING_UP",), {}, {}, config, history, history))
            history.append(window)
            continue
        baseline_history = history[-config.baseline_window:]
        baselines = _robust_baselines(baseline_history, expected_features, config)
        scores = {feature: (float(window.features[feature]) - base.median) / base.scale
                  for feature, base in baselines.items()}
        deviating = {feature: score for feature, score in scores.items()
                     if abs(score) >= config.threshold}
        if deviating:
            deviation_streak += 1
            shift_windows.append(window)
            if deviation_streak >= config.rebase_after:
                state = BioSignatureState.STRONG_DEVIATION
                codes = ("PERSISTENT_DEVIATION", "BASELINE_REBASED_AFTER_PERSISTENT_SHIFT")
                history = shift_windows[-config.baseline_window:]
                deviation_streak, shift_windows = 0, []
            elif deviation_streak >= config.persistence_windows:
                state, codes = BioSignatureState.STRONG_DEVIATION, ("PERSISTENT_DEVIATION",)
            else:
                state, codes = BioSignatureState.DEVIATION, ("FEATURES_OUTSIDE_INDIVIDUAL_BASELINE",)
        else:
            state, codes = BioSignatureState.NORMAL, ("WITHIN_INDIVIDUAL_BASELINE",)
            history.append(window)
            deviation_streak, shift_windows = 0, []
        results.append(_result(window, state, codes, scores, baselines, config,
                               baseline_history, history))
    return tuple(results)


def _result(window: BehaviorWindow, state: BioSignatureState, codes: tuple[str, ...],
            scores: Mapping[str, float], baselines: Mapping[str, FeatureBaseline],
            config: BioSignatureConfig, baseline_history: Sequence[BehaviorWindow],
            evidence_history: Sequence[BehaviorWindow]) -> BioSignatureResult:
    statuses = {item.evidence_status for item in (*evidence_history, window)}
    evidence = next((status for status in (
        EvidenceStatus.SIMULATED, EvidenceStatus.ASSUMED,
        EvidenceStatus.EXPERIMENTAL, EvidenceStatus.VALIDATED, EvidenceStatus.FUTURE,
    ) if status in statuses), EvidenceStatus.FUTURE)
    return BioSignatureResult(
        animal_id=window.animal_id, timestamp=window.timestamp, stratum=window.stratum,
        state=state, reason_codes=codes, feature_scores=dict(scores),
        feature_baselines=dict(baselines), threshold=config.threshold,
        baseline_start=baseline_history[0].timestamp if baseline_history else None,
        baseline_end=baseline_history[-1].timestamp if baseline_history else None,
        baseline_observations=len(baseline_history), method=METHOD, version=BIOSIGNATURE_VERSION,
        model_version=window.model_version, taxonomy_version=window.taxonomy_version,
        coverage=window.coverage, confidence=window.confidence,
        evidence_status=evidence, observation_features=dict(window.features),
    )
