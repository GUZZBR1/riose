from __future__ import annotations

from dataclasses import replace

import pytest

from riose.products.livestock_tracking.domain.biosignature import (
    BioSignatureConfig, BioSignatureState, BehaviorWindow, evaluate,
)
from riose.products.livestock_tracking.domain.contracts import EvidenceStatus


def window(day: int, walk: float = 0.4, *, animal: str = "cow-a",
           coverage: float = 1.0, confidence: float = 0.9,
           model: str = "behavior-v1", taxonomy: str = "labels-v1",
           status: EvidenceStatus = EvidenceStatus.SIMULATED,
           rest: float | None = None) -> BehaviorWindow:
    return BehaviorWindow(
        animal, float(day), "all-day", {"rest": 1 - walk if rest is None else rest,
                                         "walk": walk}, coverage, confidence,
        model, taxonomy, status,
    )


CFG = BioSignatureConfig(min_history=3, threshold=3.0, scale_floor=0.02,
                         max_gap_seconds=2, persistence_windows=2,
                         rebase_after=4, baseline_window=10)


def test_stable_baseline_has_independently_derived_median_mad_and_score() -> None:
    values = [0.38, 0.40, 0.42]
    results = evaluate([window(i, value) for i, value in enumerate(values)] + [window(3, 0.50)], CFG)
    result = results[-1]
    # Median=(.38+.40+.42)/3=.40; MAD=median(.02,0,.02)=.02.
    assert result.state is BioSignatureState.DEVIATION
    assert result.score == pytest.approx(abs(result.feature_scores["walk"]))
    assert result.feature_baselines["walk"].median == pytest.approx(0.40)
    assert result.feature_baselines["walk"].mad == pytest.approx(0.02)
    assert result.feature_baselines["walk"].scale == pytest.approx(1.4826 * 0.02)
    assert result.feature_scores["walk"] == pytest.approx(0.10 / (1.4826 * 0.02))
    assert result.baseline_end == 2
    assert result.baseline_observations == 3


def test_cold_start_and_low_quality_never_claim_normal_or_score() -> None:
    result = evaluate([window(0), window(1, coverage=0.4), window(2, confidence=0.1)], CFG)
    assert [item.state for item in result] == [BioSignatureState.INSUFFICIENT_HISTORY] * 3
    assert result[0].reason_codes == ("WARMING_UP",)
    assert result[1].reason_codes == ("LOW_COVERAGE",)
    assert result[2].reason_codes == ("LOW_CONFIDENCE",)
    assert result[1].feature_scores == {}
    assert result[0].score is None


def test_missing_class_is_not_interpreted_as_zero_or_anomaly() -> None:
    items = [window(i) for i in range(3)] + [replace(window(3), features={"rest": 0.6, "walk": None})]
    result = evaluate(items, CFG)[-1]
    assert result.state is BioSignatureState.INSUFFICIENT_HISTORY
    assert result.reason_codes == ("MISSING_FEATURE",)


def test_abrupt_up_and_down_are_deviation_and_persistent_shift_is_explicit() -> None:
    base = [window(i, 0.4 + (i % 3 - 1) * 0.01) for i in range(3)]
    up = evaluate(base + [window(3, 0.8), window(4, 0.82)], CFG)
    assert up[-2].state is BioSignatureState.DEVIATION
    assert up[-1].state is BioSignatureState.STRONG_DEVIATION
    assert up[-1].reason_codes == ("PERSISTENT_DEVIATION",)
    down = evaluate(base + [window(3, 0.1)], CFG)
    assert down[-1].state is BioSignatureState.DEVIATION
    assert down[-1].feature_scores["walk"] < -CFG.threshold


def test_confirmed_permanent_shift_rebases_after_configured_delay() -> None:
    base = [window(i, 0.4 + (i % 3 - 1) * 0.01) for i in range(3)]
    shifted = base + [window(i, 0.8 + (i % 3 - 1) * 0.01) for i in range(3, 10)]
    results = evaluate(shifted, CFG)
    assert results[6].state is BioSignatureState.STRONG_DEVIATION
    assert "BASELINE_REBASED_AFTER_PERSISTENT_SHIFT" in results[6].reason_codes
    assert results[7].state is BioSignatureState.NORMAL


