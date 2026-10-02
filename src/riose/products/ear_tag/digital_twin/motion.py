"""Deterministic synthetic motion-profile generation."""

from __future__ import annotations

import csv
import math
import random
from pathlib import Path
from typing import Any

def generate_motion_profiles(path: Path, seed: int = 7, sample_rate_hz: float = 12.5,
                             samples_per_profile: int = 100) -> dict[str, Any]:
    """Generate synthetic sensor inputs for the virtual IMU, not animal data."""
    rng = random.Random(seed)
    names = ("STATIC", "WALK", "RUN", "IMPACT", "RANDOM_MOVEMENT")
    rows: list[dict[str, Any]] = []
    for profile_index, name in enumerate(names):
        for index in range(samples_per_profile):
            t = index / sample_rate_hz
            noise = lambda scale: rng.uniform(-scale, scale)
            if name == "STATIC":
                x, y, z = noise(8), noise(8), 1000 + noise(8)
            elif name == "WALK":
                x, y, z = 150 * math.sin(2 * math.pi * 1.5 * t), 60 * math.sin(2 * math.pi * 0.75 * t), 1000 + 90 * math.cos(2 * math.pi * 1.5 * t)
            elif name == "RUN":
                x, y, z = 420 * math.sin(2 * math.pi * 3.0 * t), 180 * math.sin(2 * math.pi * 1.5 * t), 1000 + 280 * math.cos(2 * math.pi * 3.0 * t)
            elif name == "IMPACT":
                pulse = 1800.0 if index == samples_per_profile // 2 else 0.0
                x, y, z = pulse + noise(12), noise(12), 1000 + pulse + noise(12)
            else:
                x, y, z = rng.uniform(-1500, 1500), rng.uniform(-1500, 1500), rng.uniform(-500, 2500)
            rows.append({"profile": name, "sample_index": index, "timestamp_s": round(t, 6),
                         "x_mg": round(x), "y_mg": round(y), "z_mg": round(z),
                         "sample_rate_hz": sample_rate_hz, "seed": seed,
                         "status": "SIMULATED", "animal_measurement": False})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return {"status": "COMPLETED", "result_class": "SIMULATED", "profiles": list(names),
            "sample_rate_hz": sample_rate_hz, "samples_per_profile": samples_per_profile,
            "seed": seed, "path": str(path), "physical_hardware_used": False}
