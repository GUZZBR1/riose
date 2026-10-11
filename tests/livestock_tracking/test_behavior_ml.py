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
    KNOWN_BEHAVIORS, _majority_label, _model_scores, _portable_model, _validate_artifact,
)
from riose.products.livestock_tracking.behavior_ml.feature_schema import (
    SIGNAL_FEATURE_ORDER, SIGNAL_FEATURE_SCHEMA,
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
    {"accel_mean_native": 1.0, "accel_std_native": 0.1},
    {"accel_mean_native": 1.0, "accel_std_native": 0.1, "accel_rms_native": 1.01, "animal_id": "a"},
    {"accel_std_native": 0.1, "accel_mean_native": 1.0, "accel_rms_native": 1.01},
])
def test_missing_extra_or_reordered_features_fail(trained, features):
    _, artifact, _, _ = trained
    with pytest.raises(ValueError, match="features must have exactly this order"):
        infer(artifact, features, feature_schema=artifact["feature_schema"],
              sample_rate_hz=None, sensor_position="UNKNOWN_SYNTHETIC")


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_features_fail(trained, bad_value):
    _, artifact, _, _ = trained
    features = dict(zip(FEATURE_NAMES, [1.0, 0.1, 1.01]))
    features[FEATURE_NAMES[0]] = bad_value
    with pytest.raises(ValueError, match="finite number"):
        infer(artifact, features, feature_schema=artifact["feature_schema"],
              sample_rate_hz=None, sensor_position="UNKNOWN_SYNTHETIC")


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
    assert "target-leakage absence are not verified" in artifact["evidence_interpretation"]["feature_values"]
    assert artifact["evaluation"]["holdout"]["test_animals_used_for_selection"] is False
    assert {row["model"] for row in artifact["evaluation"]["validation_candidates"]} == {
        "majority_baseline", "logistic_regression", "decision_tree", "extra_trees"
    }
    assert artifact["split"]["test"]["animal_count"] == 2
    assert artifact["split"]["train"]["animal_count"] == 8
    metrics = artifact["evaluation"]["holdout"]
    assert set(metrics["per_class"]) == set(artifact["classes"])
    assert len(metrics["confusion_matrix"]) == len(artifact["classes"])
    assert all(len(row) == len(artifact["classes"]) for row in metrics["confusion_matrix"])
    assert metrics["per_animal_summary"]["animal_count"] == 2
    assert set(metrics["per_dataset"]) == {"riose-behavior-synthetic-fixture-v1"}
    assert "macro_f1" in metrics["majority_baseline_metrics"]
    assert report["selected_model"] in {"logistic_regression", "decision_tree", "extra_trees", "majority_baseline"}
    assert len(windows) > 0


@pytest.mark.parametrize("metadata_name", [
    "segId", "source_segment_id", "source_row_start", "filename", "ground_truth", "raw_label",
])
def test_segment_and_source_location_metadata_cannot_be_features(metadata_name):
    windows = create_synthetic_fixture(seed=23, animals=8, windows_per_behavior=2)
    changed = []
    for row in windows:
        copied = copy.copy(row)
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


def test_unregistered_feature_schema_is_rejected():
    windows = create_synthetic_fixture(seed=19, animals=8, windows_per_behavior=2)
    changed = [copy.copy(row) for row in windows]
    custom = dict(changed[-1].feature_schema)
    custom["schema_id"] = "caller.custom.unverified"
    object.__setattr__(changed[-1], "feature_schema", custom)
    with pytest.raises(ValueError, match="unregistered feature schema"):
        run_training(changed, seed=23)


def test_label_encoded_input_cannot_be_registered_by_the_caller():
    windows = create_synthetic_fixture(seed=19, animals=8, windows_per_behavior=2)
    changed = [copy.copy(row) for row in windows]
    for row in changed:
        values = {**row.features, "label_encoded": float(KNOWN_BEHAVIORS.index(row.label))}
        schema = copy.deepcopy(row.feature_schema)
        schema["units"]["label_encoded"] = "dimensionless"
        schema["definitions"]["label_encoded"] = "caller-provided behavior label encoding"
        object.__setattr__(row, "features", values)
        object.__setattr__(row, "feature_schema", schema)
    with pytest.raises(ValueError, match="unregistered feature schema"):
        run_training(changed, seed=23)


