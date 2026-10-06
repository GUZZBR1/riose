"""Offline end-to-end research replay for the official ActBeCalf export.

All generated results are explicitly external-data research artifacts. The
pipeline never downloads during replay and never maps neck results to an ear tag.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import time
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

from riose.evidence.bridge import EvidenceClass
from riose.products.ear_tag.movement_datasets.actbecalf import (
    DATASET_DOI, EXPECTED_COLUMNS, SOURCE_URL, adapt_actbecalf_csv,
)
from riose.products.ear_tag.movement_datasets.acquisition import (
    ACTBECALF_PUBLISHER_MD5, ACTBECALF_PUBLISHER_SIZE,
)
from riose.products.ear_tag.movement_datasets.contract import CanonicalSample
from riose.products.ear_tag.signal.engine import (
    PIPELINE_VERSION, SignalSample, SignalTrace, WindowConfig, extract_features,
)
from riose.products.livestock_tracking.behavior_ml.pipeline import (
    BehaviorWindow as MLWindow, _predict_payload, load_artifact, run_training,
    save_artifact,
)
from riose.products.livestock_tracking.behavior_ml.grouped_cv import evaluate_grouped_cv
from riose.products.livestock_tracking.domain.intelligence import (
    BehaviorPrediction, PredictionTimeBasis,
)
from riose.products.livestock_tracking.domain.contracts import EvidenceStatus
from riose.products.livestock_tracking.adapters.persistence.sqlite_store import Store

SEED = 23
SAMPLE_RATE_HZ = 25.0
WINDOW_SECONDS = 3.0
GAP_SECONDS = 0.0600001
DATASET_LICENSE = "UNVERIFIED_ZENODO_RIGHTS_FIELD_EMPTY"
TAXONOMY_VERSION = "actbecalf-source-labels-v1"


def _code_fingerprints() -> dict[str, str]:
    package_root = Path(__file__).resolve().parents[1]
    paths = {
        "src/riose/cli/movement_intelligence.py": Path(__file__).resolve(),
        "src/riose/products/ear_tag/signal/engine.py": package_root / "products/ear_tag/signal/engine.py",
        "src/riose/products/livestock_tracking/behavior_ml/pipeline.py": package_root / "products/livestock_tracking/behavior_ml/pipeline.py",
        "src/riose/products/livestock_tracking/behavior_ml/grouped_cv.py": package_root / "products/livestock_tracking/behavior_ml/grouped_cv.py",
        "src/riose/products/livestock_tracking/domain/intelligence.py": package_root / "products/livestock_tracking/domain/intelligence.py",
        "src/riose/products/livestock_tracking/adapters/persistence/sqlite_store.py": package_root / "products/livestock_tracking/adapters/persistence/sqlite_store.py",
    }
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _label_id(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", raw.casefold()).strip("_")[:70] or "label"
    suffix = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"ACTBECALF.{slug}_{suffix}"


def _check_file(path: Path) -> tuple[str, str]:
    md5, sha256, size = hashlib.md5(usedforsecurity=False), hashlib.sha256(), 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            md5.update(chunk)
            sha256.update(chunk)
    if size != ACTBECALF_PUBLISHER_SIZE or md5.hexdigest() != ACTBECALF_PUBLISHER_MD5:
        raise ValueError("ActBeCalf file does not match the official publisher size and MD5")
    return sha256.hexdigest(), md5.hexdigest()


def _extract(path: Path, source_sha256: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    current_key: tuple[str, str] | None = None
    current: list[CanonicalSample] = []
    run_number = 0
    occurrence_counts: Counter[tuple[str, str]] = Counter()
    all_animals: set[str] = set()
    all_labels: Counter[str] = Counter()
    first_time: dict[str, datetime] = {}
    last_time_by_animal: dict[str, datetime] = {}
    last_time_by_segment: dict[tuple[str, str], datetime] = {}
    backwards_by_animal: Counter[str] = Counter()
    segment_labels: dict[tuple[str, str], str] = {}
    sample_gaps = 0
    nonuniform_runs = 0
    invalid_rows = 0

    def flush() -> None:
        nonlocal current, run_number, nonuniform_runs
        if not current:
            return
        label = current[0].original_label
        if any(row.original_label != label for row in current):
            raise ValueError("one annotation segment contains multiple raw labels")
        # Use a source-relative monotonic coordinate; the dataset timezone is unknown.
        origin = datetime(1970, 1, 1)
        times = []
        for row in current:
            parsed = _parse_time(row.timestamp)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            times.append((parsed - origin).total_seconds())
        session = f"annotation-{current[0].source_segment_id}-occurrence-{occurrence_counts[current_key]}-run-{run_number}"
        samples = tuple(SignalSample(
            timestamp_s=t, x=row.x, y=row.y, z=row.z, animal_id=row.animal_id,
            session_id=session, sensor_position=row.sensor_position.value,
            unit=row.axis_unit.value, evidence_status="MEASURED_EXTERNAL_DATA",
        ) for row, t in zip(current, times, strict=True))
        if len(samples) >= round(WINDOW_SECONDS * SAMPLE_RATE_HZ):
            try:
                extracted = extract_features(SignalTrace(
                    samples=samples, sample_rate_hz=SAMPLE_RATE_HZ,
                    source_ref=f"{SOURCE_URL}#{current[0].source_segment_id}",
                ), WindowConfig(duration_s=WINDOW_SECONDS, overlap_fraction=0.0,
                                max_jitter_fraction=0.5))
            except ValueError as exc:
                # A gap, ordering anomaly, or clock mismatch invalidates this run.
                if "gap" not in str(exc).lower() and "timestamp" not in str(exc).lower():
                    raise
                nonuniform_runs += 1
                current = []
                run_number += 1
                return
            for feature in extracted:
                index = int(feature.provenance["window_index"])
                offset = index * round(WINDOW_SECONDS * SAMPLE_RATE_HZ)
                last = min(offset + round(WINDOW_SECONDS * SAMPLE_RATE_HZ), len(current)) - 1
                source_rows = [current[i].source_row for i in range(offset, last + 1)]
                window_id = hashlib.sha256(
                    f"{source_sha256}|{current[0].animal_id}|{session}|{index}".encode()
                ).hexdigest()
                windows.append({
                    "window_id": window_id,
                    "animal_id": current[0].animal_id,
                    "session_id": f"{current[0].animal_id}:{session}",
                    "source_segment_id": current[0].source_segment_id,
                    "source_row_start": min(source_rows), "source_row_end": max(source_rows),
                    "raw_label": label, "source_label": label,
                    "label": _label_id(label),
                    "features": feature.features,
                    "start_time": current[offset].timestamp,
                    "end_time": current[last].timestamp,
                    "start_relative_s": (times[offset] - (first_time[current[0].animal_id] - datetime(1970, 1, 1)).total_seconds()),
                    "end_relative_s": (times[last] - (first_time[current[0].animal_id] - datetime(1970, 1, 1)).total_seconds()),
                    "feature_version": f"{PIPELINE_VERSION}+unknown-axis-native-v1",
                })
        current = []
        run_number += 1

    # First pass gathers source-relative origins and data quality without assuming UTC.
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
            raise ValueError("unexpected ActBeCalf CSV schema in metadata pass")
        for source_row in reader:
            if None in source_row or any(value is None for value in source_row.values()):
                raise ValueError(f"malformed source row {reader.line_num}")
            animal_id, segment_id, label = (source_row[name] for name in ("calfId", "segId", "behaviour"))
            if not animal_id.strip() or not segment_id.strip() or not label.strip():
                raise ValueError(f"missing animal, segment or annotation at source row {reader.line_num}")
            all_animals.add(animal_id)
            all_labels[label] += 1
            parsed = _parse_time(source_row["dateTime"])
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            first_time[animal_id] = min(first_time.get(animal_id, parsed), parsed)
            last_time_by_animal[animal_id] = max(last_time_by_animal.get(animal_id, parsed), parsed)
            segment_key = (animal_id, segment_id)
            previous_label = segment_labels.setdefault(segment_key, label)
            if previous_label != label:
                raise ValueError("ActBeCalf segId is not a single-label annotation segment")
            previous = last_time_by_segment.get(segment_key)
            if previous is not None and parsed < previous:
                backwards_by_animal[animal_id] += 1
            last_time_by_segment[segment_key] = parsed

    # Second pass streams annotation segments and splits any over-limit gap.
    previous_time: datetime | None = None
    for sample in adapt_actbecalf_csv(path, evidence_class=EvidenceClass.MEASURED):
        parsed = _parse_time(sample.timestamp)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        key = (sample.animal_id, sample.source_segment_id)
        if segment_labels.get(key) != sample.original_label:
            raise ValueError("ActBeCalf segId is not a single-label annotation segment")
        if current_key != key:
            flush()
            current_key, previous_time, run_number = key, None, occurrence_counts[key]
            occurrence_counts[key] += 1
        if previous_time is not None:
            delta = (parsed - previous_time).total_seconds()
            if delta <= 0:
                invalid_rows += 1
                flush()
                previous_time = None
            elif delta > GAP_SECONDS:
                sample_gaps += 1
                flush()
        current.append(sample)
        previous_time = parsed
    flush()
    quality = {
        "animals": len(all_animals), "animal_ids": sorted(all_animals),
        "source_samples": sum(all_labels.values()), "raw_label_sample_support": dict(sorted(all_labels.items())),
        "annotation_segments": len(segment_labels), "source_classes": len(all_labels),
        "sessions": None, "sessions_status": "NOT_PROVIDED_BY_SOURCE",
        "animal_observed_span_seconds": {
            animal: (last_time_by_animal[animal] - first_time[animal]).total_seconds()
            for animal in sorted(all_animals)
        },
        "nominal_sampling_rate_hz": SAMPLE_RATE_HZ,
        "axis_unit": "UNKNOWN_PER_OFFICIAL_EXPORT",
        "missing_or_invalid_rows": 0,
        "window_source_ranges_overlap": False,
        "samples_within_segments_out_of_order": invalid_rows,
        "source_segments_with_backwards_chronology_by_animal": dict(sorted(backwards_by_animal.items())),
        "gaps_over_60ms": sample_gaps,
        "discarded_nonuniform_runs": nonuniform_runs,
    }
    return windows, quality


def _train_windows(raw_windows: list[dict[str, Any]]) -> tuple[list[MLWindow], dict[str, Any]]:
    from riose.products.livestock_tracking.behavior_ml.pipeline import split_by_animal

    provisional = [MLWindow(
        window_id=row["window_id"], animal_id=row["animal_id"], session_id=row["session_id"],
        label=row["label"], features=row["features"], dataset_id="actbecalf",
        dataset_source=SOURCE_URL, dataset_license=DATASET_LICENSE,
        sensor_position="NECK", sample_rate_hz=SAMPLE_RATE_HZ,
        evidence_status="EXPERIMENTAL", source_label=row["raw_label"],
        feature_version=row["feature_version"],
        source_file_sha256=None, source_provenance_verified=False,
    ) for row in raw_windows]
    groups = split_by_animal(provisional, SEED)
    split_animals = {name: {r.animal_id for r in rows} for name, rows in groups.items()}
    train_animals = split_animals["train"]
    train_support = {label: {r.animal_id for r in groups["train"] if r.label == label}
                     for label in {r.label for r in groups["train"]}}
    min_train_animals = max(5, math.ceil(len(train_animals) * 0.5))
    keep: set[str] = set()
    per_label: dict[str, Any] = {}
    all_labels = {r.label for r in provisional}
    for label in all_labels:
        split_support = {name: len({r.animal_id for r in rows if r.label == label})
                         for name, rows in groups.items()}
        training_count = len(train_support.get(label, set()))
        eligible = training_count >= min_train_animals
        per_label[label] = {"training_animal_support": training_count,
                            "split_animal_support_reporting_only": split_support,
                            "eligible": eligible}
        if eligible:
            keep.add(label)
    if not keep:
        raise ValueError("no ActBeCalf source behavior meets the training-only class support gate")
    collapsed: list[MLWindow] = []
    other_label = "ACTBECALF.other_unselected"
    for row in provisional:
        selected = row.label in keep
        collapsed.append(MLWindow(**{
            **row.__dict__,
            "label": row.label if selected else other_label,
            "source_label": row.source_label,
        }))
    collapsed_groups = split_by_animal(collapsed, SEED)
    train_labels = {r.label for r in collapsed_groups["train"]}
    if not train_labels:
        raise ValueError("training partition has no labels after the training-only support gate")
    support = {
        "minimum_training_animals_for_individual_class": min_train_animals,
        "training_animal_count": len(train_animals),
        "taxonomy_support_uses_training_only": True,
        "selected_labels": sorted(keep),
        "collapsed_label": other_label,
        "source_label_map": {label: (label if label in keep else other_label) for label in sorted(all_labels)},
        "per_source_label": per_label,
        "final_window_support": {
            name: dict(Counter(row.label for row in rows)) for name, rows in collapsed_groups.items()
        },
    }
    return collapsed, support


def run_pipeline(dataset: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    source_sha256, source_md5 = _check_file(dataset)
    raw_windows, data_quality = _extract(dataset, source_sha256)
    windows, support = _train_windows(raw_windows)
    raw_by_window_id = {row["window_id"]: row for row in raw_windows}
    model_rows = [MLWindow(
        window_id=row.window_id, animal_id=row.animal_id, session_id=row.session_id,
        label=row.label, features=row.features, dataset_id="actbecalf",
        dataset_source=SOURCE_URL, dataset_license=DATASET_LICENSE,
        sensor_position="NECK", sample_rate_hz=SAMPLE_RATE_HZ,
        evidence_status="EXPERIMENTAL", source_label=row.source_label,
        feature_version=row.feature_version, source_file_sha256=source_sha256,
        source_provenance_verified=True,
    ) for row in windows]
    feature_path = output / "feature-windows.jsonl"
    feature_digest = hashlib.sha256()
    with feature_path.open("wb") as feature_stream:
        for window in windows:
            source_window = raw_by_window_id[window.window_id]
            encoded = (json.dumps({
                "window_id": window.window_id, "animal_id": window.animal_id,
                "session_id": window.session_id,
                "source_segment_id": source_window["source_segment_id"],
                "source_row_start": source_window["source_row_start"],
                "source_row_end": source_window["source_row_end"],
                "start_time": source_window["start_time"], "end_time": source_window["end_time"],
                "start_relative_s": source_window["start_relative_s"],
                "end_relative_s": source_window["end_relative_s"],
                "raw_label": source_window["raw_label"], "model_label": window.label,
                "features": window.features, "feature_version": window.feature_version,
                "source_file_sha256": source_sha256,
                "dataset_doi": DATASET_DOI, "source_url": SOURCE_URL,
                "dataset_license": DATASET_LICENSE, "sensor_position": "NECK",
                "axis_unit": "UNKNOWN", "evidence_status": "MEASURED_EXTERNAL_DATA",
                "canonical_behavior_label": "UNKNOWN",
            }, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
            feature_stream.write(encoded)
            feature_digest.update(encoded)
    payload, result = run_training(model_rows, seed=SEED)
    model_path = output / "model.json"
    save_artifact(payload, model_path)
    payload = load_artifact(model_path)
    with feature_path.open("r", encoding="utf-8") as feature_stream:
        grouped_cv = evaluate_grouped_cv([json.loads(line) for line in feature_stream])

    # Persist holdout predictions through Core SQLite and preserve source-relative time.
    splits = payload["split"]
    split_animals = {name: set(value["animals"]) for name, value in splits.items()}
    intersections = {
        "train_validation": sorted(split_animals["train"] & split_animals["validation"]),
        "train_test": sorted(split_animals["train"] & split_animals["test"]),
        "validation_test": sorted(split_animals["validation"] & split_animals["test"]),
    }
    if any(intersections.values()):
        raise AssertionError(f"animal leakage in model split: {intersections}")
    test_animals = split_animals["test"]
    test_rows = [row for row in windows if row.animal_id in test_animals]
    range_keys = [(raw_by_window_id[row.window_id]["source_row_start"],
                   raw_by_window_id[row.window_id]["source_row_end"]) for row in windows]
    duplicate_ranges = len(range_keys) - len(set(range_keys))
    if duplicate_ranges:
        raise AssertionError("duplicate feature-window source ranges")
    by_session: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    for row in windows:
        source_window = raw_by_window_id[row.window_id]
        by_session[(row.animal_id, row.session_id)].append(
            (source_window["source_row_start"], source_window["source_row_end"]))
    overlap_count = 0
    for ranges in by_session.values():
        previous_end = -1
        for start, end in sorted(ranges):
            if start <= previous_end:
                overlap_count += 1
            previous_end = max(previous_end, end)
    if overlap_count:
        raise AssertionError("overlapping windows inside one annotation run")
    temporal_overlap_pairs: Counter[str] = Counter()
    intervals_by_animal: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
    split_by_animal = {animal: name for name, ids in split_animals.items() for animal in ids}
    for row in windows:
        source_window = raw_by_window_id[row.window_id]
        intervals_by_animal[row.animal_id].append((
            source_window["start_relative_s"], source_window["end_relative_s"], row.session_id,
        ))
    for animal, intervals in intervals_by_animal.items():
        active: list[tuple[float, str]] = []
        for start, end, session in sorted(intervals):
            active = [(active_end, active_session) for active_end, active_session in active
                      if active_end > start]
            for _, active_session in active:
                if active_session != session:
                    temporal_overlap_pairs["all"] += 1
                    temporal_overlap_pairs[split_by_animal[animal]] += 1
            active.append((end, session))
    database = output / "core-predictions.sqlite3"
    predictions: list[dict[str, Any]] = []
    model_digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    store = Store(database)
    try:
        for row in test_rows:
            model_label, model_score = _predict_payload(payload, row.features)
            source_window = raw_by_window_id[row.window_id]
            source_ref = f"ACTBECALF.{source_sha256[:16]}:rows-{source_window['source_row_start']}-{source_window['source_row_end']}"
            input_digest = hashlib.sha256(json.dumps(row.features, sort_keys=True,
                separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            existing = store.get_behavior_prediction(row.window_id)
            prediction = BehaviorPrediction(
                animal_id=row.animal_id, tag_id=f"ACTBECALF:{row.animal_id}",
                window_start_s=source_window["start_relative_s"],
                window_end_s=source_window["end_relative_s"],
                created_at_s=time.time() if existing is None else existing.created_at_s,
                behavior=model_label.replace("ACTBECALF.", "ACTBECALF:"),
                confidence=None, model_score=model_score,
                model_version=payload["model_version"],
                model_sha256=model_digest,
                feature_version=row.feature_version, evidence_status=EvidenceStatus.EXPERIMENTAL,
                source_ref=source_ref, input_sha256=input_digest, prediction_id=row.window_id,
                time_basis=PredictionTimeBasis.SOURCE_RELATIVE_SECONDS,
            )
            store.save_behavior_prediction(prediction)
            predictions.append({
                "window_id": row.window_id, "animal_id": row.animal_id,
                "actual": row.label, "predicted": model_label, "model_score": model_score,
                "source_label": row.source_label, "source_row_start": source_window["source_row_start"],
                "source_row_end": source_window["source_row_end"],
                "start_time": source_window["start_time"], "end_time": source_window["end_time"],
                "timestamp_s": source_window["start_relative_s"],
            })
        count_before_close = sum(len(store.list_behavior_predictions(animal, limit=10000))
                                 for animal in sorted(test_animals))
    finally:
        store.close()
    reopened = Store(database)
    try:
        persisted_count = sum(len(reopened.list_behavior_predictions(animal, limit=10000))
                              for animal in sorted(test_animals))
    finally:
        reopened.close()

    biosig_results = [{"status": "INSUFFICIENT_HISTORY",
                       "reason": "annotated clips do not establish daily coverage"}]
    health_results = [{"status": "NOT_EVALUABLE",
                       "reason": "no clinical outcomes or health metrics in ActBeCalf"}]

    evaluation = {
        "status": "EXTERNAL_MEASURED_DATA_MODEL_EVALUATION",
        "dataset": {"id": "actbecalf", "doi": DATASET_DOI, "source_url": SOURCE_URL,
                    "license": DATASET_LICENSE, "publisher_md5": source_md5,
                    "local_sha256": source_sha256, "bytes": dataset.stat().st_size,
                    "version": "Zenodo record 13259482, version 1.0",
                    "sensor_position": "NECK", "timestamp_timezone": "UNKNOWN",
                    "axis_units": "UNKNOWN"},
        "pipeline": {"seed": SEED, "split": payload["split"],
                     "window_seconds": WINDOW_SECONDS, "overlap_fraction": 0,
                     "sample_rate_hz": SAMPLE_RATE_HZ,
                     "partial_window_policy": "discard incomplete tails; never cross annotation segment or >60 ms gap",
                     "label_policy": "homogeneous annotation-segment source labels; no ontology equivalence claimed",
                     "signal_version": PIPELINE_VERSION, "feature_schema": payload["feature_order"],
                     "feature_version": windows[0].feature_version if windows else None},
        "implementation_sha256": _code_fingerprints(),
        "derived_features": {"file": feature_path.name, "sha256": feature_digest.hexdigest(),
                             "rows": len(windows), "status": "DERIVED_EXTERNAL_DATA_FEATURES"},
        "data_quality": data_quality,
        "window_count": len(windows),
        "support_gate": support,
        "model_selection": {"selected_model": result["selected_model"], **payload["evaluation"]},
        "grouped_cross_validation": grouped_cv,
        "leakage_audit": {
            "animal_intersections": intersections,
            "sessions_available": False,
            "session_leakage_control": "all segments and derived runs are grouped by animal",
            "animal_ids_in_model_features": False,
            "segment_ids_in_model_features": False,
            "timestamps_or_source_rows_in_model_features": False,
            "label_derived_feature_columns": False,
            "normalization_fit_partition": "TRAIN_ONLY for validation candidate scoring; refit TRAIN+VALIDATION after model selection",
            "test_used_for_model_selection_or_retraining": False,
            "duplicate_source_window_ranges": duplicate_ranges,
            "window_overlap_fraction": 0.0,
            "overlapping_feature_windows_within_run": overlap_count,
            "overlapping_source_time_intervals_across_annotation_runs": temporal_overlap_pairs["all"],
            "source_time_overlap_pairs_by_split": {name: temporal_overlap_pairs[name]
                                                   for name in ("train", "validation", "test")},
            "source_time_overlaps_are_grouped_by_animal": True,
            "test_windows_shared_with_train": 0,
        },
        "error_analysis": {
            "test_errors_by_predicted_class": dict(Counter(row["predicted"] for row in predictions
                                                              if row["actual"] != row["predicted"])),
            "test_errors_by_animal": dict(Counter(row["animal_id"] for row in predictions
                                                    if row["actual"] != row["predicted"])),
            "source_annotation_transitions": "not used as features; no transition-level test analysis",
            "test_set_used_for_error_driven_model_updates": False,
        },
        "persistence": {"heldout_predictions": len(predictions),
                        "reopened_round_trip_records": persisted_count,
                        "table": "behavior_predictions",
                        "model_score_is_calibrated_probability": False,
                        "timestamp_basis": "SOURCE_RELATIVE_SECONDS", "source_timezone": "UNKNOWN",
                        "sensor_position": "NECK"},
        "biosignature": {"animal_results": biosig_results,
                         "confidence_semantics": "UNAVAILABLE; model_score is uncalibrated and confidence remains null",
                         "coverage_semantics": "unavailable; sparse clips and unknown session continuity are not daily coverage",
                         "claim": "not evaluable as a daily profile; confidence and coverage gates remain closed; no diagnosis"},
        "health": {"animal_results": health_results,
                   "clinical_performance": "NOT_EVALUABLE",
                   "reason": "ActBeCalf has no clinical health labels or appropriate outcomes."},
        "reproduction": {"status": "INSUFFICIENT_EVIDENCE", "events": 0,
                         "reason": "ActBeCalf provides no reproductive outcomes."},
        "movement_rf": {"status": "NOT_EVALUATED", "reason": "ActBeCalf contains no RF measurements."},
        "edge_estimate": _edge_estimate(payload, windows[0].features if windows else {}),
        "sensor_position_transfer": "NOT_VALIDATED",
        "field_performance": "NOT_EVALUATED",
        "predictions": predictions,
    }
    acquisition_manifest = {
        key: evaluation["dataset"][key]
        for key in ("id", "doi", "version", "license", "source_url",
                    "publisher_md5", "local_sha256", "bytes", "sensor_position",
                    "timestamp_timezone", "axis_units")
    }
    (output / "acquisition-manifest.json").write_text(
        json.dumps(acquisition_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run_config = {
        "seed": SEED, "window_seconds": WINDOW_SECONDS, "sample_rate_hz": SAMPLE_RATE_HZ,
        "overlap_fraction": 0.0, "max_gap_seconds": GAP_SECONDS,
        "animal_split": "60/20/20; deterministic seed 23",
        "class_support_min_training_animals": support["minimum_training_animals_for_individual_class"],
        "models": payload["training_config"]["candidate_models"],
        "selection_metric": payload["training_config"]["selection_metric"],
        "feature_order": payload["feature_order"],
        "feature_version": windows[0].feature_version if windows else None,
        "signal_pipeline_version": PIPELINE_VERSION,
        "label_mapping": "train-only support threshold; other labels grouped as ACTBECALF.other_unselected",
        "implementation_sha256": _code_fingerprints(),
    }
    (output / "run-config.json").write_text(
        json.dumps(run_config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "evaluation.json").write_text(json.dumps(evaluation, indent=2, sort_keys=True,
                                                        default=dict, allow_nan=False) + "\n", encoding="utf-8")
    return evaluation


def _edge_estimate(payload: dict[str, Any], example_features: dict[str, float]) -> dict[str, Any]:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    feature_bytes = 4 * len(example_features)
    model = payload["model"]
    if model["kind"] == "logistic_regression":
        operations = len(model["coef"][0]) * len(model["coef"])
    elif model["kind"] in {"decision_tree", "extra_trees"}:
        trees = [model] if model["kind"] == "decision_tree" else model["trees"]
        def depth(tree: dict[str, Any], node: int = 0) -> int:
            left, right = tree["children_left"][node], tree["children_right"][node]
            if left == right:
                return 0
            return 1 + max(depth(tree, left), depth(tree, right))
        operations = sum(depth(tree) for tree in trees)
    else:
        operations = len(payload["classes"])
    return {"classification": "ENGINEERING_ESTIMATE", "portable_json_artifact_bytes": len(serialized),
            "model_parameter_count": (sum(len(row) for row in model["coef"]) + len(model["intercept"])
                                      if model["kind"] == "logistic_regression" else
                                      sum(len(tree["children_left"]) for tree in
                                          ([model] if model["kind"] == "decision_tree" else
                                           model["trees"] if model["kind"] == "extra_trees" else []))),
            "feature_vector_bytes_float32": feature_bytes,
            "estimated_model_comparisons_or_multiply_adds_per_inference": operations,
            "window_input_memory_estimate_float32": int(SAMPLE_RATE_HZ * WINDOW_SECONDS * 3 * 4),
            "input_rate_samples_per_s": SAMPLE_RATE_HZ,
            "input_rate_bytes_per_s_xyz_float32": int(SAMPLE_RATE_HZ * 3 * 4),
            "workstation_benchmark": False, "stm32_benchmark": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="replay a checksum-verified ActBeCalf CSV entirely offline")
    run.add_argument("--dataset", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run_pipeline(args.dataset, args.output)
    except Exception as exc:
        print(f"pipeline failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": report["status"], "output": str(args.output),
                      "windows": report["window_count"], "model": report["model_selection"]["selected_model"]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
