"""Animal-grouped cross-validation for external, pre-segmented clips."""

from __future__ import annotations

from collections import Counter
import math
from typing import Any, Mapping, Sequence

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

OTHER = "ACTBECALF.other_unselected"


def evaluate_grouped_cv(rows: Sequence[Mapping[str, Any]], *, folds: int = 5) -> dict[str, Any]:
    """Evaluate fixed logistic regression with every animal held out once.

    Per-fold label collapsing uses only the training animals, and scaling is
    fitted only on the fold's training windows. Source labels stay opaque.
    """
    if type(folds) is not int or folds < 2:
        raise ValueError("folds must be an integer >= 2")
    if not rows:
        raise ValueError("grouped CV input is empty")
    animals = sorted({str(row["animal_id"]) for row in rows})
    if folds > len(animals):
        raise ValueError("folds cannot exceed the number of animals")
    feature_names = tuple(rows[0]["features"])
    reserved = {"animal_id", "session_id", "timestamp", "label", "behavior", "source_row",
                "source_segment_id", "source_label", "raw_label", "window_id", "filename"}
    if not feature_names or {name.lower() for name in feature_names} & reserved:
        raise ValueError("metadata cannot be included in the feature schema")
    for row in rows:
        if tuple(row["features"]) != feature_names:
            raise ValueError("all windows must have the same ordered feature schema")
        if not isinstance(row.get("raw_label"), str) or not row["raw_label"].strip():
            raise ValueError("raw source label is required")
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) for value in row["features"].values()):
            raise ValueError("features must be finite numeric values")

    grouped = GroupKFold(n_splits=folds)
    groups = [str(row["animal_id"]) for row in rows]
    fold_results = []
    for fold_index, (train_idx, test_idx) in enumerate(
        grouped.split(rows, groups=groups), start=1
    ):
        train_rows = [rows[int(index)] for index in train_idx]
        test_rows = [rows[int(index)] for index in test_idx]
        train_animals = {row["animal_id"] for row in train_rows}
        test_animals = {row["animal_id"] for row in test_rows}
        if train_animals & test_animals:
            raise AssertionError("animal leakage in grouped CV fold")
        per_label_animals: dict[str, set[str]] = {}
        for row in train_rows:
            per_label_animals.setdefault(row["raw_label"], set()).add(row["animal_id"])
        minimum_support = max(5, math.ceil(0.5 * len(train_animals)))
        selected = {label for label, ids in per_label_animals.items()
                    if len(ids) >= minimum_support}
        encode = lambda label: label if label in selected else OTHER
        y_train = [encode(row["raw_label"]) for row in train_rows]
        y_test = [encode(row["raw_label"]) for row in test_rows]
        labels = sorted(set(y_train) | set(y_test))
        x_train = [[float(row["features"][name]) for name in feature_names] for row in train_rows]
        x_test = [[float(row["features"][name]) for name in feature_names] for row in test_rows]
        majority = Counter(y_train).most_common(1)[0][0]
        majority_prediction = [majority] * len(y_test)
        baseline_balanced_accuracy = (balanced_accuracy_score(y_test, majority_prediction)
                                      if len(set(y_test)) > 1 else None)
        if len(set(y_train)) < 2:
            predicted = majority_prediction
            model_status = "INSUFFICIENT_TRAINING_CLASSES; deterministic majority fallback"
            balanced_accuracy = baseline_balanced_accuracy
        else:
            scaler = StandardScaler().fit(x_train)
            classifier = LogisticRegression(C=1.0, max_iter=1000)
            classifier.fit(scaler.transform(x_train), y_train)
            predicted = classifier.predict(scaler.transform(x_test))
            model_status = "FITTED"
        balanced_accuracy = (balanced_accuracy_score(y_test, predicted)
                             if len(set(y_test)) > 1 else None)
        fold_results.append({
            "fold": fold_index,
            "train_animals": sorted(train_animals),
            "test_animals": sorted(test_animals),
            "train_windows": len(train_rows),
            "test_windows": len(test_rows),
            "training_only_selected_source_labels": sorted(selected),
            "collapsed_label": OTHER,
            "model_status": model_status,
            "test_status": ("INSUFFICIENT_CLASS_DIVERSITY" if len(set(y_test)) < 2
                            else "EVALUABLE"),
            "model": {
                "accuracy": accuracy_score(y_test, predicted),
                "balanced_accuracy": balanced_accuracy,
                "macro_f1": f1_score(y_test, predicted, labels=labels, average="macro", zero_division=0),
            },
            "majority_baseline": {
                "accuracy": accuracy_score(y_test, majority_prediction),
                "balanced_accuracy": baseline_balanced_accuracy,
                "macro_f1": f1_score(y_test, majority_prediction, labels=labels, average="macro", zero_division=0),
            },
        })
    return {
        "status": "RESEARCH_GROUPED_CV",
        "folds": folds,
        "animals": len(animals),
        "window_count": len(rows),
        "grouping": "animal_id; GroupKFold; each animal occurs in exactly one test fold",
        "label_support_gate": "fit independently in each fold using training animals only",
        "preprocessing": "StandardScaler fitted independently on fold training windows only",
        "model_selection": "fixed LogisticRegression(C=1.0,max_iter=1000); no CV selection",
        "feature_order": feature_names,
        "results": fold_results,
    }