def test_registered_signal_schema_matches_the_upstream_extractor_contract():
    from riose.products.ear_tag.signal.engine import FEATURE_NAMES as ENGINE_FEATURE_NAMES
    from riose.products.ear_tag.signal.engine import PIPELINE_VERSION
    from riose.products.livestock_tracking.behavior_ml.feature_schema import (
        SIGNAL_FEATURE_ORDER, SIGNAL_FEATURE_SCHEMA, validate_registered_feature_schema,
    )

    assert SIGNAL_FEATURE_ORDER == ENGINE_FEATURE_NAMES
    assert SIGNAL_FEATURE_SCHEMA["version"] == PIPELINE_VERSION
    assert validate_registered_feature_schema(SIGNAL_FEATURE_SCHEMA, ENGINE_FEATURE_NAMES) == SIGNAL_FEATURE_SCHEMA


def test_training_rejects_unregistered_feature_definitions_even_with_matching_names():
    windows = create_synthetic_fixture(seed=21, animals=8, windows_per_behavior=2)
    changed = [copy.copy(row) for row in windows]
    alternate = dict(changed[-1].feature_schema)
    alternate["definitions"] = {**alternate["definitions"],
                                "accel_mean_native": "mean of a different, incompatible sensor channel"}
    object.__setattr__(changed[-1], "feature_schema", alternate)
    with pytest.raises(ValueError, match="unregistered feature schema"):
        run_training(changed, seed=23)


def test_model_artifact_does_not_expose_raw_animal_identifiers(trained):
    windows, artifact, _, _ = trained
    serialized = json.dumps(artifact, sort_keys=True)
    assert all(row.animal_id not in serialized for row in windows)
    assert "per_animal" not in artifact["evaluation"]["holdout"]


def test_training_rejects_mixed_acquisition_conditions():
    windows = create_synthetic_fixture(seed=19, animals=8, windows_per_behavior=2)
    changed = [copy.copy(row) for row in windows]
    object.__setattr__(changed[-1], "sensor_position", "NECK")
    with pytest.raises(ValueError, match="one sensor position and sample rate"):
        run_training(changed, seed=23)


def test_inference_status_describes_experimental_prediction_not_source_evidence():
    windows = create_synthetic_fixture(seed=33, animals=8, windows_per_behavior=2)
    changed = [copy.copy(row) for row in windows]
    for index, row in enumerate(changed):
        object.__setattr__(row, "dataset_id", "external-evidence-mix")
        object.__setattr__(row, "evidence_status", "VALIDATED" if index % 2 else "SIMULATED")
    artifact, _ = run_training(changed, seed=23)

    result = infer(artifact, changed[0].features, feature_schema=artifact["feature_schema"],
                   sample_rate_hz=None, sensor_position="UNKNOWN_SYNTHETIC")

    assert artifact["provenance"]["evidence_statuses"] == ["SIMULATED", "VALIDATED"]
    assert result["evidence_status"] == "EXPERIMENTAL"
    assert result["dataset_provenance"]["evidence_statuses"] == ["SIMULATED", "VALIDATED"]


def _signal_window_config(**overrides):
    config = {
        "window_duration_s": 4.0,
        "window_samples": 100,
        "overlap_fraction": 0.5,
        "stride_samples": 50,
        "max_jitter_fraction": 0.15,
        "source_sample_rate_hz": 25.0,
        "resampling_method": "none",
        "resampling_up": 1,
        "resampling_down": 1,
        "resampling_jitter_interpolation": False,
        "resampling_filter": "none",
    }
    config.update(overrides)
    return config


