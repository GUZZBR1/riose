from __future__ import annotations

import pytest

from riose.products.livestock_tracking.behavior_ml.grouped_cv import evaluate_grouped_cv


def test_grouped_cv_holds_out_animals_and_fits_fold_taxonomy_from_training_only():
    rows = []
    for animal in range(10):
        for label, center in (("lying", 0.0), ("walking", 10.0)):
            rows.append({
                "animal_id": f"calf-{animal}",
                "raw_label": label,
                "features": {"mean_x_source": center + animal / 100,
                             "std_x_source": 0.1},
            })
    result = evaluate_grouped_cv(rows, folds=5)
    assert result["animals"] == 10
    assert result["folds"] == 5
    assert all(not set(fold["train_animals"]) & set(fold["test_animals"])
               for fold in result["results"])
    assert all(fold["training_only_selected_source_labels"] == ["lying", "walking"]
               for fold in result["results"])


def test_grouped_cv_rejects_metadata_as_model_input():
    rows = [{"animal_id": animal, "raw_label": "lying",
             "features": {"animal_id": 1.0}} for animal in ("a", "b")]
    with pytest.raises(ValueError, match="metadata cannot"):
        evaluate_grouped_cv(rows, folds=2)


def test_grouped_cv_reports_majority_fallback_when_training_has_one_class():
    rows = [{"animal_id": f"calf-{animal}", "raw_label": "lying",
             "features": {"mean_x_source": float(animal)}} for animal in range(5)]
    result = evaluate_grouped_cv(rows, folds=5)
    assert all(fold["model_status"].startswith("INSUFFICIENT_TRAINING_CLASSES")
               for fold in result["results"])
