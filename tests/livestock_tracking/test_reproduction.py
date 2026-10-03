from datetime import datetime, timedelta, timezone

import pytest

from riose.products.livestock_tracking.domain.contracts import EvidenceStatus
from riose.products.livestock_tracking.reproduction import (
    ActivityObservation,
    EventSource,
    ReproductiveEvent,
    ReproductiveEventType,
    summarize_event_activity,
    summary_json,
    validate_animal_splits,
)


T0 = datetime(2026, 1, 3, tzinfo=timezone.utc)


def observation(animal, hours_before, activity=1.0, status=EvidenceStatus.SIMULATED):
    return ActivityObservation(
        animal_id=animal,
        observed_at=T0 - timedelta(hours=hours_before),
        activity=activity,
        sensor="fixture-accelerometer",
        sensor_position="EAR_TAG",
        evidence_status=status,
        source_ref="fixture:issue-26-v1",
    )


def event(kind=ReproductiveEventType.ESTRUS, source=EventSource.SIMULATED):
    return ReproductiveEvent(
        animal_id="cow-1",
        event_type=kind,
        occurred_at=T0,
        recorded_at=T0 + timedelta(hours=1),
        source=source,
        source_ref="fixture:event-1",
        evidence_status=(EvidenceStatus.SIMULATED if source is EventSource.SIMULATED else EvidenceStatus.EXPERIMENTAL),
    )


def test_summary_uses_only_same_animal_observations_at_or_before_event():
    rows = [
        observation("cow-1", 36, 1.0),
        observation("cow-1", 30, 1.0),
        observation("cow-1", 18, 2.0),
        observation("cow-1", 6, 2.0),
        observation("cow-1", -1, 1000.0),  # future sample must not leak
        observation("cow-2", 6, 999.0),  # other animal must not leak
    ]

    result = summarize_event_activity(event(), rows)

    assert result.observation_count == 2
    assert result.mean_activity == 2.0
    assert result.baseline_mean_activity == 1.0
    assert result.activity_change_ratio == 2.0
    assert result.feature_window_end <= result.event_at
    assert result.evidence_status is EvidenceStatus.SIMULATED
    assert result.score is result.confidence is None
    assert result.status == "DESCRIPTIVE_ONLY"


def test_event_types_remain_separate_and_simulated_event_is_not_ground_truth():
    estrus = summarize_event_activity(event(ReproductiveEventType.ESTRUS), [])
    pregnancy = summarize_event_activity(event(ReproductiveEventType.PREGNANCY_CONFIRMED), [])
    calving = summarize_event_activity(event(ReproductiveEventType.CALVING), [])

    assert {estrus.target, pregnancy.target, calving.target} == {
        ReproductiveEventType.ESTRUS,
        ReproductiveEventType.PREGNANCY_CONFIRMED,
        ReproductiveEventType.CALVING,
    }
    assert not estrus.ground_truth
    assert not pregnancy.ground_truth
    assert not calving.ground_truth
    assert pregnancy.status == "INSUFFICIENT_EVIDENCE"


def test_model_or_behavior_output_cannot_be_declared_validated_ground_truth():
    with pytest.raises(ValueError, match="cannot be validated ground truth"):
        ReproductiveEvent(
            "cow-1", ReproductiveEventType.PREGNANCY_LOSS, T0, T0,
            EventSource.BEHAVIOR_SIGNAL, "prediction:1", EvidenceStatus.VALIDATED,
        )


def test_user_entry_and_unknown_event_are_not_ground_truth():
    assert not event(source=EventSource.USER_ENTRY).ground_truth
    assert not event(ReproductiveEventType.UNKNOWN, EventSource.UNKNOWN).ground_truth


def test_future_event_recording_order_and_non_finite_activity_are_rejected():
    with pytest.raises(ValueError, match="cannot precede"):
        ReproductiveEvent(
            "cow-1", ReproductiveEventType.ESTRUS, T0, T0 - timedelta(seconds=1),
            EventSource.USER_ENTRY, "user:1", EvidenceStatus.EXPERIMENTAL,
        )
    with pytest.raises(ValueError, match="finite number"):
        observation("cow-1", 1, float("nan"))


def test_naive_timestamps_and_empty_animal_ids_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        ActivityObservation("cow-1", datetime(2026, 1, 1), 1.0, "sensor", "ear", EvidenceStatus.SIMULATED, "fixture")
    with pytest.raises(ValueError, match="required"):
        observation(" ", 1)
    with pytest.raises(ValueError, match="timezone-aware"):
        ReproductiveEvent(
            "cow-1", ReproductiveEventType.UNKNOWN, None, T0,
            EventSource.UNKNOWN, "fixture:missing-time", EvidenceStatus.SIMULATED,
        )


def test_animal_overlap_between_evaluation_splits_is_rejected():
    validate_animal_splits({"train": ["cow-1"], "test": ["cow-2"]})
    with pytest.raises(ValueError, match="appears in both"):
        validate_animal_splits({"train": ["cow-1"], "test": ["cow-1"]})


def test_missing_windows_report_insufficient_evidence():
    result = summarize_event_activity(
        event(), [observation("cow-1", 6, 0.0), observation("cow-1", 1, 2.0)]
    )
    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert result.activity_change_ratio is None
    assert result.score is None


def test_signed_activity_with_zero_baseline_keeps_absolute_change_only():
    result = summarize_event_activity(
        event(),
        [
            observation("cow-1", 36, -1.0),
            observation("cow-1", 30, 1.0),
            observation("cow-1", 18, 1.0),
            observation("cow-1", 6, 2.0),
        ],
    )
    assert result.status == "DESCRIPTIVE_ONLY"
    assert result.baseline_mean_activity == 0.0
    assert result.activity_change == 1.5
    assert result.activity_change_ratio is None


def test_sensor_position_mixture_is_not_silently_pooled():
    rows = [
        observation("cow-1", 36),
        observation("cow-1", 30),
        observation("cow-1", 18),
        ActivityObservation(
            "cow-1", T0 - timedelta(hours=6), 1.0, "fixture-collar",
            "NECK", EvidenceStatus.SIMULATED, "fixture:other-sensor",
        ),
    ]
    with pytest.raises(ValueError, match="must be consistent"):
        summarize_event_activity(event(), rows)


def test_non_simulated_historical_entry_stays_experimental_and_keeps_sensor_position():
    result = summarize_event_activity(
        event(source=EventSource.VETERINARY_EXAM),
        [
            observation("cow-1", 36, 1.0, EvidenceStatus.EXPERIMENTAL),
            observation("cow-1", 30, 1.0, EvidenceStatus.EXPERIMENTAL),
            observation("cow-1", 18, 1.1, EvidenceStatus.EXPERIMENTAL),
            observation("cow-1", 6, 0.9, EvidenceStatus.EXPERIMENTAL),
        ],
    )
    assert result.ground_truth
    assert result.evidence_status is EvidenceStatus.EXPERIMENTAL
    assert result.sensor_position == "EAR_TAG"
    assert result.score is None


def test_serialized_output_is_deterministic_and_cannot_claim_a_pregnancy_diagnosis():
    result = summarize_event_activity(event(), [observation("cow-1", 6)])
    encoded = summary_json(result)
    assert encoded == summary_json(result)
    assert '"target": "ESTRUS"' in encoded
    assert '"score": null' in encoded
    assert '"confidence": null' in encoded
    assert '"evidence_status": "SIMULATED"' in encoded
    assert '"pregnant": true' not in encoded.lower()
