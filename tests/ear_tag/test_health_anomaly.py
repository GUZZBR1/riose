from __future__ import annotations

import math

import pytest

from riose.products.ear_tag.health_anomaly import (
    BehaviorObservation,
    DeviationState,
    analyze_behavior,
)
from riose.products.livestock_tracking.domain.contracts import EvidenceStatus


def history(
    animal_id: str = "cow-a",
    *,
    activity: float = 20,
    rumination: float = 500,
    position: str = "EAR",
    status: EvidenceStatus = EvidenceStatus.SIMULATED,
) -> list[BehaviorObservation]:
    return [
        BehaviorObservation(
            animal_id=animal_id,
            timestamp_s=float(day),
            sensor_position=position,
            activity=activity + (day % 2) * 0.2,
            rumination_minutes=rumination + (day % 2) * 1,
            locomotion_steps=100 + (day % 2),
            evidence_status=status,
        )
        for day in range(1, 8)
    ]


def observation(
    timestamp: float,
    *,
    animal_id: str = "cow-a",
    position: str = "EAR",
    activity: float | None = 20,
    rumination: float | None = 500,
    locomotion_steps: float | None = 100,
    status: EvidenceStatus = EvidenceStatus.SIMULATED,
) -> BehaviorObservation:
    return BehaviorObservation(
        animal_id=animal_id,
        timestamp_s=timestamp,
        sensor_position=position,
        activity=activity,
        rumination_minutes=rumination,
        locomotion_steps=locomotion_steps,
        evidence_status=status,
    )


def test_stable_behavior_is_not_a_health_clearance_and_keeps_simulated_status():
    result = analyze_behavior([*history(), observation(8)], animal_id="cow-a",
                              observed_at_s=8, sensor_position="EAR")
    assert result.state is DeviationState.NO_SIGNIFICANT_BEHAVIORAL_DEVIATION
    assert result.score <= result.threshold
    assert result.evidence_status is EvidenceStatus.SIMULATED
    assert "does not rule out disease" in " ".join(result.limitations)


@pytest.mark.parametrize("activity_level", [2.0, 200.0])
def test_individually_low_and_high_activity_are_stable_against_self(activity_level: float):
    samples = history(activity=activity_level)
    samples.append(observation(8, activity=activity_level, rumination=500))
    result = analyze_behavior(samples, animal_id="cow-a", observed_at_s=8,
                              sensor_position="EAR")
    assert result.state is DeviationState.NO_SIGNIFICANT_BEHAVIORAL_DEVIATION


@pytest.mark.parametrize("activity", [0, 100])
def test_abrupt_decrease_or_increase_is_only_an_investigation_signal(activity: float):
    result = analyze_behavior([*history(), observation(8, activity=activity)],
                              animal_id="cow-a", observed_at_s=8,
                              sensor_position="EAR")
    assert result.state is DeviationState.INVESTIGATE
    assert result.reason_codes == ("ACTIVITY_DEVIATION",)
    assert result.score >= result.threshold
    assert result.evidence_status is EvidenceStatus.SIMULATED


@pytest.mark.parametrize(
    ("feature_value", "reason_code"),
    [(700, "RUMINATION_DEVIATION"), (0, "LOCOMOTION_DEVIATION")],
)
def test_measured_rumination_and_locomotion_have_behavioral_reason_codes(
    feature_value: float, reason_code: str
):
    current = (
        observation(8, rumination=feature_value)
        if reason_code == "RUMINATION_DEVIATION"
        else observation(8, locomotion_steps=feature_value)
    )
    result = analyze_behavior([*history(), current], animal_id="cow-a",
                              observed_at_s=8, sensor_position="EAR")
    assert result.state is DeviationState.INVESTIGATE
    assert reason_code in result.reason_codes


def test_cold_start_and_missing_values_are_inconclusive_not_normal():
    cold_start = analyze_behavior([observation(1)], animal_id="cow-a",
                                  observed_at_s=1, sensor_position="EAR")
    no_data = BehaviorObservation("cow-a", 8, "EAR", evidence_status=EvidenceStatus.SIMULATED)
    missing = analyze_behavior([*history(), no_data],
                               animal_id="cow-a", observed_at_s=8,
                               sensor_position="EAR")
    assert cold_start.state is DeviationState.INSUFFICIENT_DATA
    assert missing.state is DeviationState.INSUFFICIENT_DATA
    assert cold_start.score is None
    assert missing.reason_codes == ("INSUFFICIENT_COVERAGE",)


