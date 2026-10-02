import csv
import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "generate_datasets.py"
SPEC = importlib.util.spec_from_file_location("lis2dw12_datasets", MODULE_PATH)
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


def test_generates_all_profiles_with_explicit_metadata_and_deterministic_rows(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest = generator.generate_datasets(first, sample_rate_hz=25, samples=16, seed=42)
    generator.generate_datasets(second, sample_rate_hz=25, samples=16, seed=42)

    assert [item["name"] for item in manifest["datasets"]] == list(generator.PROFILES)
    assert all(item["status"] == "SIMULATED" and item["unit"] == "g" for item in manifest["datasets"])
    assert all(item["sample_rate_hz"] == 25 and item["seed"] == 42 for item in manifest["datasets"])
    assert manifest["provenance"] == "SIMULATED"
    for item in manifest["datasets"]:
        left = first / item["file"]
        right = second / item["file"]
        assert left.read_bytes() == right.read_bytes()
        with left.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 16
        assert set(rows[0]) == {"timestamp_s", "x_g", "y_g", "z_g"}
        assert float(rows[1]["timestamp_s"]) - float(rows[0]["timestamp_s"]) == pytest.approx(1 / 25)
    assert json.loads((first / "manifest.json").read_text()) == manifest


def test_seed_changes_random_profile_but_not_profile_inventory(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    generator.generate_datasets(a, samples=20, seed=10)
    generator.generate_datasets(b, samples=20, seed=11)
    assert (a / "random_movement.csv").read_bytes() != (b / "random_movement.csv").read_bytes()


def test_profile_shapes_are_distinguishable_and_impact_is_transient(tmp_path):
    generator.generate_datasets(tmp_path, sample_rate_hz=25, samples=64, seed=4)

    def axes(filename, axis):
        with (tmp_path / filename).open(newline="", encoding="utf-8") as stream:
            return [float(row[axis]) for row in csv.DictReader(stream)]

    static_x = axes("static.csv", "x_g")
    walk_x = axes("walk.csv", "x_g")
    run_x = axes("run.csv", "x_g")
    impact_z = axes("impact.csv", "z_g")
    assert max(static_x) - min(static_x) <= 0.004
    assert max(abs(value) for value in walk_x) > 0.15
    assert max(abs(value) for value in run_x) > max(abs(value) for value in walk_x)
    assert max(impact_z) > 3.0
    assert sum(value > 1.1 for value in impact_z) <= 5


@pytest.mark.parametrize("rate", [0, -1, 1600.1, float("inf"), float("nan")])
def test_rejects_invalid_sample_rates(tmp_path, rate):
    with pytest.raises(ValueError):
        generator.generate_datasets(tmp_path, sample_rate_hz=rate)


@pytest.mark.parametrize("samples", [0, -1, 1.5, True, 1_000_001])
def test_rejects_invalid_sample_counts(tmp_path, samples):
    with pytest.raises(ValueError):
        generator.generate_datasets(tmp_path, samples=samples)


def test_rejects_invalid_seed(tmp_path):
    with pytest.raises(ValueError):
        generator.generate_datasets(tmp_path, seed=-1)
