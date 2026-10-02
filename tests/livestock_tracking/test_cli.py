import csv
from array import array
import argparse
import builtins
import pytest

from riose.products.livestock_tracking.adapters.datasets import write_episode_dataset
from riose.products.livestock_tracking.domain.contracts import RFObservation
from riose.products.livestock_tracking.cli import (
    CsvStreamWriter,
    StressSummary,
    _validate_benchmark_workload,
    _validate_dataset_workload,
    aggregate_stress,
    iter_stress_benchmark,
    nearest_truth_point,
    run_stress_benchmark,
)

from riose.products.livestock_tracking.cli import ErrorCsvWriter, aggregate_errors


def test_error_csv_writer_streams_rows_with_existing_schema(tmp_path):
    path = tmp_path / "localization_errors.csv"
    writer = ErrorCsvWriter(path)
    writer.append({"animal_count": 2, "anchor_count": 4, "seed": 7,
                   "method": "weighted_centroid", "tag_id": "tag-0001",
                   "timestamp_s": 30.0, "error_m": 1.25, "evidence": "SIMULATED"})
    writer.close()

    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == ["animal_count", "anchor_count", "seed", "method",
                                     "tag_id", "timestamp_s", "error_m", "evidence"]
        assert list(reader) == [{"animal_count": "2", "anchor_count": "4", "seed": "7",
                                 "method": "weighted_centroid", "tag_id": "tag-0001",
                                 "timestamp_s": "30.0", "error_m": "1.25",
                                 "evidence": "SIMULATED"}]
    assert len(writer) == 1


def test_error_aggregate_uses_compact_values_and_oracle_reference():
    means = aggregate_errors({"weighted_centroid": array("d", [2.0, 4.0])}, gps_error_count=3)

    assert means["gps_oracle_reference"] == 0.0
    assert means["weighted_centroid"] == 3.0
    assert means["path_loss"] is None


def test_csv_fallback_removes_parquet_from_previous_export(tmp_path, monkeypatch):
    parquet_path = tmp_path / "holdout" / "features" / "observations.parquet"
    parquet_path.parent.mkdir(parents=True)
    parquet_path.write_bytes(b"stale parquet from an earlier run")
    real_import = builtins.__import__

    def import_without_pyarrow(name, *args, **kwargs):
        if name == "pyarrow" or name.startswith("pyarrow."):
            raise ImportError("PyArrow is not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_pyarrow)
    outputs = write_episode_dataset([], [], tmp_path, "holdout")

    assert outputs["parquet"].startswith("unavailable")
    assert not parquet_path.exists()
    assert (tmp_path / "holdout" / "features" / "observations.csv").exists()
    assert (tmp_path / "holdout" / "manifest.json").exists()


def test_dataset_generation_failure_preserves_published_split(tmp_path):
    split = tmp_path / "holdout"
    features = split / "features"
    labels = split / "ground_truth"
    features.mkdir(parents=True)
    labels.mkdir(parents=True)
    old_files = {
        features / "observations.csv": b"old feature data\n",
        features / "observations.parquet": b"old parquet data",
        labels / "labels.csv": b"old label data\n",
        split / "manifest.json": b'{"status":"SIMULATED","generation":"old"}',
    }
    for path, contents in old_files.items():
        path.write_bytes(contents)

    observation = RFObservation(0.0, "tag-1", "anchor-1", -70.0, 8.0, True)

    def observations_with_failure():
        yield observation
        raise RuntimeError("injected iterator failure")

    with pytest.raises(RuntimeError, match="injected iterator failure"):
        write_episode_dataset(observations_with_failure(), [], tmp_path, "holdout")

    assert {path: path.read_bytes() for path in old_files} == old_files
    assert not list(tmp_path.glob(".holdout.staging-*"))
    assert not list(tmp_path.glob(".holdout.backup-*"))


def test_stress_benchmark_stream_matches_compatibility_results():
    streamed_metrics = []
    streamed_errors = []
    for row_type, row in iter_stress_benchmark(duration_s=0, sample_period_s=60, seed=19):
        (streamed_metrics if row_type == "metric" else streamed_errors).append(row)

    assert (streamed_metrics, streamed_errors) == run_stress_benchmark(
        duration_s=0, sample_period_s=60, seed=19)


def test_stress_benchmark_yields_before_simulating_next_scenario(monkeypatch):
    from riose.products.livestock_tracking import cli

    real_simulate = cli.simulate_episode
    generated = []

    def track_simulation(*args, **kwargs):
        episode = real_simulate(*args, **kwargs)
        generated.append(episode)
        return episode

    monkeypatch.setattr(cli, "simulate_episode", track_simulation)
    rows = iter_stress_benchmark(duration_s=0, sample_period_s=60, seed=23)

    first_type, first_row = next(rows)
    assert first_type == "metric"
    assert first_row["scenario"] == "LOS"
    assert len(generated) == 1
    next(rows)
    assert len(generated) == 1


def test_nearest_stress_truth_lookup_matches_linear_search_and_breaks_ties_earlier():
    from riose.products.livestock_tracking.domain.contracts import GroundTruth

    candidates = [GroundTruth(timestamp, "tag-1", float(timestamp), 0.0)
                  for timestamp in (0.0, 10.0, 20.0)]
    timestamps = [point.timestamp_s for point in candidates]

    for requested in (-5.0, 0.0, 4.9, 5.0, 10.1, 19.0, 25.0):
        expected = min(candidates, key=lambda point: (
            abs(point.timestamp_s - requested), point.timestamp_s))
        assert nearest_truth_point(candidates, timestamps, requested) == expected
    assert nearest_truth_point([], [], 5.0) is None


def test_streaming_csv_writer_publishes_rows_with_given_schema(tmp_path):
    output = tmp_path / "stress_errors.csv"
    with CsvStreamWriter(output, ("scenario", "error_m")) as writer:
        writer.append({"scenario": "LOS", "error_m": 1.25})

    with output.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == ["scenario", "error_m"]
        assert list(reader) == [{"scenario": "LOS", "error_m": "1.25"}]
    assert not (tmp_path / "stress_errors.csv.tmp").exists()


def test_streamed_stress_summary_matches_row_based_aggregate():
    rows = [
        {"scenario": "LOS", "anchor_count": 4, "method": "centroid", "mean_error_m": 2.0},
        {"scenario": "LOS", "anchor_count": 8, "method": "centroid", "mean_error_m": 4.0},
        {"scenario": "NLOS", "anchor_count": 4, "method": "centroid", "mean_error_m": None},
        {"scenario": "LOS", "anchor_count": 4, "method": "path_loss", "mean_error_m": 6.0},
    ]
    streamed = StressSummary()
    for row in rows:
        streamed.add(row)

    assert streamed.scenario_count == 3
    assert streamed.means() == aggregate_stress(rows)


def test_default_benchmark_and_dataset_workloads_fit_memory_budgets():
    _validate_benchmark_workload(argparse.Namespace(
        profile="full", animals=None, anchors=None, duration=None, seeds=1))
    _validate_dataset_workload(argparse.Namespace(
        animals=20, anchors=8, duration=1800.0, period=30.0))


def test_oversized_cli_workloads_are_rejected_before_simulation():
    with pytest.raises(ValueError, match="in-memory sample budget"):
        _validate_dataset_workload(argparse.Namespace(
            animals=1000, anchors=40, duration=604800.0, period=0.001))
    with pytest.raises(ValueError, match="in-memory sample budget"):
        _validate_benchmark_workload(argparse.Namespace(
            profile="full", animals=[1000], anchors=[40], duration=604800.0, seeds=1))
