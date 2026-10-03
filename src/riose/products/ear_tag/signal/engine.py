"""Pure XYZ validation, segmentation, optional resampling, and features.

Input acceleration is converted to g. Timestamps are seconds on one monotonic
clock. The declared rate must agree with the median timestamp interval within
5%; individual intervals may jitter by at most the configured fraction, and a
gap larger than 1.5 nominal periods is rejected. Each contiguous animal,
session, mount-position, and evidence run is processed independently.

Downsampling uses SciPy's polyphase FIR resampler (anti-alias filtering); small
accepted timestamp jitter is first interpolated onto a uniform source grid.
All transformations and rates are recorded in each output's metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math

import numpy as np
from scipy.signal import resample_poly

PIPELINE_VERSION = "riose.signal/1.0.0"
GRAVITY_M_S2 = 9.80665
FEATURE_NAMES = (
    "mean_x_g", "mean_y_g", "mean_z_g",
    "std_x_g", "std_y_g", "std_z_g",
    "rms_x_g", "rms_y_g", "rms_z_g",
    "mean_magnitude_g", "rms_magnitude_g", "sma_g",
    "jerk_rms_g_per_s", "energy_g2_s", "dominant_frequency_hz",
)
_UNIT_TO_G = {"g": 1.0, "mg": 0.001, "m/s^2": 1.0 / GRAVITY_M_S2}


@dataclass(frozen=True, slots=True)
class SignalSample:
    """One XYZ sample and the identity/provenance needed to segment safely."""

    timestamp_s: float
    x: float
    y: float
    z: float
    animal_id: str
    session_id: str
    sensor_position: str
    unit: str
    evidence_status: str


@dataclass(frozen=True, slots=True)
class SignalTrace:
    """Samples from one source clock with an explicitly declared sample rate."""

    samples: tuple[SignalSample, ...]
    sample_rate_hz: float | None
    source_ref: str | None = None
    full_scale: float | None = None


@dataclass(frozen=True, slots=True)
class WindowConfig:
    """Window duration and overlap, plus optional explicit output rate."""

    duration_s: float
    overlap_fraction: float = 0.0
    target_sample_rate_hz: float | None = None
    max_jitter_fraction: float = 0.15


@dataclass(frozen=True, slots=True)
class FeatureWindow:
    """An ordered, reproducible feature vector and its source metadata."""

    feature_names: tuple[str, ...]
    vector: tuple[float, ...]
    start_timestamp_s: float
    end_timestamp_s: float
    metadata: tuple[tuple[str, object], ...]

    @property
    def features(self) -> dict[str, float]:
        """Return a new name-to-value mapping, in the documented schema order."""
        return dict(zip(self.feature_names, self.vector, strict=True))

    @property
    def provenance(self) -> dict[str, object]:
        """Return a copy of the deterministic metadata mapping."""
        return dict(self.metadata)


def extract_features(trace: SignalTrace, config: WindowConfig) -> tuple[FeatureWindow, ...]:
    """Validate and extract features without training, inference, or I/O.

    Rates are mandatory and never inferred from timestamps. A short run, gap,
    rate conflict, saturation, invalid unit, or malformed sample raises
    ``ValueError`` rather than silently returning plausible-looking features.
    """
    _validate_config(config)
    if type(trace) is not SignalTrace:
        raise ValueError("trace must be a SignalTrace")
    if not trace.samples:
        raise ValueError("trace must contain at least one sample")
    if trace.sample_rate_hz is None:
        raise ValueError("sample_rate_hz is required; rate is never inferred")
    source_rate = _finite_positive(trace.sample_rate_hz, "sample_rate_hz")
    if trace.source_ref is not None and (
        not isinstance(trace.source_ref, str) or not trace.source_ref.strip()
    ):
        raise ValueError("source_ref must be a non-empty string when provided")

    rows = [_validate_sample(sample) for sample in trace.samples]
    units = {sample.unit for sample, _ in rows}
    if len(units) != 1:
        raise ValueError("all samples in one trace must declare the same unit")
    trace_unit = rows[0][0].unit
    full_scale_g = None
    if trace.full_scale is not None:
        full_scale_g = _finite_positive(trace.full_scale, "full_scale") * _UNIT_TO_G[trace_unit]

    runs: list[list[tuple[SignalSample, np.ndarray]]] = []
    for sample, xyz in rows:
        if full_scale_g is not None and np.any(np.abs(xyz) >= full_scale_g):
            raise ValueError("saturated sample reached the declared full_scale")
        key = _sample_key(sample)
        if not runs or key != _sample_key(runs[-1][-1][0]):
            runs.append([])
        runs[-1].append((sample, xyz))

    output: list[FeatureWindow] = []
    for run in runs:
        samples = [row[0] for row in run]
        values = np.stack([row[1] for row in run]).astype(np.float64, copy=False)
        times = np.asarray([sample.timestamp_s for sample in samples], dtype=np.float64)
        observed_rate, rate_relative_error = _validate_clock(
            times, source_rate, config.max_jitter_fraction
        )
        target_rate = config.target_sample_rate_hz or source_rate
        if target_rate > source_rate and config.target_sample_rate_hz is not None:
            raise ValueError("upsampling is unsupported because it cannot add measured information")
        resample_meta: dict[str, object] = {
            "resampling_method": "none",
            "resampling_up": 1,
            "resampling_down": 1,
            "resampling_jitter_interpolation": False,
            "resampling_filter": "none",
        }
        if config.target_sample_rate_hz is not None and target_rate != source_rate:
            values, times, ratio = _resample(values, times, source_rate, target_rate)
            resample_meta.update({
                "resampling_method": (
                    "linear-jitter-correction+polyphase-fir" if ratio[2] else "polyphase-fir"
                ),
                "resampling_up": ratio[0],
                "resampling_down": ratio[1],
                "resampling_jitter_interpolation": ratio[2],
                "resampling_filter": "SciPy polyphase FIR; Kaiser beta=5.0",
            })
        window_samples = int(round(config.duration_s * target_rate))
        if window_samples < 8:
            raise ValueError("each window must contain at least 8 samples for spectral features")
        stride = max(1, int(round(window_samples * (1.0 - config.overlap_fraction))))
        if len(values) < window_samples:
            raise ValueError("segment is shorter than one complete configured window")
        starts = list(range(0, len(values) - window_samples + 1, stride))
        tail_samples = len(values) - (starts[-1] + window_samples)
        for window_index, start in enumerate(starts):
            stop = start + window_samples
            window_values = values[start:stop]
            window_times = times[start:stop]
            features = _features(window_values, window_times, target_rate)
            first = samples[0]
            meta: dict[str, object] = {
                "pipeline_version": PIPELINE_VERSION,
                "source_sample_rate_hz": source_rate,
                "observed_timestamp_rate_hz": observed_rate,
                "timestamp_rate_relative_error": rate_relative_error,
                "timestamp_rate_tolerance_fraction": 0.05,
                "source_sample_count": len(trace.samples),
                "segment_sample_count": len(values),
                "sample_rate_hz": target_rate,
                "input_unit": first.unit,
                "canonical_unit": "g",
                "sensor_position": first.sensor_position,
                "animal_id": first.animal_id,
                "session_id": first.session_id,
                "evidence_status": first.evidence_status,
                "source_ref": trace.source_ref,
                "window_samples": window_samples,
                "window_index": window_index,
                "window_count": len(starts),
                "discarded_tail_samples": tail_samples,
                "window_duration_s": config.duration_s,
                "overlap_fraction": config.overlap_fraction,
                "stride_samples": stride,
                "max_jitter_fraction": config.max_jitter_fraction,
                "nyquist_hz": target_rate / 2.0,
                "frequency_resolution_hz": target_rate / window_samples,
                "feature_schema": FEATURE_NAMES,
                **resample_meta,
            }
            output.append(FeatureWindow(
                FEATURE_NAMES,
                tuple(float(features[name]) for name in FEATURE_NAMES),
                float(window_times[0]),
                float(window_times[-1]),
                tuple(sorted(meta.items())),
            ))
    return tuple(output)


def _validate_config(config: WindowConfig) -> None:
    if type(config) is not WindowConfig:
        raise ValueError("config must be a WindowConfig")
    _finite_positive(config.duration_s, "duration_s")
    overlap = _finite_number(config.overlap_fraction, "overlap_fraction")
    if not (0 <= overlap < 1):
        raise ValueError("overlap_fraction must be finite and in [0, 1)")
    jitter = _finite_number(config.max_jitter_fraction, "max_jitter_fraction")
    if not (0 <= jitter <= 0.5):
        raise ValueError("max_jitter_fraction must be finite and in [0, 0.5]")
    if config.target_sample_rate_hz is not None:
        _finite_positive(config.target_sample_rate_hz, "target_sample_rate_hz")


def _validate_sample(sample: SignalSample) -> tuple[SignalSample, np.ndarray]:
    if type(sample) is not SignalSample:
        raise ValueError("samples must be SignalSample instances")
    if sample.unit not in _UNIT_TO_G:
        raise ValueError(f"unsupported acceleration unit: {sample.unit!r}")
    for name in ("animal_id", "session_id", "sensor_position", "evidence_status"):
        value = getattr(sample, name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    timestamp = _finite_number(sample.timestamp_s, "timestamp_s")
    xyz = np.asarray([
        _finite_number(sample.x, "x"),
        _finite_number(sample.y, "y"),
        _finite_number(sample.z, "z"),
    ], dtype=np.float64) * _UNIT_TO_G[sample.unit]
    # Frozen dataclass prevents ordinary mutation, but reject booleans as numeric inputs.
    if not math.isfinite(timestamp) or not np.isfinite(xyz).all():
        raise ValueError("sample values must be finite")
    return sample, xyz


def _validate_clock(
    times: np.ndarray, rate: float, jitter_fraction: float
) -> tuple[float, float]:
    if len(times) < 2:
        raise ValueError("at least two ordered timestamps are required per segment")
    intervals = np.diff(times)
    if not np.isfinite(intervals).all() or np.any(intervals <= 0):
        raise ValueError("timestamps must be finite and strictly increasing")
    nominal = 1.0 / rate
    median = float(np.median(intervals))
    relative_error = (1.0 / median) / rate - 1.0
    if abs(relative_error) > 0.05:
        raise ValueError("declared sample_rate_hz conflicts with timestamp intervals by more than 5%")
    if np.any(intervals > nominal * 1.5):
        raise ValueError("timestamp gap exceeds 1.5 nominal sample periods")
    if np.any(np.abs(intervals - median) > median * jitter_fraction):
        raise ValueError("timestamp jitter exceeds max_jitter_fraction")
    return 1.0 / median, relative_error


def _resample(
    values: np.ndarray, times: np.ndarray, source_rate: float, target_rate: float
) -> tuple[np.ndarray, np.ndarray, tuple[int, int, bool]]:
    intervals = np.diff(times)
    nominal = 1.0 / source_rate
    jittered = bool(np.any(np.abs(intervals - nominal) > nominal * 1e-9))
    if jittered:
        regular_times = times[0] + np.arange(len(times), dtype=np.float64) * nominal
        values = np.column_stack([
            np.interp(regular_times, times, values[:, axis]) for axis in range(3)
        ])
        times = regular_times
    fraction = Fraction(target_rate / source_rate).limit_denominator(1000)
    actual_rate = source_rate * fraction.numerator / fraction.denominator
    if abs(actual_rate - target_rate) > target_rate * 1e-6:
        raise ValueError("target/source rate ratio cannot be represented within 1 ppm")
    # scipy.signal.resample_poly applies a zero-phase low-pass FIR before decimation.
    resampled = resample_poly(
        values, fraction.numerator, fraction.denominator, axis=0,
        window=("kaiser", 5.0), padtype="constant",
    )
    resampled_times = times[0] + np.arange(len(resampled), dtype=np.float64) / actual_rate
    valid = resampled_times <= times[-1] + 1e-12
    return resampled[valid], resampled_times[valid], (
        fraction.numerator, fraction.denominator, jittered
    )


def _features(values: np.ndarray, times: np.ndarray, rate: float) -> dict[str, float]:
    means = np.mean(values, axis=0)
    centered = values - means
    magnitude = np.linalg.norm(values, axis=1)
    derivative = np.diff(values, axis=0) / np.diff(times)[:, None]
    spectrum = np.fft.rfft(centered, axis=0)
    power = np.sum(np.abs(spectrum) ** 2, axis=1)
    frequencies = np.fft.rfftfreq(len(values), d=1.0 / rate)
    dominant_index = int(np.argmax(power[1:]) + 1)  # DC is excluded by construction.
    energy = float(np.sum(np.sum(values * values, axis=1)) / rate)
    return {
        "mean_x_g": float(means[0]), "mean_y_g": float(means[1]), "mean_z_g": float(means[2]),
        "std_x_g": float(np.std(values[:, 0])), "std_y_g": float(np.std(values[:, 1])),
        "std_z_g": float(np.std(values[:, 2])),
        "rms_x_g": float(np.sqrt(np.mean(values[:, 0] ** 2))),
        "rms_y_g": float(np.sqrt(np.mean(values[:, 1] ** 2))),
        "rms_z_g": float(np.sqrt(np.mean(values[:, 2] ** 2))),
        "mean_magnitude_g": float(np.mean(magnitude)),
        "rms_magnitude_g": float(np.sqrt(np.mean(magnitude ** 2))),
        "sma_g": float(np.mean(np.sum(np.abs(values), axis=1))),
        "jerk_rms_g_per_s": float(np.sqrt(np.mean(np.sum(derivative ** 2, axis=1)))),
        "energy_g2_s": energy,
        "dominant_frequency_hz": (
            float(frequencies[dominant_index]) if float(np.max(power[1:])) > 1e-24 else 0.0
        ),
    }


def _sample_key(sample: SignalSample) -> tuple[str, str, str, str, str]:
    return (
        sample.animal_id,
        sample.session_id,
        sample.sensor_position,
        sample.evidence_status,
        sample.unit,
    )


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _finite_positive(value: object, name: str) -> float:
    result = _finite_number(value, name)
    if result <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return result
