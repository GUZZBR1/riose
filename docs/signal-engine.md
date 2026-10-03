# XYZ signal engine

`riose.products.ear_tag.signal` is an offline feature transformation API. It
accepts ordered XYZ samples and returns fixed-schema feature windows. It does
not assign behavior, diagnose an animal, validate a sensor, or upgrade the
source evidence. `SIMULATED` input remains `SIMULATED` in every result.

## Example

```python
from riose.products.ear_tag.signal import (
    SignalSample, SignalTrace, WindowConfig, extract_features,
)

samples = tuple(
    SignalSample(i / 12.5, 0.1, 0.0, 1.0, "tag-1", "session-1",
                 "collar", "g", "SIMULATED")
    for i in range(100)
)
windows = extract_features(
    SignalTrace(samples, sample_rate_hz=12.5, source_ref="fixture:static"),
    WindowConfig(duration_s=4.0, overlap_fraction=0.5),
)
```

## Contract and features

Timestamps are finite seconds on a single clock. XYZ axes are ordered `x,y,z`;
each sample states its unit (`g`, `mg`, or `m/s^2`), animal, session, sensor
position, and evidence status. Units are converted to `g` (`1 g = 1000 mg =
9.80665 m/s^2`). Mixed units in one trace are rejected. A declared positive
sample rate is required; median timestamp spacing must agree within 5%. The
observed timestamp rate and difference from the declared rate are recorded,
including accepted differences within that tolerance.
Timestamps must strictly increase; gaps above 1.5 nominal periods and interval
jitter above `max_jitter_fraction` (default 15%) are rejected. Optional
`full_scale` is expressed in the trace's declared unit; reaching it rejects the
trace as potentially saturated.

Runs split whenever animal, session, sensor position, or evidence status
changes. No window crosses one of those boundaries. A run too short for a full
window is rejected. Trailing samples that do not fit a complete window are
reported as `discarded_tail_samples`. Window size is rounded to the nearest
sample count at the output rate; stride is rounded from `window_samples *
(1-overlap_fraction)` and is at least one sample.

The vector order is `FEATURE_NAMES`:

| Feature | Definition | Unit |
|---|---|---|
| `mean_{x,y,z}_g` | Per-axis arithmetic mean | g |
| `std_{x,y,z}_g` | Population standard deviation | g |
| `rms_{x,y,z}_g` | Square root of mean squared per-axis acceleration | g |
| `mean_magnitude_g` | Mean of `sqrt(x²+y²+z²)` | g |
| `rms_magnitude_g` | Root mean square of vector magnitude | g |
| `sma_g` | Mean of `abs(x)+abs(y)+abs(z)` | g |
| `jerk_rms_g_per_s` | RMS of the XYZ finite-difference derivative norm | g/s |
| `energy_g2_s` | `sum(x²+y²+z²) / sample_rate_hz` | g²·s |
| `dominant_frequency_hz` | Largest non-DC summed XYZ FFT power bin; zero for a constant window | Hz |

FFT bins use the output sampling rate and cannot exceed Nyquist (`rate/2`). The
dominant bin is a descriptive signal statistic, not an activity label or a
biologically validated frequency. Sensor-axis means and jerk depend on
orientation; `sensor_position` is retained, and mount changes split runs.
FFT spacing is `sample_rate_hz / window_samples`; short windows therefore give
coarse frequency resolution. Frequencies already aliased in the input cannot
be recovered or detected from XYZ samples alone.

## Resampling and reproducibility

No resampling occurs unless `target_sample_rate_hz` is explicitly supplied.
Upsampling is rejected because interpolation cannot add measured information.
Downsampling uses `scipy.signal.resample_poly`, a polyphase FIR anti-alias
filter (Kaiser window, beta 5.0, constant padding). Accepted timestamp jitter is first
linearly interpolated to the declared uniform source grid. Gaps and rate
conflicts are rejected before resampling. The rate ratio must be representable
to within 1 ppm by integer polyphase factors (denominator at most 1000).

Every output includes pipeline version, source and final rate, filter/method,
polyphase factors, jitter-correction flag, window parameters, feature schema,
Nyquist, unit conversion, identity, sensor position, evidence status, and
source reference. The numerical implementation is deterministic for the same
Python/NumPy/SciPy platform and inputs; floating-point results can vary in the
last bits across library/platform builds. It is intended for offline analysis,
not yet benchmarked on STM32.

Run the numerical suite with `uv run pytest tests/ear_tag/test_signal_engine.py
-q`. Generate an informative workstation benchmark with
`uv run python benchmarks/benchmark_signal_engine.py`; its `EXPERIMENTAL`
classification is not a hardware performance claim.
