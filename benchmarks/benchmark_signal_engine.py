"""Informative, reproducible workstation benchmark; not an STM32 claim."""

from __future__ import annotations

import json
import platform
import statistics
import time
import tracemalloc

import numpy as np
import scipy

from riose.products.ear_tag.signal import SignalSample, SignalTrace, WindowConfig, extract_features


def main() -> None:
    rate = 12.5
    count = 1250
    timestamps = np.arange(count) / rate
    samples = tuple(
        SignalSample(float(t), float(np.sin(2 * np.pi * 1.5 * t)),
                     float(np.sin(2 * np.pi * 0.75 * t)),
                     float(1 + 0.2 * np.cos(2 * np.pi * 1.5 * t)),
                     "benchmark-animal", "benchmark-session", "collar", "g", "SIMULATED")
        for t in timestamps
    )
    trace = SignalTrace(samples, rate, "benchmark:deterministic-1.5Hz")
    config = WindowConfig(duration_s=4.0, overlap_fraction=0.5)
    # Warm up import/FFT internals before timing.
    expected = extract_features(trace, config)
    timings_ms = []
    tracemalloc.start()
    for _ in range(20):
        started = time.perf_counter()
        result = extract_features(trace, config)
        timings_ms.append((time.perf_counter() - started) * 1000)
        assert result == expected
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(json.dumps({
        "classification": "EXPERIMENTAL",
        "environment": {"platform": platform.platform(), "python": platform.python_version(),
                        "machine": platform.machine(), "numpy": np.__version__,
                        "scipy": scipy.__version__},
        "samples": count,
        "windows_per_run": len(expected),
        "runs": len(timings_ms),
        "median_ms": statistics.median(timings_ms),
        "p95_ms": sorted(timings_ms)[int(0.95 * (len(timings_ms) - 1))],
        "peak_traced_bytes": peak_bytes,
        "hardware_target_benchmarked": False,
    }, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