def test_partial_missingness_does_not_turn_missing_metric_into_zero():
    result = analyze_behavior([*history(), observation(8, activity=None)],
                              animal_id="cow-a", observed_at_s=8,
                              sensor_position="EAR")
    assert result.state is DeviationState.NO_SIGNIFICANT_BEHAVIORAL_DEVIATION
    assert all(item.feature != "activity" for item in result.deviations)
    assert any("insufficient coverage" in item for item in result.limitations)


def test_future_rows_and_other_animals_cannot_change_the_result():
    target = [*history(), observation(8, activity=0)]
    baseline = analyze_behavior(target, animal_id="cow-a", observed_at_s=8,
                                sensor_position="EAR")
    with_irrelevant_rows = analyze_behavior(
        [*target, observation(99, activity=1_000_000), *history("cow-b", activity=1_000_000)],
        animal_id="cow-a", observed_at_s=8, sensor_position="EAR"
    )
    assert with_irrelevant_rows == baseline


def test_other_sensor_positions_do_not_leak_into_baseline():
    result = analyze_behavior(
        [*history(position="COLLAR"), observation(8, position="EAR")],
        animal_id="cow-a", observed_at_s=8, sensor_position="EAR"
    )
    assert result.state is DeviationState.INSUFFICIENT_DATA
    assert result.sensor_position == "EAR"


def test_temporary_deviation_and_recovery_are_compared_to_past_individual_baseline():
    data = [*history(), observation(8, activity=0), observation(9, activity=20)]
    deviation = analyze_behavior(data, animal_id="cow-a", observed_at_s=8,
                                 sensor_position="EAR")
    recovery = analyze_behavior(data, animal_id="cow-a", observed_at_s=9,
                                sensor_position="EAR")
    assert deviation.state is DeviationState.INVESTIGATE
    assert recovery.state is DeviationState.NO_SIGNIFICANT_BEHAVIORAL_DEVIATION
    assert recovery.baseline_end_s == 8


def test_experimental_input_is_not_promoted_to_validated():
    result = analyze_behavior(
        [*history(status=EvidenceStatus.EXPERIMENTAL),
         observation(8, status=EvidenceStatus.EXPERIMENTAL)],
        animal_id="cow-a", observed_at_s=8, sensor_position="EAR"
    )
    assert result.evidence_status is EvidenceStatus.EXPERIMENTAL
    assert EvidenceStatus.VALIDATED not in result.input_evidence_statuses


@pytest.mark.parametrize("kwargs", [
    {"activity": -1},
    {"activity": math.nan},
    {"activity": math.inf},
    {"rumination_minutes": 1441},
])
def test_invalid_sensor_scores_are_rejected(kwargs):
    with pytest.raises(ValueError):
        BehaviorObservation("cow-a", 1, "EAR", **kwargs)


def test_threshold_boundary_is_inclusive_and_bad_parameters_are_rejected():
    result = analyze_behavior([*history(), observation(8, activity=23.7)],
                              animal_id="cow-a", observed_at_s=8,
                              sensor_position="EAR", threshold=3.5)
    assert result.state is DeviationState.INVESTIGATE
    with pytest.raises(ValueError):
        analyze_behavior(history(), animal_id="cow-a", observed_at_s=8,
                         sensor_position="EAR", threshold=0)


def test_unknown_rows_and_duplicate_times_are_rejected():
    with pytest.raises(ValueError):
        analyze_behavior([*history(), object()], animal_id="cow-a",
                         observed_at_s=8, sensor_position="EAR")
    with pytest.raises(ValueError):
        analyze_behavior([*history(), history()[-1]], animal_id="cow-a",
                         observed_at_s=8, sensor_position="EAR")


def test_synthetic_demo_labels_its_result_and_never_promotes_provenance():
    from riose.products.ear_tag.health_anomaly.demo import synthetic_demo

    demo = synthetic_demo()
    assert "not clinical validation" in demo["disclaimer"]
    assert demo["result"]["evidence_status"] == EvidenceStatus.SIMULATED.value
    assert demo["result"]["state"] == DeviationState.INVESTIGATE.value


def test_oversized_integer_score_is_rejected_without_overflowing_validation():
    with pytest.raises(ValueError):
        BehaviorObservation("cow-a", 1, "EAR", activity=10**1000)
