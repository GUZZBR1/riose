from __future__ import annotations

from dataclasses import replace

import pytest

from riose.products.livestock_tracking.adapters.persistence.sqlite_store import Store
from riose.products.livestock_tracking.domain.contracts import EvidenceStatus
from riose.products.livestock_tracking.domain.intelligence import (
    BehaviorPrediction,
    PredictionTimeBasis,
)


def prediction(**changes):
    value = BehaviorPrediction(
        animal_id="external-calf-1",
        tag_id="ACTBECALF:external-calf-1",
        window_start_s=1.0,
        window_end_s=4.0,
        created_at_s=10.0,
        behavior="ACTBECALF:lying",
        confidence=None,
        model_score=0.73,
        model_version="behavior-eval-v1",
        model_sha256="a" * 64,
        feature_version="signal-unknown-unit-v1",
        evidence_status=EvidenceStatus.EXPERIMENTAL,
        source_ref="ACTBECALF.0123456789abcdef:rows-2-76",
        input_sha256="b" * 64,
        prediction_id="c" * 64,
        time_basis=PredictionTimeBasis.SOURCE_RELATIVE_SECONDS,
    )
    return replace(value, **changes)


def test_prediction_store_round_trip_preserves_relative_time_and_scores(tmp_path):
    store = Store(tmp_path / "core.sqlite3")
    try:
        value = prediction()
        assert store.save_behavior_prediction(value) is True
        assert store.save_behavior_prediction(value) is False
        assert store.list_behavior_predictions(value.animal_id) == [value]
        assert store.get_behavior_prediction(value.prediction_id) == value
        assert store.connection.execute("SELECT COUNT(*) FROM animals").fetchone()[0] == 0
    finally:
        store.close()

    reopened = Store(tmp_path / "core.sqlite3")
    try:
        assert reopened.list_behavior_predictions(value.animal_id) == [value]
    finally:
        reopened.close()


def test_prediction_id_conflict_does_not_overwrite_existing_record(tmp_path):
    store = Store(tmp_path / "core.sqlite3")
    try:
        assert store.save_behavior_prediction(prediction()) is True
        with pytest.raises(ValueError, match="different prediction data"):
            store.save_behavior_prediction(prediction(model_score=0.9))
        saved = store.list_behavior_predictions("external-calf-1")
        assert saved[0].model_score == 0.73
    finally:
        store.close()


def test_utc_remains_the_backward_compatible_default():
    value = prediction(time_basis=PredictionTimeBasis.UTC_UNIX_SECONDS)
    assert value.time_basis is PredictionTimeBasis.UTC_UNIX_SECONDS
