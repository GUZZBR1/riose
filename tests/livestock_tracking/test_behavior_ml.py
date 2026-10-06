from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import numpy as np
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.tree import DecisionTreeClassifier

from riose.products.livestock_tracking.behavior_ml import (
    FEATURE_NAMES, BehaviorWindow, create_synthetic_fixture, infer, load_artifact,
    run_training, save_artifact, split_by_animal,
)
from riose.products.livestock_tracking.behavior_ml.pipeline import (
    ACTBECALF_MODEL_VERSION, _majority_label, _model_scores, _portable_model, _validate_artifact,
)


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    windows = create_synthetic_fixture(seed=23, animals=12, windows_per_behavior=4)
    payload, report = run_training(windows, seed=23)
    path = tmp_path_factory.mktemp("behavior") / "model.json"
    save_artifact(payload, path)
    return windows, payload, report, path


def test_animal_and_session_are_disjoint_across_all_splits():
    groups = split_by_animal(create_synthetic_fixture(), seed=23)
    animal_groups = {name: {row.animal_id for row in rows} for name, rows in groups.items()}
    session_groups = {name: {row.session_id for row in rows} for name, rows in groups.items()}
    assert animal_groups["train"].isdisjoint(animal_groups["validation"] | animal_groups["test"])
    assert animal_groups["validation"].isdisjoint(animal_groups["test"])
    assert session_groups["train"].isdisjoint(session_groups["validation"] | session_groups["test"])
    assert session_groups["validation"].isdisjoint(session_groups["test"])


def test_duplicate_window_ids_are_rejected():
    windows = create_synthetic_fixture()
    with pytest.raises(ValueError, match="duplicate window_id"):
        split_by_animal(windows + [windows[0]])


def test_session_cannot_be_reassigned_to_another_animal():
    windows = create_synthetic_fixture()
    conflicting = copy.copy(windows[-1])
    object.__setattr__(conflicting, "session_id", windows[0].session_id)
    with pytest.raises(ValueError, match="maps to multiple animals"):
        split_by_animal([*windows[:-1], conflicting])


def test_dataset_id_cannot_hide_conflicting_provenance():
    windows = create_synthetic_fixture()
    conflicting = copy.copy(windows[-1])
    object.__setattr__(conflicting, "dataset_source", "unrecorded alternative source")
    with pytest.raises(ValueError, match="conflicting source/license provenance"):
        split_by_animal([*windows[:-1], conflicting])


def test_unknown_evidence_status_is_rejected():
    windows = create_synthetic_fixture()
    invalid = copy.copy(windows[0])
    object.__setattr__(invalid, "evidence_status", "FIELD_VALIDATED_BY_MAGIC")
    with pytest.raises(ValueError, match="unknown evidence status"):
        split_by_animal([invalid, *windows[1:]])


@pytest.mark.parametrize("features", [
    {"accel_mean_g": 1.0, "accel_std_g": 0.1},
    {"accel_mean_g": 1.0, "accel_std_g": 0.1, "accel_rms_g": 1.01, "animal_id": "a"},
    {"accel_std_g": 0.1, "accel_mean_g": 1.0, "accel_rms_g": 1.01},
])
def test_missing_extra_or_reordered_features_fail(trained, features):
    _, artifact, _, _ = trained
    with pytest.raises(ValueError, match="features must have exactly this order"):
        infer(artifact, features, sample_rate_hz=None, sensor_position="UNKNOWN_SYNTHETIC")


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_features_fail(trained, bad_value):
    _, artifact, _, _ = trained
    features = dict(zip(FEATURE_NAMES, [1.0, 0.1, 1.01]))
    features[FEATURE_NAMES[0]] = bad_value
    with pytest.raises(ValueError, match="finite number"):
        infer(artifact, features, sample_rate_hz=None, sensor_position="UNKNOWN_SYNTHETIC")


def test_unknown_labels_empty_data_and_bad_sample_rate_fail():
    windows = create_synthetic_fixture()
    bad = copy.copy(windows[0])
    object.__setattr__(bad, "label", "SICK")
    with pytest.raises(ValueError, match="unknown or unsupported"):
        split_by_animal([bad, *windows[1:]])
    with pytest.raises(ValueError, match="empty"):
        run_training([])
    bad_rate = copy.copy(windows[0])
    object.__setattr__(bad_rate, "sample_rate_hz", 0.0)
    with pytest.raises(ValueError, match="sample_rate_hz"):
        split_by_animal([bad_rate, *windows[1:]])


