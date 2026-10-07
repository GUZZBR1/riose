"""Small, offline, animal-aware behavior classification pipeline.

The bundled fixture is synthetic software test data. This module does not
claim that its labels or features represent measured cattle or an ear tag.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import random
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..domain.contracts import EvidenceStatus

FEATURE_NAMES = ("accel_mean_g", "accel_std_g", "accel_rms_g")
FEATURE_VERSION = "movement-window-v1"
MODEL_VERSION = "behavior-baseline-v1"
ACTBECALF_MODEL_VERSION = "behavior-actbecalf-e2e-v1"
ARTIFACT_SCHEMA_VERSION = 1
KNOWN_BEHAVIORS = ("REST", "WALK", "GRAZE")


@dataclass(frozen=True)
class BehaviorWindow:
    window_id: str
    animal_id: str
    session_id: str
    label: str
    features: Mapping[str, float]
    dataset_id: str
    dataset_source: str
    dataset_license: str
    sensor_position: str
    sample_rate_hz: float | None
    evidence_status: str = "SIMULATED"
    source_label: str | None = None
    feature_version: str = FEATURE_VERSION
    source_file_sha256: str | None = None
    source_provenance_verified: bool = False


def _validate_windows(windows: Sequence[BehaviorWindow]) -> tuple[str, ...]:
    if not windows:
        raise ValueError("training input is empty")
    ids: set[str] = set()
    session_animals: dict[str, str] = {}
    dataset_metadata: dict[str, tuple[str, str]] = {}
    feature_names = tuple(windows[0].features.keys()) if isinstance(windows[0].features, Mapping) else ()
    if not feature_names or any(not isinstance(name, str) or not name for name in feature_names):
        raise ValueError("features must have a non-empty ordered feature schema")
    reserved_features = {
        "animal_id", "session_id", "timestamp", "timestamp_s", "label", "behavior",
        "dataset_id", "dataset_source", "dataset_license", "sensor_position",
        "source_file_sha256", "source_label", "window_id", "source_row",
        "segid", "source_segment_id", "segment_id", "source_row_start", "source_row_end",
        "source_file", "filename", "recording_id", "animal", "session", "event_time",
    }
    if {name.lower() for name in feature_names}.intersection(reserved_features):
        raise ValueError("features must have exactly this order of signal values; metadata cannot be features")
    feature_versions = {row.feature_version for row in windows}
    if len(feature_versions) != 1 or any(not isinstance(value, str) or not value.strip()
                                         for value in feature_versions):
        raise ValueError("all windows must use one non-empty feature version")
    for row in windows:
        if any(not isinstance(value, str) or not value.strip()
               for value in (row.window_id, row.animal_id, row.session_id)):
            raise ValueError("window_id, animal_id and session_id are required")
        if row.window_id in ids:
            raise ValueError(f"duplicate window_id: {row.window_id}")
        ids.add(row.window_id)
        previous = session_animals.setdefault(row.session_id, row.animal_id)
        if previous != row.animal_id:
            raise ValueError(f"session_id {row.session_id!r} maps to multiple animals")
        if not isinstance(row.label, str) or not row.label.strip():
            raise ValueError("behavior label must be a non-empty string")
        if row.dataset_id == "riose-behavior-synthetic-fixture-v1":
            if row.label not in KNOWN_BEHAVIORS or row.source_label is not None:
                raise ValueError(f"unknown or unsupported synthetic behavior label: {row.label!r}")
            if feature_names != FEATURE_NAMES:
                raise ValueError(f"features must have exactly this order: {list(FEATURE_NAMES)}")
        elif row.dataset_id == "actbecalf":
            if (not re.fullmatch(r"ACTBECALF\.[a-z0-9_.-]{1,100}", row.label)
                    or not isinstance(row.source_label, str) or not row.source_label.strip()):
                raise ValueError("ActBeCalf windows require a namespaced label and original source_label")
        elif row.label not in KNOWN_BEHAVIORS:
            raise ValueError(f"unknown or unsupported behavior label: {row.label!r}")
        if any(not isinstance(value, str) or not value.strip() for value in
               (row.dataset_id, row.dataset_source, row.dataset_license, row.sensor_position)):
            raise ValueError("dataset ID, source, license and sensor position provenance are required")
        if row.evidence_status not in {status.value for status in EvidenceStatus}:
            raise ValueError(f"unknown evidence status: {row.evidence_status!r}")
        metadata = (row.dataset_source, row.dataset_license)
        if row.dataset_id in dataset_metadata and dataset_metadata[row.dataset_id] != metadata:
            raise ValueError(f"dataset_id {row.dataset_id!r} has conflicting source/license provenance")
        dataset_metadata[row.dataset_id] = metadata
        if row.source_file_sha256 is not None and (
                not re.fullmatch(r"[0-9a-f]{64}", row.source_file_sha256)):
            raise ValueError("source_file_sha256 must be a lowercase SHA-256 digest")
        if not isinstance(row.source_provenance_verified, bool):
            raise ValueError("source_provenance_verified must be an explicit boolean")
        if row.sample_rate_hz is not None and (isinstance(row.sample_rate_hz, bool) or
                not isinstance(row.sample_rate_hz, (int, float)) or
                not math.isfinite(row.sample_rate_hz) or row.sample_rate_hz <= 0):
            raise ValueError("sample_rate_hz must be null when unknown or finite and positive")
        if not isinstance(row.features, Mapping):
            raise ValueError("features must be an ordered feature object")
        if tuple(row.features.keys()) != feature_names:
            raise ValueError(f"features must have one consistent ordered schema: {list(feature_names)}")
        for name, value in row.features.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"feature {name} must be a finite number")
    return feature_names


def _matrix(windows: Sequence[BehaviorWindow], feature_names: Sequence[str] | None = None) -> np.ndarray:
    import numpy as np
    schema = tuple(feature_names or windows[0].features.keys())
    return np.asarray([[float(row.features[name]) for name in schema] for row in windows], dtype=np.float64)


def split_by_animal(windows: Sequence[BehaviorWindow], seed: int = 23) -> dict[str, list[BehaviorWindow]]:
    """Deterministic 60/20/20 split by animal; all windows/sessions stay together."""
    _validate_windows(windows)
    animals = sorted({row.animal_id for row in windows})
    if len(animals) < 5:
        raise ValueError("at least five distinct animals are required for train/validation/test")
    random.Random(seed).shuffle(animals)
    test_n = max(1, round(len(animals) * 0.2))
    validation_n = max(1, round(len(animals) * 0.2))
    if test_n + validation_n >= len(animals):
        raise ValueError("not enough animals for non-empty train/validation/test splits")
    test_animals = set(animals[:test_n])
    validation_animals = set(animals[test_n:test_n + validation_n])
    train_animals = set(animals[test_n + validation_n:])
    groups = {
        "train": [row for row in windows if row.animal_id in train_animals],
        "validation": [row for row in windows if row.animal_id in validation_animals],
        "test": [row for row in windows if row.animal_id in test_animals],
    }
    animal_sets = {name: {row.animal_id for row in rows} for name, rows in groups.items()}
    if (animal_sets["train"] & animal_sets["validation"] or
            animal_sets["train"] & animal_sets["test"] or
            animal_sets["validation"] & animal_sets["test"]):
        raise AssertionError("animal leakage across splits")
    return groups


def _metrics(y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str],
             animals: Sequence[str]) -> dict[str, Any]:
    from sklearn.metrics import (accuracy_score, balanced_accuracy_score,
                                 classification_report, confusion_matrix, f1_score)

    report = classification_report(y_true, y_pred, labels=list(labels), output_dict=True, zero_division=0)
    by_animal: dict[str, Any] = {}
    for animal in sorted(set(animals)):
        indices = [i for i, value in enumerate(animals) if value == animal]
        by_animal[animal] = {
            "support": len(indices),
            "accuracy": float(accuracy_score([y_true[i] for i in indices], [y_pred[i] for i in indices])),
            "macro_f1": float(f1_score([y_true[i] for i in indices], [y_pred[i] for i in indices],
                                        labels=list(labels), average="macro", zero_division=0)),
        }
    return {
        "classes": list(labels),
        "support": {label: int(sum(value == label for value in y_true)) for label in labels},
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, labels=list(labels), average="macro", zero_division=0)),
        "per_class": {label: {key: float(report[label][key]) for key in ("precision", "recall", "f1-score", "support")}
                      for label in labels},
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=list(labels)).tolist(),
        "per_animal": by_animal,
    }


def _portable_model(model: Any, name: str) -> dict[str, Any]:
    if name == "logistic_regression":
        return {"kind": name, "classes": model.classes_.tolist(),
                "coef": model.coef_.tolist(), "intercept": model.intercept_.tolist()}
    if name == "decision_tree":
        tree = model.tree_
        return {"kind": name, "classes": model.classes_.tolist(),
                "children_left": tree.children_left.tolist(), "children_right": tree.children_right.tolist(),
                "feature": tree.feature.tolist(), "threshold": tree.threshold.tolist(),
                "values": tree.value[:, 0, :].tolist()}
    if name == "extra_trees":
        return {"kind": name, "classes": model.classes_.tolist(),
                "trees": [_portable_model(tree, "decision_tree") for tree in model.estimators_]}
    raise ValueError(f"unsupported portable model: {name}")


def _majority_label(labels: Sequence[str], training_labels: Sequence[str]) -> str:
    """Choose the lexicographically first class among equal training counts."""
    if not labels or not training_labels:
        raise ValueError("majority label selection requires labels")
    return min(labels, key=lambda label: (-training_labels.count(label), label))


def _tree_scores(model: Mapping[str, Any], row: Sequence[float]) -> list[float]:
    node = 0
    while model["children_left"][node] != model["children_right"][node]:
        feature = model["feature"][node]
        node = model["children_left"][node] if row[feature] <= model["threshold"][node] else model["children_right"][node]
    counts = model["values"][node]
    total = sum(counts)
    return [count / total if total else 0.0 for count in counts]


def _model_scores(model: Mapping[str, Any], row: Sequence[float], mean: Sequence[float],
                  scale: Sequence[float]) -> list[float]:
    kind = model["kind"]
    if kind == "logistic_regression":
        standardized = [(value - mean[i]) / scale[i] for i, value in enumerate(row)]
        logits = [sum(a * b for a, b in zip(coef, standardized)) + intercept
                  for coef, intercept in zip(model["coef"], model["intercept"])]
        if len(logits) == 1:  # binary sklearn logistic regression
            positive = 1.0 / (1.0 + math.exp(-max(-700.0, min(700.0, logits[0]))))
            return [1.0 - positive, positive]
        maximum = max(logits)
        exp = [math.exp(value - maximum) for value in logits]
        return [value / sum(exp) for value in exp]
    if kind == "decision_tree":
        return _tree_scores(model, row)
    if kind == "majority":
        return model["scores"]
    if kind == "extra_trees":
        trees = [_tree_scores(tree, row) for tree in model["trees"]]
        return [sum(tree[i] for tree in trees) / len(trees) for i in range(len(model["classes"]))]
    raise ValueError(f"unknown artifact model kind: {kind}")


def _predict_payload(payload: Mapping[str, Any], features: Mapping[str, float]) -> tuple[str, float]:
    expected = payload["feature_order"]
    if tuple(features.keys()) != tuple(expected):
        raise ValueError(f"features must have exactly this order: {expected}")
    row = []
    for name in expected:
        value = features[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"feature {name} must be a finite number")
        row.append(float(value))
    scores = _model_scores(payload["model"], row, payload["preprocessing"]["mean"],
                           payload["preprocessing"]["scale"])
    index = max(range(len(scores)), key=scores.__getitem__)
    return payload["model"]["classes"][index], float(scores[index])


def run_training(windows: Sequence[BehaviorWindow], seed: int = 23) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compare models on validation; evaluate chosen model once on animal holdout."""
    import numpy as np
    import sklearn
    from sklearn.dummy import DummyClassifier
    from sklearn.ensemble import ExtraTreesClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, f1_score
    from sklearn.preprocessing import StandardScaler
    from sklearn.tree import DecisionTreeClassifier

    windows = list(windows)
    feature_names = _validate_windows(windows)
    feature_version = windows[0].feature_version
    groups = split_by_animal(windows, seed)
    model_version = (ACTBECALF_MODEL_VERSION if {row.dataset_id for row in windows} == {"actbecalf"}
                     else MODEL_VERSION)
    train, validation, test = (groups[name] for name in ("train", "validation", "test"))
    train_labels = sorted({row.label for row in train})
    all_labels = sorted({row.label for row in windows})
    if not train_labels:
        raise ValueError("training partition must contain at least one behavior label")
    if ({row.dataset_id for row in windows} == {"riose-behavior-synthetic-fixture-v1"}
            and set(train_labels) != set(all_labels)):
        raise ValueError("every behavior class must appear in training animals")
    config = {
        "seed": seed,
        "split": "deterministic animal-disjoint 60/20/20; validation selects candidate; test evaluated once",
        "feature_version": feature_version,
        "feature_order": list(feature_names),
        "candidate_models": ["majority_baseline", "logistic_regression", "decision_tree", "extra_trees"],
        "selection_metric": "validation macro_f1; simpler model wins ties",
        "candidate_parameters": {"logistic_regression": {"C": 1.0, "max_iter": 1000},
                                  "decision_tree": {"max_depth": 4, "min_samples_leaf": 2},
                                  "extra_trees": {"n_estimators": 40, "max_depth": 5, "min_samples_leaf": 2}},
    }
    candidates: list[tuple[str, Any, StandardScaler | None, float]] = []
    majority = DummyClassifier(strategy="most_frequent").fit(_matrix(train, feature_names), [row.label for row in train])
    majority_validation = majority.predict(_matrix(validation, feature_names)).tolist()
    majority_score = float(f1_score([row.label for row in validation], majority_validation,
                                    labels=all_labels, average="macro", zero_division=0))
    candidates.append(("majority_baseline", majority, None, majority_score))
    scaler = StandardScaler().fit(_matrix(train, feature_names))
    x_train = scaler.transform(_matrix(train, feature_names))
    x_validation = scaler.transform(_matrix(validation, feature_names))
    y_train = [row.label for row in train]
    y_validation = [row.label for row in validation]
    sklearn_models = [
        ("logistic_regression", LogisticRegression(C=1.0, max_iter=1000, random_state=seed), True),
        ("decision_tree", DecisionTreeClassifier(max_depth=4, min_samples_leaf=2, random_state=seed), False),
        ("extra_trees", ExtraTreesClassifier(n_estimators=40, max_depth=5, min_samples_leaf=2,
                                              random_state=seed, n_jobs=1), False),
    ]
    validation_rows = [{"model": "majority_baseline", "validation_macro_f1": majority_score}]
    for name, estimator, scale_features in sklearn_models:
        candidate_train = x_train if scale_features else _matrix(train, feature_names)
        candidate_validation = x_validation if scale_features else _matrix(validation, feature_names)
        estimator.fit(candidate_train, y_train)
        predictions = estimator.predict(candidate_validation).tolist()
        score = float(f1_score(y_validation, predictions, labels=all_labels, average="macro", zero_division=0))
        candidates.append((name, estimator, scaler if scale_features else None, score))
        validation_rows.append({"model": name, "validation_macro_f1": score})
    # Complexity is an explicit tie-break, independent of test results.
    complexity = {"logistic_regression": 0, "decision_tree": 1, "extra_trees": 2, "majority_baseline": 3}
    selected_name, _, _, selected_score = max(candidates, key=lambda item: (item[3], -complexity[item[0]]))
    model_labels = sorted({row.label for row in (train if selected_name == "majority_baseline"
                                                  else train + validation)})
    if selected_name == "majority_baseline":
        # Persist an explicit majority model only if validation proves no candidate better.
        artifact_model = {"kind": "majority", "classes": model_labels,
                          "label": _majority_label(model_labels, [row.label for row in train]),
                          "scores": [sum(r.label == label for r in train) / len(train) for label in model_labels]}
        mean, scale = [0.0] * len(feature_names), [1.0] * len(feature_names)
    else:
        final_scaler = StandardScaler().fit(_matrix(train + validation, feature_names))
        final_estimator, scale_features = next((est, scaled) for name, est, scaled in sklearn_models
                                               if name == selected_name)
        final_x = (final_scaler.transform(_matrix(train + validation, feature_names)) if scale_features
                   else _matrix(train + validation, feature_names))
        final_estimator.fit(final_x, [row.label for row in train + validation])
        artifact_model = _portable_model(final_estimator, selected_name)
        mean, scale = ((final_scaler.mean_.tolist(), final_scaler.scale_.tolist()) if scale_features
                       else ([0.0] * len(feature_names), [1.0] * len(feature_names)))
    payload: dict[str, Any] = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "model_version": model_version,
        "model_type": selected_name,
        "feature_version": feature_version,
        "feature_order": list(feature_names),
        # The artifact lists classes the selected estimator actually learned;
        # test-only labels remain evaluation targets and cannot become outputs.
        "classes": model_labels,
        "model": artifact_model,
        "preprocessing": {"kind": "standard_scaler" if selected_name == "logistic_regression" else "identity",
                          "mean": mean, "scale": scale},
        "training_config": config,
        "versions": {"python": platform.python_version(), "numpy": np.__version__, "scikit_learn": sklearn.__version__},
        "provenance": {
            "dataset_ids": sorted({row.dataset_id for row in windows}),
            "dataset_sources": {row.dataset_id: {"source": row.dataset_source, "license": row.dataset_license}
                                for row in sorted(windows, key=lambda item: item.dataset_id)},
            "sensor_positions": sorted({row.sensor_position for row in windows}),
            "sample_rates_hz": sorted({row.sample_rate_hz for row in windows},
                                       key=lambda value: -math.inf if value is None else value),
            "evidence_statuses": sorted({row.evidence_status for row in windows}),
            "window_count": len(windows),
            "animal_count": len({row.animal_id for row in windows}),
            "dataset_sha256": _dataset_hash(windows),
            "source_file_sha256": sorted({row.source_file_sha256 for row in windows
                                           if row.source_file_sha256 is not None}),
            "class_source_labels": {
                label: sorted({row.source_label for row in windows
                               if row.label == label and row.source_label is not None})
                for label in sorted({row.label for row in windows})
            },
        },
        "split": {name: {"animals": sorted({row.animal_id for row in rows}), "windows": len(rows)}
                  for name, rows in groups.items()},
        "evaluation": {"selection_metric": config["selection_metric"],
                       "validation_candidates": validation_rows,
                       "selected_validation_macro_f1": selected_score,
                       "holdout": None},
        "confidence_semantics": "maximum model score; not a calibrated probability",
        "evidence_interpretation": {
            "result_status": ("SIMULATED_SOFTWARE_PIPELINE_ONLY"
                              if {row.evidence_status for row in windows} == {"SIMULATED"}
                              else "EXPERIMENTAL_MODEL_RESULT"),
            "source_data_status": ("MEASURED_EXTERNAL_DATA" if
                                   all(row.source_provenance_verified and
                                       row.source_file_sha256 is not None for row in windows)
                                   else "NOT_ASSERTED"),
            "sensor_position_transfer": "NOT_VALIDATED",
            "scientific_validation": "NOT_ASSESSED",
            "ear_tag_validation": False,
            "clinical_diagnosis": False,
        },
    }
    if selected_name == "majority_baseline":
        y_pred = [artifact_model["label"]] * len(test)
    else:
        y_pred = [_predict_payload(payload, row.features)[0] for row in test]
    test_y = [row.label for row in test]
    payload["evaluation"]["holdout"] = _metrics(test_y, y_pred, all_labels, [row.animal_id for row in test])
    payload["evaluation"]["holdout"]["majority_baseline_accuracy"] = float(
        accuracy_score(test_y, majority.predict(_matrix(test, feature_names))))
    baseline_predictions = majority.predict(_matrix(test, feature_names)).tolist()
    payload["evaluation"]["holdout"]["majority_baseline_metrics"] = _metrics(
        test_y, baseline_predictions, all_labels, [row.animal_id for row in test])
    payload["evaluation"]["holdout"]["per_dataset"] = {
        dataset_id: _metrics(
            [row.label for row in test if row.dataset_id == dataset_id],
            [prediction for row, prediction in zip(test, y_pred) if row.dataset_id == dataset_id],
            all_labels,
            [row.animal_id for row in test if row.dataset_id == dataset_id],
        ) for dataset_id in sorted({row.dataset_id for row in test})
    }
    payload["evaluation"]["holdout"]["test_animals_used_for_selection"] = False
    return payload, {"selected_model": selected_name, "selected_validation_macro_f1": selected_score,
                     "holdout": payload["evaluation"]["holdout"]}