def _signal_schema_windows():
    windows = create_synthetic_fixture(seed=41, animals=8, windows_per_behavior=2)
    result = []
    for row in windows:
        changed = copy.copy(row)
        object.__setattr__(changed, "dataset_id", "external-signal-window-test")
        object.__setattr__(changed, "sample_rate_hz", 25.0)
        object.__setattr__(changed, "sensor_position", "EAR")
        object.__setattr__(changed, "feature_version", SIGNAL_FEATURE_SCHEMA["version"])
        object.__setattr__(changed, "feature_schema", SIGNAL_FEATURE_SCHEMA)
        object.__setattr__(changed, "window_config", _signal_window_config())
        object.__setattr__(changed, "features", {
            name: float(index + 1) for index, name in enumerate(SIGNAL_FEATURE_ORDER)
        })
        result.append(changed)
    return result


def test_signal_feature_model_is_bound_to_window_configuration():
    windows = _signal_schema_windows()
    artifact, _ = run_training(windows, seed=23)
    result = infer(artifact, windows[0].features, feature_schema=SIGNAL_FEATURE_SCHEMA,
                   sample_rate_hz=25.0, sensor_position="EAR",
                   window_config=_signal_window_config())

    assert result["evidence_status"] == "EXPERIMENTAL"
    with pytest.raises(ValueError, match="window_config is incompatible"):
        infer(artifact, windows[0].features, feature_schema=SIGNAL_FEATURE_SCHEMA,
              sample_rate_hz=25.0, sensor_position="EAR",
              window_config=_signal_window_config(window_duration_s=2.0, window_samples=50,
                                                  stride_samples=25))


def test_training_rejects_mixed_signal_window_configurations():
    windows = _signal_schema_windows()
    object.__setattr__(windows[-1], "window_config",
                       _signal_window_config(window_duration_s=2.0, window_samples=50,
                                             stride_samples=25))
    with pytest.raises(ValueError, match="one window extraction configuration"):
        run_training(windows, seed=23)


def test_training_skips_logistic_regression_for_one_class_animal_partition():
    windows = create_synthetic_fixture(seed=43, animals=12, windows_per_behavior=1)
    groups = split_by_animal(windows, seed=23)
    train_animals = {row.animal_id for row in groups["train"]}
    validation_animals = {row.animal_id for row in groups["validation"]}
    changed = [copy.copy(row) for row in windows]
    for row in changed:
        object.__setattr__(row, "dataset_id", "external-one-class-train")
        label = ("REST" if row.animal_id in train_animals else
                 "WALK" if row.animal_id in validation_animals else "GRAZE")
        object.__setattr__(row, "label", label)

    artifact, _ = run_training(changed, seed=23)

    logistic = next(row for row in artifact["evaluation"]["validation_candidates"]
                   if row["model"] == "logistic_regression")
    assert logistic == {"model": "logistic_regression", "status": "skipped",
                        "reason": "requires at least two training classes"}


def test_majority_winner_is_refit_on_train_and_validation(monkeypatch):
    import sklearn.ensemble
    import sklearn.tree

    class AlwaysWrongEstimator:
        def __init__(self, *args, **kwargs):
            pass

        def fit(self, features, labels):
            self.classes_ = np.unique(labels)
            return self

        def predict(self, features):
            return np.asarray(["UNSEEN_PREDICTION"] * len(features))

    monkeypatch.setattr(sklearn.tree, "DecisionTreeClassifier", AlwaysWrongEstimator)
    monkeypatch.setattr(sklearn.ensemble, "ExtraTreesClassifier", AlwaysWrongEstimator)
    windows = create_synthetic_fixture(seed=47, animals=12, windows_per_behavior=1)
    groups = split_by_animal(windows, seed=23)
    train_animals = {row.animal_id for row in groups["train"]}
    validation_animals = {row.animal_id for row in groups["validation"]}
    changed = [copy.copy(row) for row in windows]
    for row in changed:
        object.__setattr__(row, "dataset_id", "external-majority-refit")
        if row.animal_id in train_animals:
            label = "REST"
        elif row.animal_id in validation_animals:
            label = "WALK" if row.label == "WALK" else "REST"
        else:
            label = "GRAZE"
        object.__setattr__(row, "label", label)

    artifact, _ = run_training(changed, seed=23)
    train_and_validation_animals = train_animals | validation_animals
    train_and_validation = [row for row in changed if row.animal_id in train_and_validation_animals]
    final_counts = {label: sum(row.label == label for row in train_and_validation)
                    for label in sorted({row.label for row in train_and_validation})}

    assert artifact["model_type"] == "majority_baseline"
    assert artifact["classes"] == sorted(final_counts)
    assert artifact["model"]["label"] == min(final_counts, key=lambda label: (-final_counts[label], label))
    assert artifact["model"]["scores"] == [
        final_counts[label] / len(train_and_validation) for label in artifact["classes"]
    ]


