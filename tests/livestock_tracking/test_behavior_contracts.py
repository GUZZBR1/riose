import pytest

from riose.products.livestock_tracking.domain.behavior import BehaviorObservation
from riose.products.livestock_tracking.domain.contracts import EvidenceStatus


def observation(**overrides):
    values = dict(
        animal_id="animal-17", timestamp_s=1_700_000_000.0, behavior="WALK",
        source="research-model-v1", evidence_status=EvidenceStatus.EXPERIMENTAL,
        observation_kind="PREDICTION", idempotency_key="animal-17-walk-1700000000",
        end_timestamp_s=1_700_000_010.0, confidence=None,
        model_version="research-model-v1", sensor_position="NECK",
    )
    values.update(overrides)
    return BehaviorObservation(**values)


def test_behavior_observation_keeps_origin_evidence_and_time_bounds():
    value = observation()
    assert value.evidence_status is EvidenceStatus.EXPERIMENTAL
    assert value.observation_kind == "PREDICTION"
    assert value.timestamp_s < value.end_timestamp_s
    assert value.confidence is None


@pytest.mark.parametrize("updates", [
    {"timestamp_s": float("nan")},
    {"end_timestamp_s": 1.0},
    {"evidence_status": "VALIDATED"},
    {"observation_kind": "SIMULATED_MEASUREMENT"},
    {"observation_kind": "PREDICTION", "model_version": None},
    {"confidence": True},
    {"confidence": 1.1},
    {"idempotency_key": ""},
])
def test_behavior_observation_rejects_invalid_contract_values(updates):
    with pytest.raises((TypeError, ValueError)):
        observation(**updates)
