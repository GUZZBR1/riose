"""Reproducible observation datasets with truth in a separate file/namespace."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
import uuid
from typing import Iterable

from ...domain.contracts import GroundTruth, RFObservation


def write_episode_dataset(observations: Iterable[RFObservation], truth: Iterable[GroundTruth],
                          output_dir: str | Path, split: str,
                          scenario: dict | None = None) -> dict[str, str]:
    """Write inference features and evaluation labels separately.

    All streams are first written below a private staging directory. The split
    directory is replaced only after feature CSV, truth CSV, optional Parquet,
    and the completion manifest have been produced successfully. CSV remains
    the portable fallback when PyArrow is not installed.
    """
    if split not in {"train", "validation", "holdout"}:
        raise ValueError("split must be train, validation, or holdout")

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    published_root = root / split
    staging_root = root / f".{split}.staging-{uuid.uuid4().hex}"
    backup_root = root / f".{split}.backup-{uuid.uuid4().hex}"
    features_dir = staging_root / "features"
    truth_dir = staging_root / "ground_truth"
    features_dir.mkdir(parents=True)
    truth_dir.mkdir(parents=True)

    feature_csv = features_dir / "observations.csv"
    feature_csv_tmp = features_dir / "observations.csv.tmp"
    truth_csv = truth_dir / "labels.csv"
    truth_csv_tmp = truth_dir / "labels.csv.tmp"
    parquet_path = features_dir / "observations.parquet"
    parquet_tmp = features_dir / "observations.parquet.tmp"
    feature_fields = ["timestamp_s", "tag_id", "anchor_id", "rssi_dbm", "snr_db",
                      "packet_received", "imu_accel_norm_g", "behavior_state", "tof_ns",
                      "phase_rad", "status"]
    truth_fields = ["timestamp_s", "tag_id", "x", "y"]

    try:
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            pa = pq = None

        parquet_writer = None
        parquet_batch: list[dict] = []
        batch_size = 4096

        def flush_parquet_batch() -> None:
            nonlocal parquet_writer, parquet_batch
            if not parquet_batch or pa is None or pq is None:
                return
            table = pa.Table.from_pylist(parquet_batch)
            if parquet_writer is None:
                parquet_writer = pq.ParquetWriter(parquet_tmp, table.schema)
            parquet_writer.write_table(table)
            parquet_batch = []

        try:
            with feature_csv_tmp.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=feature_fields)
                writer.writeheader()
                for observation in observations:
                    row = {
                        "timestamp_s": observation.timestamp_s, "tag_id": observation.tag_id,
                        "anchor_id": observation.anchor_id, "rssi_dbm": observation.rssi_dbm,
                        "snr_db": observation.snr_db, "packet_received": observation.packet_received,
                        "imu_accel_norm_g": observation.imu_accel_norm_g,
                        "behavior_state": observation.behavior_state, "tof_ns": observation.tof_ns,
                        "phase_rad": observation.phase_rad, "status": observation.status.value,
                    }
                    writer.writerow(row)
                    if pa is not None and pq is not None:
                        parquet_batch.append(row)
                        if len(parquet_batch) >= batch_size:
                            flush_parquet_batch()
                flush_parquet_batch()
        finally:
            if parquet_writer is not None:
                parquet_writer.close()

        if parquet_writer is None and pa is not None and pq is not None:
            empty_schema = pa.schema([
                ("timestamp_s", pa.float64()), ("tag_id", pa.string()),
                ("anchor_id", pa.string()), ("rssi_dbm", pa.float64()),
                ("snr_db", pa.float64()), ("packet_received", pa.bool_()),
                ("imu_accel_norm_g", pa.float64()), ("behavior_state", pa.string()),
                ("tof_ns", pa.float64()), ("phase_rad", pa.float64()), ("status", pa.string()),
            ])
            pq.write_table(pa.Table.from_pylist([], schema=empty_schema), parquet_tmp)

        with truth_csv_tmp.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=truth_fields)
            writer.writeheader()
            writer.writerows({"timestamp_s": point.timestamp_s, "tag_id": point.tag_id,
                              "x": point.x, "y": point.y} for point in truth)

        # Promote the completed streams inside staging before writing the
        # manifest. Its presence therefore marks a complete staged split.
        feature_csv_tmp.replace(feature_csv)
        truth_csv_tmp.replace(truth_csv)
        if pa is not None and pq is not None:
            parquet_tmp.replace(parquet_path)
        manifest = {"split": split, "feature_fields": feature_fields,
                    "feature_file": str(root / split / "features" / feature_csv.name),
                    "ground_truth_file": str(root / split / "ground_truth" / truth_csv.name),
                    "scenario": scenario or {}, "status": "SIMULATED"}
        (staging_root / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")

        if published_root.exists():
            published_root.rename(backup_root)
        try:
            staging_root.rename(published_root)
        except BaseException:
            if backup_root.exists() and not published_root.exists():
                backup_root.rename(published_root)
            raise
        if backup_root.exists():
            shutil.rmtree(backup_root, ignore_errors=True)
    except BaseException:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise

    outputs = {
        "features_csv": str(published_root / "features" / "observations.csv"),
        "ground_truth_csv": str(published_root / "ground_truth" / "labels.csv"),
        "manifest": str(published_root / "manifest.json"),
    }
    if pa is not None and pq is not None:
        outputs["features_parquet"] = str(published_root / "features" / "observations.parquet")
    else:
        outputs["parquet"] = "unavailable; CSV fallback written"
    return outputs