def _dataset_hash(windows: Iterable[BehaviorWindow]) -> str:
    encoded = json.dumps([asdict(row) for row in windows], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def save_artifact(payload: Mapping[str, Any], path: str | Path) -> None:
    artifact_path = Path(path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _validate_artifact(payload: Mapping[str, Any]) -> None:
    if not isinstance(payload, Mapping):
        raise ValueError("artifact must be a JSON object")
    if payload.get("schema_version") != ARTIFACT_SCHEMA_VERSION or payload.get("model_version") not in {
            MODEL_VERSION, ACTBECALF_MODEL_VERSION}:
        raise ValueError("unsupported artifact schema or model version")
    feature_order = payload.get("feature_order")
    feature_version = payload.get("feature_version")
    if (not isinstance(feature_order, list) or not feature_order or
            any(not isinstance(name, str) or not name for name in feature_order) or
            len(set(feature_order)) != len(feature_order) or
            not isinstance(feature_version, str) or not feature_version.strip()):
        raise ValueError("artifact feature contract mismatch")
    if payload.get("model_version") == MODEL_VERSION and feature_order != list(FEATURE_NAMES):
        raise ValueError("artifact feature contract mismatch")
    feature_count = len(feature_order)
    classes = payload.get("classes")
    if not isinstance(classes, list) or not classes or any(not isinstance(label, str) for label in classes) or len(set(classes)) != len(classes):
        raise ValueError("artifact classes are invalid")
    if payload.get("model_type") not in {"majority_baseline", "logistic_regression", "decision_tree", "extra_trees"}:
        raise ValueError("unsupported artifact model type")
    if not isinstance(payload.get("model"), Mapping) or payload["model"].get("kind") not in {
            "majority", "logistic_regression", "decision_tree", "extra_trees"}:
        raise ValueError("artifact model payload mismatch")
    model = payload["model"]
    model_type = payload["model_type"]
    if (model_type == "majority_baseline") != (model["kind"] == "majority") or (
            model_type != "majority_baseline" and model_type != model["kind"]):
        raise ValueError("artifact model type/payload mismatch")
    if model.get("classes") != classes:
        raise ValueError("artifact model classes mismatch")
    provenance = payload.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("artifact provenance is incomplete")
    digest = provenance.get("dataset_sha256")
    if (not provenance.get("dataset_ids") or not isinstance(digest, str) or
            len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest) or
            not isinstance(provenance.get("dataset_sources"), Mapping) or
            set(provenance["dataset_ids"]) != set(provenance["dataset_sources"]) or
            not provenance.get("sensor_positions") or not provenance.get("sample_rates_hz")):
        raise ValueError("artifact provenance is incomplete")
    for rate in provenance["sample_rates_hz"]:
        if rate is not None and (isinstance(rate, bool) or not isinstance(rate, (int, float)) or
                                 not math.isfinite(rate) or rate <= 0):
            raise ValueError("artifact sample-rate provenance is invalid")
    if model["kind"] == "logistic_regression":
        expected_coefficient_rows = 1 if len(model["classes"]) == 2 else len(model["classes"])
        if (len(model["classes"]) < 2 or
                len(model.get("coef", [])) != expected_coefficient_rows):
            raise ValueError("artifact logistic coefficient shape mismatch")
        if any(len(coef) != feature_count or any(isinstance(value, bool) or
                   not isinstance(value, (int, float)) or not math.isfinite(value) for value in coef)
               for coef in model.get("coef", [])):
            raise ValueError("artifact logistic coefficient shape mismatch")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
               for value in model.get("intercept", [])) or len(model.get("intercept", [])) != len(model.get("coef", [])):
            raise ValueError("artifact logistic intercept shape mismatch")
    if model["kind"] == "majority" and (model.get("label") not in model["classes"] or
                                         len(model.get("scores", [])) != len(model["classes"])):
        raise ValueError("artifact majority model mismatch")
    if model["kind"] == "majority" and (any(isinstance(value, bool) or not isinstance(value, (int, float)) or
            not math.isfinite(value) or value < 0 for value in model["scores"]) or
            not math.isclose(sum(model["scores"]), 1.0, rel_tol=1e-9, abs_tol=1e-9)):
        raise ValueError("artifact majority scores are invalid")
    tree_models = ([model] if model["kind"] == "decision_tree" else
                   model.get("trees", []) if model["kind"] == "extra_trees" else [])
    if model["kind"] == "extra_trees" and not tree_models:
        raise ValueError("artifact extra trees model is empty")
    for tree in tree_models:
        if not isinstance(tree, Mapping) or len(tree.get("classes", [])) != len(classes):
            raise ValueError("artifact tree classes mismatch")
        arrays = [tree.get(key) for key in ("children_left", "children_right", "feature", "threshold", "values")]
        if any(not isinstance(array, list) for array in arrays) or not arrays[0]:
            raise ValueError("artifact tree structure is invalid")
        node_count = len(arrays[0])
        if any(len(array) != node_count for array in arrays):
            raise ValueError("artifact tree array lengths mismatch")
        if any(not isinstance(values, list) or len(values) != len(classes)
               for values in tree["values"]):
            raise ValueError("artifact tree class dimensions mismatch")
        parents = [0] * node_count
        for left, right, feature, threshold, values in zip(*arrays):
            if any(isinstance(child, bool) or not isinstance(child, int) or child < -1 or child >= node_count
                   for child in (left, right)):
                raise ValueError("artifact tree child index is invalid")
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                   for value in values) or any(value < 0 for value in values):
                raise ValueError("artifact tree values are invalid")
            if left != right and (isinstance(feature, bool) or not isinstance(feature, int) or
                                  feature < 0 or feature >= feature_count or
                                  isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or
                                  not math.isfinite(threshold)):
                raise ValueError("artifact tree split is invalid")
            if left == right and left != -1:
                raise ValueError("artifact tree leaf must use -1 child indices")
            if left != right:
                if left < 0 or right < 0:
                    raise ValueError("artifact tree split must have two children")
                parents[left] += 1
                parents[right] += 1
        if parents[0] != 0 or any(count != 1 for count in parents[1:]):
            raise ValueError("artifact tree must have one root and no shared or parentless nodes")
        visited: set[int] = set()
        stack = [0]
        while stack:
            node = stack.pop()
            if node in visited:
                raise ValueError("artifact tree contains a cycle")
            visited.add(node)
            left, right = tree["children_left"][node], tree["children_right"][node]
            if left != right:
                stack.extend((right, left))
        if len(visited) != node_count:
            raise ValueError("artifact tree contains unreachable nodes")
    preprocessing = payload.get("preprocessing")
    if not isinstance(preprocessing, Mapping):
        raise ValueError("artifact preprocessing is invalid")
    expected_preprocessing = "standard_scaler" if model_type == "logistic_regression" else "identity"
    if preprocessing.get("kind") != expected_preprocessing:
        raise ValueError("artifact preprocessing kind mismatch")
    if any(len(preprocessing.get(key, [])) != feature_count for key in ("mean", "scale")):
        raise ValueError("artifact preprocessing shape mismatch")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
           for value in preprocessing["mean"] + preprocessing["scale"]):
        raise ValueError("artifact preprocessing contains non-finite values")
    if any(value <= 0 for value in preprocessing["scale"]):
        raise ValueError("artifact preprocessing scale must be positive")