def test_gradual_change_is_scored_against_only_prior_accepted_windows() -> None:
    series = [window(i, 0.40 + i * 0.025) for i in range(12)]
    results = evaluate(series, CFG)
    assert results[3].state is BioSignatureState.NORMAL
    # first score after warming up can only use the first three timestamps
    assert results[3].baseline_end == 2
    assert results[-1].baseline_end < results[-1].timestamp
    assert all(item.baseline_end is None or item.baseline_end < item.timestamp for item in results)


def test_animal_profiles_are_independent_and_never_use_herd_average() -> None:
    high = evaluate([window(i, 0.8, animal="cow-high") for i in range(4)], CFG)
    low = evaluate([window(i, 0.1, animal="cow-low") for i in range(4)], CFG)
    assert high[-1].state is low[-1].state is BioSignatureState.NORMAL
    assert high[-1].feature_baselines["walk"].median == pytest.approx(0.8)
    assert low[-1].feature_baselines["walk"].median == pytest.approx(0.1)
    with pytest.raises(ValueError, match="one evaluation sequence"):
        evaluate([window(0, animal="cow-a"), window(1, animal="cow-b")], CFG)


def test_version_mismatch_invalidates_prior_baseline_and_rewarms() -> None:
    items = [window(i) for i in range(4)] + [window(4, model="behavior-v2"),
                                               window(5, model="behavior-v2")]
    results = evaluate(items, CFG)
    assert results[4].reason_codes == ("MODEL_VERSION_MISMATCH",)
    assert results[4].baseline_observations == 0
    assert results[5].reason_codes == ("WARMING_UP",)


def test_duplicate_and_out_of_order_timestamps_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate timestamp"):
        evaluate([window(0), window(0)], CFG)
    with pytest.raises(ValueError, match="increasing"):
        evaluate([window(1), window(0)], CFG)


def test_long_gap_invalidates_baseline_and_restarts_warmup() -> None:
    results = evaluate([window(0), window(1), window(2), window(10, 0.9),
                        window(11), window(12), window(13)], CFG)
    assert results[3].state is BioSignatureState.INSUFFICIENT_HISTORY
    assert results[3].reason_codes == ("GAP_TOO_LONG",)
    assert results[3].baseline_observations == 0
    assert results[-1].state is BioSignatureState.NORMAL


def test_seeded_synthetic_evidence_is_never_promoted() -> None:
    items = [window(i, status=EvidenceStatus.SIMULATED) for i in range(4)]
    result = evaluate(items, CFG)[-1]
    assert result.evidence_status is EvidenceStatus.SIMULATED
    validated = [window(i, status=EvidenceStatus.VALIDATED) for i in range(4)]
    assert evaluate(validated, CFG)[-1].evidence_status is EvidenceStatus.VALIDATED
    assumed = [window(i, status=EvidenceStatus.ASSUMED) for i in range(3)] + [
        window(3, status=EvidenceStatus.VALIDATED)]
    assert evaluate(assumed, CFG)[-1].evidence_status is EvidenceStatus.ASSUMED


def test_scores_are_deterministic_and_threshold_is_configurable() -> None:
    items = [window(i, 0.4 + (i % 3 - 1) * 0.01) for i in range(3)] + [window(3, 0.8)]
    first, second = evaluate(items, CFG), evaluate(items, CFG)
    assert first == second
    assert first[-1].state is BioSignatureState.DEVIATION
    strict = evaluate(items, replace(CFG, threshold=100))
    assert strict[-1].state is BioSignatureState.NORMAL
    assert first[-1].threshold == 3


def test_threshold_boundary_is_inclusive_and_future_cannot_change_past_result() -> None:
    baseline = [window(i, value) for i, value in enumerate((0.38, 0.40, 0.42))]
    scale = 1.4826 * 0.02
    at_boundary = window(3, 0.40 + CFG.threshold * scale)
    later = [window(4, 0.9), window(5, 0.1)]
    prefix_result = evaluate(baseline + [at_boundary], CFG)[-1]
    full_result = evaluate(baseline + [at_boundary] + later, CFG)[-3]
    assert prefix_result == full_result
    assert prefix_result.state is BioSignatureState.DEVIATION
    assert prefix_result.feature_scores["walk"] == pytest.approx(CFG.threshold)


def test_zero_is_an_observed_absence_and_feature_vectors_must_be_compositional() -> None:
    result = evaluate([window(i, 0.0) for i in range(4)], CFG)[-1]
    assert result.state is BioSignatureState.NORMAL
    with pytest.raises(ValueError, match="sum to 1"):
        window(0, 0.4, rest=0.2)
