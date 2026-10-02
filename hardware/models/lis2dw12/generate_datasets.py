#!/usr/bin/env python3
"""Generate explicitly simulated LIS2DW12-compatible acceleration examples."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from pathlib import Path

PROFILES = ("STATIC", "WALK", "RUN", "IMPACT", "RANDOM_MOVEMENT")
MAX_ODR_HZ = 1600.0


def _sample(
    profile: str,
    index: int,
    count: int,
    rate: float,
    rng: random.Random,
    random_walk: list[int],
) -> tuple[int, int, int]:
    t = index / rate
    if profile == "STATIC":
        x, y, z = 0.0, 0.0, 1000.0
    elif profile == "WALK":
        phase = 2 * math.pi * 1.8 * t
        x, y, z = 240 * math.sin(phase), 90 * math.sin(phase + 0.7), 1000 + 160 * math.cos(phase)
    elif profile == "RUN":
        phase = 2 * math.pi * 3.2 * t
        x, y, z = 780 * math.sin(phase), 420 * math.sin(phase + 0.9), 1000 + 560 * math.cos(phase)
    elif profile == "IMPACT":
        x = y = 0.0
        z = 1000.0
        impact_at = count // 2
        distance = index - impact_at
        if abs(distance) <= 2:
            pulse = (1.0, 0.45, 0.18)[abs(distance)]
            x, y, z = 1500 * pulse, -900 * pulse, 1000 + 2400 * pulse
    else:
        # Bounded seeded random walk, kept illustrative and independent of livestock data.
        for axis in range(3):
            target = (0, 0, 1000)[axis]
            random_walk[axis] += rng.randint(-90, 90) + int((target - random_walk[axis]) * 0.18)
            random_walk[axis] = max(-1800, min(1800, random_walk[axis]))
        x, y, z = random_walk

    if profile != "RANDOM_MOVEMENT":
        x += rng.randint(-2, 2)
        y += rng.randint(-2, 2)
        z += rng.randint(-2, 2)
    return tuple(max(-16000, min(16000, round(v))) for v in (x, y, z))


def generate_datasets(output_dir: Path, sample_rate_hz: float = 12.5, samples: int = 128, seed: int = 1) -> dict:
    """Write five CSV traces plus a provenance manifest and return the manifest."""
    if not math.isfinite(sample_rate_hz) or not (0 < sample_rate_hz <= MAX_ODR_HZ):
        raise ValueError(f"sample_rate_hz must be finite and in (0, {MAX_ODR_HZ:g}]")
    if not isinstance(samples, int) or isinstance(samples, bool) or not (1 <= samples <= 1_000_000):
        raise ValueError("samples must be an integer in [1, 1000000]")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("seed must be a non-negative integer")

    output_dir.mkdir(parents=True, exist_ok=True)
    datasets = []
    for profile_index, profile in enumerate(PROFILES):
        # Independent streams make one profile's output stable if profile order changes.
        rng = random.Random(seed + profile_index * 1_000_003)
        random_walk = [0, 0, 1000]
        filename = f"{profile.lower()}.csv"
        with (output_dir / filename).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(("timestamp_s", "x_g", "y_g", "z_g"))
            for index in range(samples):
                x, y, z = _sample(profile, index, samples, sample_rate_hz, rng, random_walk)
                writer.writerow((f"{index / sample_rate_hz:.9f}", f"{x / 1000:.6f}",
                                 f"{y / 1000:.6f}", f"{z / 1000:.6f}"))
        datasets.append({
            "name": profile,
            "file": filename,
            "samples": samples,
            "sample_rate_hz": sample_rate_hz,
            "unit": "g",
            "seed": seed,
            "status": "SIMULATED",
            "source": "RIOSE deterministic synthetic profile generator; not measured animal data",
        })

    manifest = {
        "schema_version": 1,
        "provenance": "SIMULATED",
        "description": "Illustrative acceleration signals for firmware and sensor-model tests; not measured bovine behavior.",
        "datasets": datasets,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "datasets")
    parser.add_argument("--sample-rate-hz", type=float, default=12.5)
    parser.add_argument("--samples", type=int, default=128)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    manifest = generate_datasets(args.output, args.sample_rate_hz, args.samples, args.seed)
    print(f"Generated {len(manifest['datasets'])} SIMULATED datasets in {args.output}")


if __name__ == "__main__":
    main()
