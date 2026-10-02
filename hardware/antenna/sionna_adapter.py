"""Small deterministic tag-to-receiver scenarios for optional Sionna RT runs.

The obstacle and antenna pattern are intentionally simplified sensitivity
models. They are not a farm scene, antenna validation, or openEMS substitute.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


SCENARIO_SETTINGS = {
    "TAG_TO_RECEIVER_10M": {"obstacle": False, "orientation_rad": 0.0},
    "TAG_TO_RECEIVER_WITH_OBSTACLE": {"obstacle": True, "orientation_rad": 0.0},
    "TAG_TO_RECEIVER_ORIENTATION_VARIANT": {"obstacle": False, "orientation_rad": math.pi / 2},
}

# A 10 cm thick, 4 m wide, 3 m high rectangular obstacle centered between
# tag and receiver. Its generic dielectric parameters are sensitivity inputs.
OBSTACLE_OBJ = """\
v -0.05 -2 -1.5
v 0.05 -2 -1.5
v 0.05 2 -1.5
v -0.05 2 -1.5
v -0.05 -2 1.5
v 0.05 -2 1.5
v 0.05 2 1.5
v -0.05 2 1.5
f 1 4 3 2
f 5 6 7 8
f 1 2 6 5
f 2 3 7 6
f 3 4 8 7
f 4 1 5 8
"""


def _frequency_hz(spec_path: Path | None) -> tuple[float, str | None]:
    if spec_path is None:
        return 915_000_000.0, None
    import yaml

    raw = spec_path.read_bytes()
    spec = yaml.safe_load(raw) or {}
    record = spec.get("antenna", {}).get("center_frequency_hz", {})
    frequency = record.get("value", 915_000_000) if isinstance(record, dict) else 915_000_000
    if isinstance(frequency, bool) or not isinstance(frequency, (int, float)) or not math.isfinite(frequency) or frequency <= 0:
        raise ValueError("antenna.center_frequency_hz must be a positive finite number")
    return float(frequency), hashlib.sha256(raw).hexdigest()


def simulate(*, scenario: str, spec_path: Path | None, output_dir: Path) -> dict[str, Any]:
    """Run one small Sionna RT path solve and return solver-derived evidence."""
    if scenario not in SCENARIO_SETTINGS:
        raise ValueError(f"Unsupported Sionna RT scenario: {scenario}")

    import mitsuba as mi
    from sionna.rt import (PathSolver, PlanarArray, RadioMaterial, Receiver,
                           SceneObject, Transmitter, load_scene)

    frequency_hz, spec_hash = _frequency_hz(spec_path)
    settings = SCENARIO_SETTINGS[scenario]
    output_dir.mkdir(parents=True, exist_ok=True)

    scene = load_scene()
    scene.frequency = frequency_hz
    scene.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="dipole", polarization="V")
    scene.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="dipole", polarization="V")

    obstacle_hash = None
    if settings["obstacle"]:
        obstacle_path = output_dir / "obstacle.obj"
        obstacle_path.write_text(OBSTACLE_OBJ, encoding="utf-8")
        obstacle_hash = hashlib.sha256(obstacle_path.read_bytes()).hexdigest()
        obstacle = SceneObject(
            fname=str(obstacle_path),
            name="riose_sensitivity_obstacle",
            radio_material=RadioMaterial(
                name="riose_assumed_obstacle_material",
                relative_permittivity=5.0,
                conductivity=0.01,
                thickness=0.1,
            ),
            position=mi.Point3f(5.0, 0.0, 1.5),
        )
        scene.add(obstacle)

    tx = Transmitter(name="tag", position=[0.0, 0.0, 1.5],
                     orientation=[0.0, 0.0, settings["orientation_rad"]])
    rx = Receiver(name="receiver", position=[10.0, 0.0, 1.5])
    scene.add([tx, rx])

    # Sionna RT chooses the supported Mitsuba backend on import. A fixed seed
    # and deterministic solver make the small comparison reproducible.
    paths = PathSolver(deterministic=True)(
        scene, max_depth=2, max_num_paths_per_src=1_000, samples_per_src=10_000,
        synthetic_array=True, seed=42,
    )
    interactions = paths.interactions
    path_count = int(interactions.shape[-1])
    variant = mi.variant()

    evidence = {
        "solver": "Sionna RT PathSolver",
        "solver_version": _installed_version(),
        "mitsuba_variant": variant,
        "seed": 42,
        "deterministic": True,
        "frequency_hz": frequency_hz,
        "scene": "empty free-space scene plus optional single rectangular sensitivity obstacle",
        "obstacle_sha256": obstacle_hash,
        "spec_sha256": spec_hash,
    }
    metrics = {"path_count": path_count, "tag_receiver_distance_m": 10.0}
    row = {
        "schema_version": "riose.sionna.scenario/v1",
        "scenario": scenario,
        "status": "COMPLETED",
        "result_class": "SIMULATED",
        "metrics": metrics,
        "evidence": evidence,
        "assumptions": [
            "Single isotropic dipole model; no ear-tag antenna pattern or enclosure geometry",
            "Generic obstacle dielectric is an assumed sensitivity input",
            "Ray-tracing output is exploratory and is not measured link performance",
        ],
    }
    (output_dir / f"{scenario.lower()}.json").write_text(
        json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"status": "COMPLETED", "metrics": metrics, "evidence": evidence}


def _installed_version() -> str | None:
    from importlib import metadata

    for distribution in ("sionna-rt", "sionna"):
        try:
            return metadata.version(distribution)
        except metadata.PackageNotFoundError:
            continue
    return None
