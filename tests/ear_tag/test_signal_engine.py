"""Independent numerical and adversarial checks for the XYZ signal engine."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
import pytest

from riose.products.ear_tag.signal import (
    FEATURE_NAMES,
    PIPELINE_VERSION,
    SignalSample,
    SignalTrace,
    WindowConfig,
    extract_features,
)


def make_trace(values: np.ndarray, rate: float = 12.5, *, unit: str = "g",
               animal: str = "a", session: str = "s", evidence: str = "SIMULATED",
               times: np.ndarray | None = None, sensor: str = "collar",
               full_scale: float | None = None) -> SignalTrace:
    if times is None:
        times = np.arange(len(values), dtype=float) / rate
    samples = tuple(
        SignalSample(float(t), *map(float, xyz), animal, session, sensor, unit, evidence)
        for t, xyz in zip(times, values, strict=True)
    )
    return SignalTrace(samples, rate, "fixture:golden", full_scale)


def one_window(trace: SignalTrace, duration_s: float, **kwargs: object):
    windows = extract_features(trace, WindowConfig(duration_s, **kwargs))
    assert len(windows) == 1
    return windows[0]


def test_analytic_constant_golden_vector_and_provenance() -> None:
    values = np.tile([1.0, 2.0, 2.0], (100, 1))
    result = one_window(make_trace(values), 8.0)
    f = result.features
    expected = {
        "mean_x_g": 1.0, "mean_y_g": 2.0, "mean_z_g": 2.0,
        "std_x_g": 0.0, "std_y_g": 0.0, "std_z_g": 0.0,
        "rms_x_g": 1.0, "rms_y_g": 2.0, "rms_z_g": 2.0,
        "mean_magnitude_g": 3.0, "rms_magnitude_g": 3.0, "sma_g": 5.0,
        "jerk_rms_g_per_s": 0.0, "energy_g2_s": 72.0,
        "dominant_frequency_hz": 0.0,
    }
    assert result.feature_names == FEATURE_NAMES
    assert f == expected
    assert result.provenance["pipeline_version"] == PIPELINE_VERSION
    assert result.provenance["evidence_status"] == "SIMULATED"
    assert result.provenance["canonical_unit"] == "g"


def test_existing_lis2dw12_static_fixture_remains_simulated() -> None:
    repo = Path(__file__).parents[2]
    fixture_dir = repo / "hardware" / "models" / "lis2dw12" / "datasets"
    manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))
    fixture = next(row for row in manifest["datasets"] if row["name"] == "STATIC")
    with (fixture_dir / fixture["file"]).open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    samples = tuple(SignalSample(
        float(row["timestamp_s"]), float(row["x_g"]), float(row["y_g"]),
        float(row["z_g"]), "fixture-tag", "fixture-session", "collar",
        fixture["unit"], fixture["status"],
    ) for row in rows)
    windows = extract_features(
        SignalTrace(samples, fixture["sample_rate_hz"], f"fixture:{fixture['file']}"),
        WindowConfig(4.0),
    )
    assert len(windows) == 2
    assert all(window.provenance["evidence_status"] == "SIMULATED" for window in windows)
    assert all(window.provenance["source_ref"] == "fixture:static.csv" for window in windows)


def test_sinusoid_golden_at_12_5_hz_and_an_alternative_rate() -> None:
    for rate in (12.5, 20.0):
        n = int(rate * 4)
        t = np.arange(n) / rate
        values = np.column_stack((np.sin(2 * math.pi * 1.0 * t), np.zeros(n), np.ones(n)))
        f = one_window(make_trace(values, rate), 4.0).features
        assert f["mean_x_g"] == pytest.approx(0.0, abs=1e-14)
        assert f["rms_x_g"] == pytest.approx(1 / math.sqrt(2), abs=1e-14)
        assert f["dominant_frequency_hz"] == pytest.approx(1.0)
        assert f["mean_z_g"] == 1.0


def test_impulse_golden_vector() -> None:
    values = np.zeros((100, 3))
    values[50, 0] = 1.0
    f = one_window(make_trace(values), 8.0).features
    assert f["mean_x_g"] == pytest.approx(0.01)
    assert f["rms_x_g"] == pytest.approx(0.1)
    assert f["sma_g"] == pytest.approx(0.01)
    assert f["energy_g2_s"] == pytest.approx(0.08)
    assert f["dominant_frequency_hz"] <= 6.25


def test_axis_permutation_is_reflected_in_axis_features_but_not_magnitude() -> None:
    values = np.tile([1.0, 2.0, 3.0], (100, 1))
    original = one_window(make_trace(values), 8.0).features
    permuted = one_window(make_trace(values[:, [2, 0, 1]]), 8.0).features
    assert (original["mean_x_g"], original["mean_y_g"], original["mean_z_g"]) == (1, 2, 3)
    assert (permuted["mean_x_g"], permuted["mean_y_g"], permuted["mean_z_g"]) == (3, 1, 2)
    assert permuted["mean_magnitude_g"] == pytest.approx(original["mean_magnitude_g"])
    assert permuted["sma_g"] == pytest.approx(original["sma_g"])


@pytest.mark.parametrize("unit,scale", [("g", 1), ("mg", 1000), ("m/s^2", 9.80665)])
def test_explicit_unit_conversion(unit: str, scale: float) -> None:
    values = np.tile([1.0 * scale, 0.0, 0.0], (100, 1))
    assert one_window(make_trace(values, unit=unit), 8.0).features["mean_x_g"] == pytest.approx(1.0)


def test_resampling_records_rate_and_anti_aliases_above_target_nyquist() -> None:
    rate = 100.0
    t = np.arange(1000) / rate
    # A 30 Hz source tone is below source Nyquist but above the 10 Hz target Nyquist.
    values = np.column_stack((np.sin(2 * math.pi * 30 * t), np.zeros(len(t)), np.zeros(len(t))))
    result = extract_features(
        make_trace(values, rate), WindowConfig(2.0, target_sample_rate_hz=10.0)
    )[0]
    assert result.provenance["source_sample_rate_hz"] == 100.0
    assert result.provenance["sample_rate_hz"] == 10.0
    assert result.provenance["nyquist_hz"] == 5.0
    assert result.provenance["resampling_method"] == "polyphase-fir"
    assert result.provenance["resampling_up"] == 1
    assert result.provenance["resampling_down"] == 10
    assert result.features["rms_x_g"] < 0.02
    assert result.features["dominant_frequency_hz"] <= 5.0


def test_jitter_is_corrected_and_reported() -> None:
    rate = 12.5
    times = np.arange(100) / rate
    times += 0.0005 * np.sin(np.arange(100))
    values = np.column_stack((np.sin(2 * np.pi * times), np.zeros(100), np.zeros(100)))
    result = extract_features(
        make_trace(values, rate, times=times),
        WindowConfig(4.0, target_sample_rate_hz=10.0),
    )[0]
    assert result.provenance["resampling_jitter_interpolation"] is True
    assert "linear-jitter-correction" in result.provenance["resampling_method"]


@pytest.mark.parametrize("bad", [[], [[0.0, 0.0, float("nan")]] * 100,
                                  [[0.0, 0.0, float("inf")]] * 100])
def test_empty_and_nonfinite_inputs_rejected(bad: list[list[float]]) -> None:
    trace = make_trace(np.asarray(bad, dtype=float))
    with pytest.raises(ValueError):
        extract_features(trace, WindowConfig(4.0))


def test_short_window_and_missing_rate_rejected() -> None:
    with pytest.raises(ValueError, match="shorter"):
        extract_features(make_trace(np.ones((20, 3))), WindowConfig(4.0))
    trace = make_trace(np.ones((100, 3)))
    with pytest.raises(ValueError, match="required"):
        extract_features(SignalTrace(trace.samples, None), WindowConfig(4.0))


def test_duplicate_out_of_order_gap_rate_conflict_and_jitter_rejected() -> None:
    values = np.ones((100, 3))
    for times, rate, config, message in (
        (np.r_[np.arange(50) / 12.5, np.arange(50) / 12.5 + 3.92], 12.5, WindowConfig(2.0), "strictly increasing"),
        (np.r_[np.arange(50) / 12.5, np.arange(50) / 12.5 + 3.84], 12.5, WindowConfig(2.0), "strictly increasing"),
        (np.r_[np.arange(50) / 12.5, np.arange(50, 100) / 12.5 + 0.2], 12.5, WindowConfig(2.0), "gap"),
        (np.arange(100) / 10.0, 12.5, WindowConfig(2.0), "conflicts"),
    ):
        with pytest.raises(ValueError, match=message):
            extract_features(make_trace(values, rate, times=times), config)
    jitter = np.arange(100) / 12.5
    jitter[50:] += 0.02
    with pytest.raises(ValueError, match="jitter"):
        extract_features(make_trace(values, times=jitter), WindowConfig(2.0, max_jitter_fraction=0.1))


def test_invalid_unit_saturation_upsampling_and_unrepresentable_rate_rejected() -> None:
    values = np.tile([1.0, 0.0, 0.0], (100, 1))
    trace = make_trace(values)
    bad_unit = tuple(SignalSample(s.timestamp_s, s.x, s.y, s.z, s.animal_id,
                                  s.session_id, s.sensor_position, "mg/g", s.evidence_status)
                     for s in trace.samples)
    with pytest.raises(ValueError, match="unit"):
        extract_features(SignalTrace(bad_unit, 12.5), WindowConfig(4.0))
    with pytest.raises(ValueError, match="saturated"):
        extract_features(SignalTrace(trace.samples, 12.5, full_scale=1.0), WindowConfig(4.0))
    with pytest.raises(ValueError, match="upsampling"):
        extract_features(trace, WindowConfig(4.0, target_sample_rate_hz=20.0))
    with pytest.raises(ValueError, match="represented"):
        extract_features(trace, WindowConfig(4.0, target_sample_rate_hz=7.333))


def test_overlap_determinism_and_boundary_isolation() -> None:
    values = np.tile([0.0, 0.0, 1.0], (200, 1))
    trace = make_trace(values)
    config = WindowConfig(4.0, overlap_fraction=0.5)
    first = extract_features(trace, config)
    assert first == extract_features(trace, config)
    assert len(first) == 7
    assert first[1].start_timestamp_s - first[0].start_timestamp_s == pytest.approx(2.0)
    assert first[0].provenance["discarded_tail_samples"] == 0

    split = list(trace.samples)
    split[80:] = [SignalSample(s.timestamp_s, s.x, s.y, s.z, "b", s.session_id,
                               s.sensor_position, s.unit, s.evidence_status) for s in split[80:]]
    separated = extract_features(SignalTrace(tuple(split), 12.5), WindowConfig(4.0))
    assert {window.provenance["animal_id"] for window in separated} == {"a", "b"}


def test_metadata_changes_for_session_and_sensor_mount_boundary() -> None:
    values = np.ones((200, 3))
    samples = []
    for i, xyz in enumerate(values):
        session = "s1" if i < 100 else "s2"
        position = "collar" if i < 100 else "ear"
        samples.append(SignalSample(i / 12.5, *map(float, xyz), "a", session,
                                    position, "g", "SIMULATED"))
    result = extract_features(SignalTrace(tuple(samples), 12.5), WindowConfig(4.0))
    assert [window.provenance["session_id"] for window in result] == ["s1", "s1", "s2", "s2"]
    assert [window.provenance["sensor_position"] for window in result] == ["collar", "collar", "ear", "ear"]


def test_tolerated_declared_rate_difference_is_explicit_in_metadata() -> None:
    rate = 12.5
    timestamps = np.arange(100) / (rate * 1.03)
    result = extract_features(
        make_trace(np.ones((100, 3)), rate, times=timestamps), WindowConfig(4.0)
    )[0]
    assert result.provenance["observed_timestamp_rate_hz"] == pytest.approx(rate * 1.03)
    assert result.provenance["timestamp_rate_relative_error"] == pytest.approx(0.03)
    assert result.provenance["timestamp_rate_tolerance_fraction"] == 0.05