def test_candidate_comparison_metrics_and_synthetic_evidence_are_explicit(trained):
    windows, artifact, report, _ = trained
    assert artifact["provenance"]["evidence_statuses"] == ["SIMULATED"]
    assert artifact["provenance"]["sensor_positions"] == ["UNKNOWN_SYNTHETIC"]
    assert artifact["evaluation"]["holdout"]["test_animals_used_for_selection"] is False
    assert {row["model"] for row in artifact["evaluation"]["validation_candidates"]} == {
        "majority_baseline", "logistic_regression", "decision_tree", "extra_trees"
    }
    holdout_animals = set(artifact["split"]["test"]["animals"])
    assert holdout_animals.isdisjoint(artifact["split"]["train"]["animals"])
    metrics = artifact["evaluation"]["holdout"]
    assert set(metrics["per_class"]) == set(artifact["classes"])
    assert len(metrics["confusion_matrix"]) == len(artifact["classes"])
    assert all(len(row) == len(artifact["classes"]) for row in metrics["confusion_matrix"])
    assert set(metrics["per_animal"]) == holdout_animals
    assert set(metrics["per_dataset"]) == {"riose-behavior-synthetic-fixture-v1"}
    assert "macro_f1" in metrics["majority_baseline_metrics"]
    assert report["selected_model"] in {"logistic_regression", "decision_tree", "extra_trees", "majority_baseline"}
    assert len(windows) > 0


def test_dataset_name_alone_does_not_promote_source_data_to_measured():
    windows = create_synthetic_fixture(seed=23, animals=8, windows_per_behavior=2)
    actbecalf = []
    for row in windows:
        copied = copy.copy(row)
        object.__setattr__(copied, "dataset_id", "actbecalf")
        object.__setattr__(copied, "label", f"ACTBECALF.{row.label.lower()}")
        object.__setattr__(copied, "source_label", row.label)
        actbecalf.append(copied)
    artifact, _ = run_training(actbecalf, seed=23)
    assert artifact["evidence_interpretation"]["source_data_status"] == "NOT_ASSERTED"


@pytest.mark.parametrize("metadata_name", ["segId", "source_segment_id", "source_row_start", "filename"])
def test_segment_and_source_location_metadata_cannot_be_features(metadata_name):
    windows = create_synthetic_fixture(seed=23, animals=8, windows_per_behavior=2)
    changed = []
    for row in windows:
        copied = copy.copy(row)
        object.__setattr__(copied, "dataset_id", "actbecalf")
        object.__setattr__(copied, "label", f"ACTBECALF.{row.label.lower()}")
        object.__setattr__(copied, "source_label", row.label)
        object.__setattr__(copied, "features", {metadata_name: 1.0, "signal": 2.0})
        changed.append(copied)
    with pytest.raises(ValueError, match="metadata cannot be features"):
        split_by_animal(changed)


def test_missing_holdout_class_is_reported_with_zero_support():
    windows = create_synthetic_fixture(seed=11, windows_per_behavior=1)
    test_animals = {row.animal_id for row in split_by_animal(windows, seed=23)["test"]}
    reduced = [row for row in windows if not (row.animal_id in test_animals and row.label == "WALK")]
    artifact, _ = run_training(reduced, seed=23)
    walk_metrics = artifact["evaluation"]["holdout"]["per_class"]["WALK"]
    assert walk_metrics["support"] == 0.0
    assert walk_metrics["recall"] == 0.0


def test_imbalanced_fixture_keeps_per_class_support_and_macro_metrics():
    windows = create_synthetic_fixture(seed=14, windows_per_behavior=4)
    seen: dict[tuple[str, str], int] = {}
    imbalanced = []
    for row in windows:
        changed = copy.copy(row)
        key = (row.animal_id, row.label)
        index = seen.get(key, 0)
        seen[key] = index + 1
        if (row.label == "GRAZE" and index > 0) or (row.label == "WALK" and index > 1):
            object.__setattr__(changed, "label", "REST")
        imbalanced.append(changed)
    artifact, _ = run_training(imbalanced, seed=23)
    metrics = artifact["evaluation"]["holdout"]
    assert metrics["support"]["REST"] > metrics["support"]["GRAZE"] > 0
    assert metrics["support"]["REST"] > metrics["support"]["WALK"] > 0
    assert "macro_f1" in metrics
    assert len(metrics["per_class"]) == 3