def load_artifact(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("artifact must be a JSON object")
    _validate_artifact(payload)
    return payload


def infer(payload: Mapping[str, Any], features: Mapping[str, float], *, sample_rate_hz: float | None,
          sensor_position: str, timestamp_s: float | None = None,
          context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    _validate_artifact(payload)
    if (not isinstance(sensor_position, str) or not sensor_position or
            (sample_rate_hz is not None and (isinstance(sample_rate_hz, bool) or
             not isinstance(sample_rate_hz, (int, float)) or not math.isfinite(sample_rate_hz) or sample_rate_hz <= 0)) or
            sample_rate_hz not in payload["provenance"]["sample_rates_hz"]):
        raise ValueError("sample_rate_hz is incompatible with training provenance")
    if sensor_position not in payload["provenance"]["sensor_positions"]:
        raise ValueError("sensor_position is incompatible with training provenance")
    prediction, score = _predict_payload(payload, features)
    if timestamp_s is not None and (isinstance(timestamp_s, bool) or
            not isinstance(timestamp_s, (int, float)) or not math.isfinite(timestamp_s)):
        raise ValueError("timestamp_s must be finite")
    if context is not None and not isinstance(context, Mapping):
        raise ValueError("context must be an object")
    return {"predicted_behavior": prediction, "model_score": score,
            "confidence_semantics": payload["confidence_semantics"],
            "model_version": payload["model_version"], "timestamp_s": timestamp_s,
            "context": dict(context or {}), "dataset_provenance": payload["provenance"],
            "evidence_status": ",".join(payload["provenance"]["evidence_statuses"]),
            "evidence_interpretation": payload["evidence_interpretation"]}


def create_synthetic_fixture(seed: int = 23, animals: int = 12, windows_per_behavior: int = 8) -> list[BehaviorWindow]:
    """Make explicitly synthetic window summaries for software/pipeline checks."""
    import numpy as np

    if animals < 5 or windows_per_behavior < 1:
        raise ValueError("fixture requires at least five animals and one window per behavior")
    rng = np.random.default_rng(seed)
    centers = {"REST": (1.0, 0.025, 1.001), "WALK": (1.12, 0.18, 1.135), "GRAZE": (1.04, 0.075, 1.043)}
    rows = []
    for animal_num in range(animals):
        animal = f"sim-animal-{animal_num:03d}"
        animal_shift = rng.normal(0.0, (0.008, 0.006, 0.009))
        for label, center in centers.items():
            for window in range(windows_per_behavior):
                vals = np.asarray(center) + animal_shift + rng.normal(0.0, (0.004, 0.004, 0.004))
                rows.append(BehaviorWindow(
                    window_id=f"{animal}-session-0-{label}-{window:03d}", animal_id=animal,
                    session_id=f"{animal}-session-0", label=label,
                    features={name: float(value) for name, value in zip(FEATURE_NAMES, vals)},
                    dataset_id="riose-behavior-synthetic-fixture-v1",
                    dataset_source="seeded fixture generator in the RIOSE repository",
                    dataset_license="UNSPECIFIED: repository has no license declaration",
                    sensor_position="UNKNOWN_SYNTHETIC", sample_rate_hz=None,
                    evidence_status="SIMULATED"))
    return rows


def read_windows(path: str | Path) -> list[BehaviorWindow]:
    """Read JSON rows; dataset columns and labels remain distinct from feature vectors."""
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("input JSON must be a list of window objects")
    result = []
    for row in rows:
        if not isinstance(row, dict) or "features" not in row:
            raise ValueError("each window must be an object with a features object")
        result.append(BehaviorWindow(**row))
    _validate_windows(result)
    return result


def write_fixture(path: str | Path, *, seed: int = 23, animals: int = 12,
                  windows_per_behavior: int = 4) -> None:
    rows = create_synthetic_fixture(seed=seed, animals=animals,
                                    windows_per_behavior=windows_per_behavior)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps([asdict(row) for row in rows], indent=2, allow_nan=False) + "\n",
                          encoding="utf-8")
