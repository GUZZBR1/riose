from __future__ import annotations

import json

import pytest

from riose.products.livestock_tracking.behavior_ml.feature_schema import (
    SIGNAL_FEATURE_ORDER, SIGNAL_FEATURE_SCHEMA,
)
from riose.products.livestock_tracking.behavior_ml.grouped_cv import evaluate_grouped_cv


def feature_schema(names):
    assert tuple(names) == SIGNAL_FEATURE_ORDER
    return SIGNAL_FEATURE_SCHEMA


def feature_values(value):
    return {name: value + index / 100.0 for index, name in enumerate(SIGNAL_FEATURE_ORDER)}


def test_grouped_cv_holds_out_animals_and_fits_fold_taxonomy_from_training_only():
    rows = []
    for animal in range(10):
        for label, center in (("lying", 0.0), ("walking", 10.0)):
            values = feature_values(center + animal / 100)
            rows.append({
                "animal_id": f"calf-{animal}",
                "raw_label": label,
                "features": values,
                "feature_schema": feature_schema(tuple(values)),
            })
    result = evaluate_grouped_cv(rows, folds=5)
    assert result["animals"] == 10
    assert result["folds"] == 5
    assert result["feature_schema"] == SIGNAL_FEATURE_SCHEMA
    assert all(fold["train_animal_count"] + fold["test_animal_count"] == 10
               for fold in result["results"])
    assert all("train_animals" not in fold and "test_animals" not in fold
               for fold in result["results"])
    assert all(f"calf-{animal}" not in json.dumps(result) for animal in range(10))
    assert all(fold["training_only_selected_source_labels"] == ["lying", "walking"]
               for fold in result["results"])


def test_grouped_cv_rejects_metadata_as_model_input():
    rows = [{"animal_id": animal, "raw_label": "lying",
             "features": {"animal_id": 1.0},
             "feature_schema": SIGNAL_FEATURE_SCHEMA} for animal in ("a", "b")]
    with pytest.raises(ValueError, match="metadata cannot"):
        evaluate_grouped_cv(rows, folds=2)


def test_grouped_cv_reports_majority_fallback_when_training_has_one_class():
    rows = []
    for animal in range(5):
        values = feature_values(float(animal))
        rows.append({"animal_id": f"calf-{animal}", "raw_label": "lying",
                     "features": values, "feature_schema": feature_schema(tuple(values))})
    result = evaluate_grouped_cv(rows, folds=5)
    assert all(fold["model_status"].startswith("INSUFFICIENT_TRAINING_CLASSES")
               for fold in result["results"])


def test_grouped_cv_rejects_empty_small_and_malformed_inputs():
    with pytest.raises(ValueError, match="empty"):
        evaluate_grouped_cv([], folds=2)
    too_small = [{"animal_id": animal, "raw_label": "lying", "features": feature_values(1.0),
                  "feature_schema": SIGNAL_FEATURE_SCHEMA} for animal in ("a", "b")]
    with pytest.raises(ValueError, match="cannot exceed"):
        evaluate_grouped_cv(too_small, folds=3)
    with pytest.raises(ValueError, match="animal_id"):
        evaluate_grouped_cv([{"raw_label": "lying", "features": feature_values(1.0)}], folds=2)
    with pytest.raises(ValueError, match="finite numeric"):
        rows = []
        for animal in ("a", "b"):
            values = feature_values(1.0)
            values[SIGNAL_FEATURE_ORDER[0]] = float("nan")
            rows.append({"animal_id": animal, "raw_label": "lying", "features": values,
                         "feature_schema": SIGNAL_FEATURE_SCHEMA})
        evaluate_grouped_cv(rows, folds=2)


def test_grouped_cv_rejects_unregistered_feature_definitions():
    values = feature_values(0.0)
    invalid_schema = {**SIGNAL_FEATURE_SCHEMA,
                      "definitions": {**SIGNAL_FEATURE_SCHEMA["definitions"],
                                      SIGNAL_FEATURE_ORDER[0]: "an unverified alternative definition"}}
    rows = [
        {"animal_id": animal, "raw_label": "lying", "features": values,
         "feature_schema": invalid_schema}
        for animal in ("a", "b")
    ]
    with pytest.raises(ValueError, match="unregistered feature schema"):
        evaluate_grouped_cv(rows, folds=2)