@pytest.mark.parametrize("estimator", [
    DecisionTreeClassifier(max_depth=4, min_samples_leaf=2, random_state=23),
    ExtraTreesClassifier(n_estimators=8, max_depth=5, min_samples_leaf=2, random_state=23, n_jobs=1),
])
def test_tree_candidate_json_scores_match_sklearn(estimator):
    windows = create_synthetic_fixture(seed=23, animals=8, windows_per_behavior=2)
    matrix = np.asarray([[row.features[name] for name in FEATURE_NAMES] for row in windows])
    labels = [row.label for row in windows]
    estimator.fit(matrix, labels)
    portable = _portable_model(estimator, "extra_trees" if isinstance(estimator, ExtraTreesClassifier)
                               else "decision_tree")
    model_type = portable["kind"]
    artifact = {
        "schema_version": 1, "model_version": "behavior-baseline-v1",
        "feature_version": "movement-window-v1", "feature_order": list(FEATURE_NAMES),
        "model_type": model_type, "classes": portable["classes"], "model": portable,
        "provenance": {"dataset_ids": ["sim"], "dataset_sources": {"sim": {"source": "test", "license": "test"}},
                       "dataset_sha256": "a" * 64, "sensor_positions": ["UNKNOWN_SYNTHETIC"],
                       "sample_rates_hz": [None]},
        "preprocessing": {"kind": "identity", "mean": [0.0] * len(FEATURE_NAMES),
                          "scale": [1.0] * len(FEATURE_NAMES)},
    }
    _validate_artifact(artifact)
    for row in matrix[:12]:
        scores = _model_scores(portable, row.tolist(), [0.0] * len(FEATURE_NAMES),
                               [1.0] * len(FEATURE_NAMES))
        assert np.allclose(scores, estimator.predict_proba([row])[0], atol=1e-12)


def test_artifact_round_trip_inference_is_deterministic_and_provenance_bound(trained, tmp_path):
    windows, artifact, _, path = trained
    loaded = load_artifact(path)
    features = windows[0].features
    context = {"session_id": windows[0].session_id}
    original = infer(artifact, features, sample_rate_hz=None,
                     sensor_position="UNKNOWN_SYNTHETIC", timestamp_s=12.0, context=context)
    restored = infer(loaded, features, sample_rate_hz=None,
                     sensor_position="UNKNOWN_SYNTHETIC", timestamp_s=12.0, context=context)
    assert restored == original
    assert restored["model_score"] >= 0.0
    assert "not a calibrated probability" in restored["confidence_semantics"]
    with pytest.raises(ValueError, match="sample_rate_hz is incompatible"):
        infer(loaded, features, sample_rate_hz=25.0, sensor_position="UNKNOWN_SYNTHETIC")
    with pytest.raises(ValueError, match="sensor_position is incompatible"):
        infer(loaded, features, sample_rate_hz=None, sensor_position="neck")
    mismatch = tmp_path / "mismatch.json"
    artifact["feature_order"] = list(reversed(FEATURE_NAMES))
    save_artifact(artifact, mismatch)
    with pytest.raises(ValueError, match="feature contract mismatch"):
        load_artifact(mismatch)


def test_loaded_json_inference_does_not_import_numpy_or_sklearn(trained):
    _, _, _, artifact_path = trained
    root = Path(__file__).resolve().parents[2]
    script = """
import builtins, json
real_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'numpy', 'sklearn'}:
        raise AssertionError('offline inference imported a training dependency')
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded
from riose.products.livestock_tracking.behavior_ml import load_artifact, infer
artifact = load_artifact(%r)
features = {'accel_mean_g': 1.0, 'accel_std_g': 0.08, 'accel_rms_g': 1.01}
result = infer(artifact, features, sample_rate_hz=None, sensor_position='UNKNOWN_SYNTHETIC')
assert result['evidence_status'] == 'SIMULATED'
""" % str(artifact_path)
    subprocess.run([sys.executable, "-c", script], cwd=root, check=True,
                   env={**os.environ, "PYTHONPATH": str(root / "src")})


def test_malformed_cyclic_tree_artifact_is_rejected(trained):
    import copy

    _, payload, _, _ = trained
    malformed = copy.deepcopy(payload)
    malformed["model_version"] = ACTBECALF_MODEL_VERSION
    malformed["model_type"] = "decision_tree"
    malformed["model"] = {
        "kind": "decision_tree", "classes": malformed["classes"],
        "children_left": [0, -1], "children_right": [1, -1],
        "feature": [0, -2], "threshold": [0.0, -2.0],
        "values": [[1.0] * len(malformed["classes"]), [1.0] * len(malformed["classes"])],
    }
    malformed["preprocessing"] = {
        "kind": "identity", "mean": [0.0] * len(malformed["feature_order"]),
        "scale": [1.0] * len(malformed["feature_order"]),
    }
    with pytest.raises(ValueError, match="tree"):
        _validate_artifact(malformed)