@pytest.mark.parametrize("metadata", [
    "confidence_semantics", "evidence_interpretation", "evidence_statuses",
])
def test_artifact_rejects_missing_metadata_consumed_by_inference(trained, metadata):
    _, artifact, _, _ = trained
    malformed = copy.deepcopy(artifact)
    if metadata == "evidence_statuses":
        del malformed["provenance"]["evidence_statuses"]
    else:
        del malformed[metadata]
    with pytest.raises(ValueError, match="inference metadata|evidence status provenance"):
        _validate_artifact(malformed)


def test_validation_candidate_scores_do_not_depend_on_test_only_labels():
    windows = create_synthetic_fixture(seed=29, animals=12, windows_per_behavior=2)
    split = split_by_animal(windows, seed=23)
    test_animals = {row.animal_id for row in split["test"]}
    external = [copy.copy(row) for row in windows]
    for row in external:
        object.__setattr__(row, "dataset_id", "external-test-dataset")
    altered = [copy.copy(row) for row in external]
    for row in altered:
        if row.animal_id in test_animals:
            object.__setattr__(row, "label", "TEST_ONLY_LABEL")
            object.__setattr__(row, "source_label", None)
    baseline, _ = run_training(external, seed=23)
    candidate, _ = run_training(altered, seed=23)
    assert candidate["evaluation"]["validation_candidates"] == baseline["evaluation"]["validation_candidates"]
    assert candidate["evaluation"]["selected_validation_macro_f1"] == baseline["evaluation"]["selected_validation_macro_f1"]
    assert candidate["provenance"]["window_digests"]["train_and_validation"] == baseline["provenance"]["window_digests"]["train_and_validation"]
    assert candidate["provenance"]["window_digests"]["holdout"] != baseline["provenance"]["window_digests"]["holdout"]


