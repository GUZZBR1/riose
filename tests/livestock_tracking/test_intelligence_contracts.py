import pytest

from riose.products.livestock_tracking.domain.contracts import EvidenceStatus
from riose.products.livestock_tracking.domain.intelligence import BehaviorPrediction


def prediction(**overrides):
    values = dict(
        animal_id="animal-17", tag_id="tag-17", window_start_s=100.0,
        window_end_s=110.0, created_at_s=111.0, behavior="WALK", confidence=0.73,
        model_version="behavior-v1", model_sha256="a" * 64,
        feature_version="movement-window-v1", evidence_status=EvidenceStatus.SIMULATED,
        source_ref="dataset.synthetic-v1", input_sha256="b" * 64,
        prediction_id="prediction-17-100",
    )
    values.update(overrides)
    return BehaviorPrediction(**values)


def test_behavior_prediction_keeps_identity_window_and_provenance():
    value = prediction()
    assert value.animal_id == "animal-17"
    assert value.tag_id == "tag-17"
    assert value.created_at_s == 111.0
    assert value.model_sha256 == "a" * 64
    assert value.feature_version == "movement-window-v1"
    assert value.evidence_status is EvidenceStatus.SIMULATED


@pytest.mark.parametrize("updates", [
    {"window_end_s": 100},
    {"window_start_s": float("nan")},
    {"created_at_s": -1},
    {"confidence": True},
    {"confidence": 1.1},
    {"model_sha256": "unknown"},
    {"input_sha256": "A" * 64},
    {"evidence_status": "VALIDATED"},
])
def test_behavior_prediction_rejects_invalid_provenance_and_values(updates):
    with pytest.raises((TypeError, ValueError)):
        prediction(**updates)


def test_confidence_may_be_absent_without_inventing_a_score():
    assert prediction(confidence=None).confidence is None