def test_multiclass_logistic_artifact_requires_one_row_per_class(trained):
    import copy

    _, payload, _, _ = trained
    malformed = copy.deepcopy(payload)
    malformed["model_version"] = ACTBECALF_MODEL_VERSION
    malformed["model"]["coef"] = malformed["model"]["coef"][:1]
    malformed["model"]["intercept"] = malformed["model"]["intercept"][:1]
    with pytest.raises(ValueError, match="logistic coefficient shape"):
        _validate_artifact(malformed)


def test_test_only_class_stays_in_evaluation_not_prediction_artifact(monkeypatch, tmp_path):
    import riose.products.livestock_tracking.behavior_ml.pipeline as pipeline

    features = {"accel_mean_g": 0.0, "accel_std_g": 0.1, "accel_rms_g": 0.2}
    groups = {"train": [], "validation": [], "test": []}
    for split, animals in (("train", range(6)), ("validation", range(6, 8)),
                           ("test", range(8, 10))):
        for animal in animals:
            for label in ("ACTBECALF.lying", "ACTBECALF.walking"):
                groups[split].append(pipeline.BehaviorWindow(
                    window_id=f"{animal}-{label}", animal_id=f"calf-{animal}",
                    session_id=f"calf-{animal}-session", label=label,
                    features=features, dataset_id="actbecalf", dataset_source="source",
                    dataset_license="UNVERIFIED", sensor_position="NECK",
                    sample_rate_hz=25.0, evidence_status="EXPERIMENTAL", source_label=label,
                ))
    groups["test"].append(pipeline.BehaviorWindow(
        window_id="test-only", animal_id="calf-9", session_id="calf-9-session",
        label="ACTBECALF.unseen", features=features, dataset_id="actbecalf",
        dataset_source="source", dataset_license="UNVERIFIED", sensor_position="NECK",
        sample_rate_hz=25.0, evidence_status="EXPERIMENTAL", source_label="unseen",
    ))
    all_rows = [row for split_rows in groups.values() for row in split_rows]
    monkeypatch.setattr(pipeline, "split_by_animal", lambda _rows, seed: groups)

    payload, _ = pipeline.run_training(all_rows, seed=23)
    path = tmp_path / "artifact.json"
    pipeline.save_artifact(payload, path)
    loaded = pipeline.load_artifact(path)
    assert "ACTBECALF.unseen" not in loaded["classes"]
    assert "ACTBECALF.unseen" in payload["evaluation"]["holdout"]["per_dataset"]["actbecalf"]["classes"]


def test_majority_ties_match_the_portable_model_argmax_order():
    assert _majority_label(["A", "B"], ["A", "B"]) == "A"


def test_repeated_training_with_same_seed_is_reproducible():
    windows = create_synthetic_fixture(seed=3)
    first, report1 = run_training(windows, seed=9)
    second, report2 = run_training(windows, seed=9)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert report1 == report2


def test_holdout_values_cannot_change_selected_model_or_preprocessing():
    windows = create_synthetic_fixture(seed=5)
    baseline, _ = run_training(windows, seed=23)
    holdout_ids = set(baseline["split"]["test"]["animals"])
    attacked = []
    for row in windows:
        changed = copy.copy(row)
        if row.animal_id in holdout_ids:
            changed_features = dict(row.features)
            changed_features[FEATURE_NAMES[0]] += 10_000.0
            object.__setattr__(changed, "features", changed_features)
        attacked.append(changed)
    attack_result, _ = run_training(attacked, seed=23)
    assert attack_result["model"] == baseline["model"]
    assert attack_result["preprocessing"] == baseline["preprocessing"]
    assert attack_result["split"]["train"] == baseline["split"]["train"]


def test_metadata_and_labels_cannot_enter_the_feature_vector():
    windows = create_synthetic_fixture()
    changed = copy.copy(windows[0])
    object.__setattr__(changed, "features", {**changed.features, "animal_id": 1.0})
    with pytest.raises(ValueError, match="features must have exactly this order"):
        run_training([changed, *windows[1:]])


def test_single_class_confined_to_one_animal_is_rejected_if_missing_from_training():
    windows = create_synthetic_fixture(seed=2, animals=12, windows_per_behavior=1)
    # Confine GRAZE to an animal assigned outside train; do not move its windows.
    animal = split_by_animal(windows, seed=23)["test"][0].animal_id
    modified = [copy.copy(row) for row in windows]
    for row in modified:
        object.__setattr__(row, "label", "GRAZE" if row.animal_id == animal else "REST")
    with pytest.raises(ValueError, match="every behavior class must appear in training animals"):
        run_training(modified, seed=23)