def test_external_provenance_is_reported_as_caller_attested_not_verified():
    windows = create_synthetic_fixture(seed=31, animals=8, windows_per_behavior=2)
    changed = [copy.copy(row) for row in windows]
    for row in changed:
        object.__setattr__(row, "dataset_id", "external-dataset")
        object.__setattr__(row, "source_file_sha256", "a" * 64)
        object.__setattr__(row, "source_provenance_attested", True)
    artifact, _ = run_training(changed, seed=23)
    assert artifact["evidence_interpretation"]["source_data_status"] == "CALLER_ATTESTED_EXTERNAL_PROVENANCE"


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
        "feature_schema": {
            "schema_id": "riose.synthetic.behavior-window", "version": "movement-window-v1",
            "extractor": "riose.synthetic.behavior-fixture-v1",
            "units": {name: "source_native" for name in FEATURE_NAMES},
            "definitions": {
                "accel_mean_native": "synthetic window mean acceleration on an uncalibrated source scale",
                "accel_std_native": "synthetic window acceleration standard deviation on an uncalibrated source scale",
                "accel_rms_native": "synthetic window root mean square acceleration on an uncalibrated source scale",
            },
        },
        "model_type": model_type, "classes": portable["classes"], "model": portable,
            "provenance": {"dataset_ids": ["sim"], "dataset_sources": {"sim": {"source": "test", "license": "test"}},
                           "window_digests": {name: "a" * 64 for name in
                                               ("train", "train_and_validation", "holdout", "full_evaluation_input")},
                           "sensor_positions": ["UNKNOWN_SYNTHETIC"],
                       "sample_rates_hz": [None], "window_config": None,
                       "evidence_statuses": ["SIMULATED"]},
        "preprocessing": {"kind": "identity", "mean": [0.0] * len(FEATURE_NAMES),
                          "scale": [1.0] * len(FEATURE_NAMES)},
        "confidence_semantics": "maximum model score; not a calibrated probability",
        "evidence_interpretation": {
            "result_status": "SIMULATED_SOFTWARE_PIPELINE_ONLY",
            "source_data_status": "NOT_ASSERTED",
            "sensor_position_transfer": "NOT_VALIDATED",
            "scientific_validation": "NOT_ASSESSED",
            "feature_values": "REGISTERED_SCHEMA_ONLY",
            "ear_tag_validation": False,
            "clinical_diagnosis": False,
        },
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
    original = infer(artifact, features, feature_schema=artifact["feature_schema"], sample_rate_hz=None,
                     sensor_position="UNKNOWN_SYNTHETIC", timestamp_s=12.0, context=context)
    restored = infer(loaded, features, feature_schema=loaded["feature_schema"], sample_rate_hz=None,
                     sensor_position="UNKNOWN_SYNTHETIC", timestamp_s=12.0, context=context)
    assert restored == original
    assert restored["model_score"] >= 0.0
    assert "not a calibrated probability" in restored["confidence_semantics"]
    with pytest.raises(ValueError, match="sample_rate_hz is incompatible"):
        infer(loaded, features, feature_schema=loaded["feature_schema"],
              sample_rate_hz=25.0, sensor_position="UNKNOWN_SYNTHETIC")
    with pytest.raises(ValueError, match="sensor_position is incompatible"):
        infer(loaded, features, feature_schema=loaded["feature_schema"],
              sample_rate_hz=None, sensor_position="neck")
    alternate_schema = copy.deepcopy(loaded["feature_schema"])
    alternate_schema["units"][FEATURE_NAMES[0]] = "g"
    with pytest.raises(ValueError, match="unregistered feature schema"):
        infer(loaded, features, feature_schema=alternate_schema,
              sample_rate_hz=None, sensor_position="UNKNOWN_SYNTHETIC")
    mismatch = tmp_path / "mismatch.json"
    malformed = copy.deepcopy(artifact)
    malformed["feature_order"] = list(reversed(FEATURE_NAMES))
    save_artifact(malformed, mismatch)
    with pytest.raises(ValueError, match="unregistered feature schema"):
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
features = {'accel_mean_native': 1.0, 'accel_std_native': 0.08, 'accel_rms_native': 1.01}
result = infer(artifact, features, feature_schema=artifact['feature_schema'],
               sample_rate_hz=None, sensor_position='UNKNOWN_SYNTHETIC')
assert result['evidence_status'] == 'EXPERIMENTAL'
""" % str(artifact_path)
    subprocess.run([sys.executable, "-c", script], cwd=root, check=True,
                   env={**os.environ, "PYTHONPATH": str(root / "src")})


def test_malformed_cyclic_tree_artifact_is_rejected(trained):
    import copy

    _, payload, _, _ = trained
    malformed = copy.deepcopy(payload)
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
    malformed["model"]["coef"] = malformed["model"]["coef"][:1]
    malformed["model"]["intercept"] = malformed["model"]["intercept"][:1]
    with pytest.raises(ValueError, match="logistic coefficient shape"):
        _validate_artifact(malformed)


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
    holdout_ids = {row.animal_id for row in split_by_animal(windows, seed=23)["test"]}
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
