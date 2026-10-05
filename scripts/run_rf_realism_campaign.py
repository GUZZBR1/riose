#!/usr/bin/env python3
"""Run the bounded RF realism campaign against the pinned FREQUENCIA APIs.

The FREQUENCIA checkout remains external. Set FREQUENCIA_ROOT and run this
script with its Sionna-enabled Python environment. Raw artifacts are written
outside Git by default.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time
from typing import Any


SEED = 20261005
FREQUENCY_HZ = 915_000_000
BANDWIDTH_HZ = 125_000
TX_POWER_DBM = 14.0
COVERAGE_DBM = -127.0
NOISE_FIGURE_DB = 6.0
SNR_THRESHOLD_DB = -10.0
FREQUENCIA_SHA = "ba2bdabf003722aae8292580e048f7092d0356d6"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {key: None for key in ("min", "p10", "p50", "mean", "p90", "p95", "max")}
    ordered = sorted(values)

    def percentile(q: float) -> float:
        position = (len(ordered) - 1) * q
        low, high = math.floor(position), math.ceil(position)
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

    return {"min": min(ordered), "p10": percentile(.10), "p50": percentile(.50),
            "mean": statistics.fmean(ordered), "p90": percentile(.90),
            "p95": percentile(.95), "max": max(ordered)}


def gateway_sites(points: list[tuple[float, float, float]], prefix: str = "GW") -> tuple[Any, ...]:
    from farm.virtual_farm import GatewaySite
    return tuple(GatewaySite(f"{prefix}-{index + 1}", point, f"rx-{prefix}-{index + 1}")
                 for index, point in enumerate(points))


def one_tag_scenario(base: Any, position: tuple[float, float, float],
                     gateways: tuple[Any, ...], *, seed: int = SEED) -> Any:
    from farm.virtual_farm import Animal
    config = replace(base.config, animals=1, duration_s=0, dt_s=1,
                     seed=seed, frequency_hz=FREQUENCY_HZ,
                     bandwidth_hz=BANDWIDTH_HZ, tx_power_dbm=TX_POWER_DBM)
    return replace(base, config=config, animals=(Animal("animal-001", "tx-001"),),
                   gateways=gateways,
                   ground_truth=({"animal_id": "animal-001", "timestamp_s": 0,
                                  "position_m": list(position)},))


def wall_mesh(path: Path) -> None:
    path.write_text(
        "ply\nformat ascii 1.0\ncomment Synthetic vertical RF test wall; ENU metres\n"
        "element vertex 4\nproperty float x\nproperty float y\nproperty float z\n"
        "element face 2\nproperty list uchar int vertex_indices\nend_header\n"
        "500 400 0\n500 600 0\n500 600 20\n500 400 20\n"
        "3 0 1 2\n3 0 2 3\n", encoding="ascii")


def wall_reflector_mesh(path: Path, reflector_y: float) -> None:
    """Write a synthetic blocker and separate finite specular test panel."""
    quads = (
        ((500, 400, 0), (500, 600, 0), (500, 600, 20), (500, 400, 20)),
        ((0, reflector_y, 0), (1000, reflector_y, 0),
         (1000, reflector_y, 20), (0, reflector_y, 20)),
    )
    vertices = [vertex for quad in quads for vertex in quad]
    faces = [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)]
    with path.open("w", encoding="ascii") as stream:
        stream.write("ply\nformat ascii 1.0\ncomment Synthetic controlled RF geometry; ENU metres\n")
        stream.write("element vertex 8\nproperty float x\nproperty float y\nproperty float z\n")
        stream.write("element face 4\nproperty list uchar int vertex_indices\nend_header\n")
        for x, y, z in vertices:
            stream.write(f"{x} {y} {z}\n")
        for face in faces:
            stream.write(f"3 {face[0]} {face[1]} {face[2]}\n")


def segment_crosses_wall(tx: tuple[float, float, float], rx: tuple[float, float, float]) -> bool:
    """Check direct segment crossing against the declared finite wall prism."""
    dx = rx[0] - tx[0]
    if dx == 0:
        return False
    t = (500.0 - tx[0]) / dx
    if not 0.0 < t < 1.0:
        return False
    y = tx[1] + t * (rx[1] - tx[1])
    z = tx[2] + t * (rx[2] - tx[2])
    return 400.0 <= y <= 600.0 and 0.0 <= z <= 20.0


def classify_geometric_path(direct_blocked: bool, status: str,
                            received_power_dbm: float | None,
                            paths: list[dict[str, Any]], *,
                            tx: tuple[float, float, float] | None = None,
                            rx: tuple[float, float, float] | None = None,
                            reflector_y_m: float | None = None) -> str:
    """Require backend state and path evidence before labeling geometric NLOS."""
    if status == "NO_PATH":
        return "NO_PATH"
    if not direct_blocked and status == "LOS" and received_power_dbm is not None:
        return "LOS_RECEIVED"
    if (direct_blocked and status == "NLOS" and received_power_dbm is not None
            and tx is not None and rx is not None and reflector_y_m is not None):
        for path in paths:
            for interaction in path.get("interactions", []):
                if interaction.get("type") != "specular":
                    continue
                vertex = interaction.get("vertex_m")
                if not isinstance(vertex, list) or len(vertex) != 3:
                    continue
                point = tuple(float(value) for value in vertex)
                if (abs(point[1] - reflector_y_m) > 0.02 or not 0 <= point[0] <= 1000
                        or not 0 <= point[2] <= 20):
                    continue
                if (abs(point[0] - 500.0) < 0.02 and 400.0 <= point[1] <= 600.0
                        and 0.0 <= point[2] <= 20.0):
                    continue
                if (not segment_crosses_wall(tx, point)
                        and not segment_crosses_wall(point, rx)):
                    return "GEOMETRIC_NLOS_WITH_RECEIVED_PATH"
    return "UNPROVEN"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frequencia-root", type=Path,
                        default=Path(os.environ.get("FREQUENCIA_ROOT", "")))
    parser.add_argument("--output", type=Path,
                        default=Path.home() / ".cache/RIOSE/rf_realism_campaign")
    parser.add_argument("--sionna", action="store_true",
                        help="run Sionna RT (requires FREQUENCIA's pinned Python environment)")
    parser.add_argument("--gap-closure-only", action="store_true",
                        help="run only paired LOS, blocked NLOS/no-path controls, and a small reflector sweep")
    args = parser.parse_args()
    engine = args.frequencia_root.resolve()
    if not engine.is_dir():
        parser.error("--frequencia-root or FREQUENCIA_ROOT must identify the clean pinned FREQUENCIA worktree")
    actual_sha = subprocess.check_output(["git", "-C", str(engine), "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "-C", str(engine), "status", "--porcelain=v1"], text=True).strip())
    if actual_sha != FREQUENCIA_SHA or dirty:
        parser.error(f"FREQUENCIA must be clean at {FREQUENCIA_SHA}; actual={actual_sha} dirty={dirty}")
    sys.path.insert(0, str(engine))
    from farm.reference import load_reference_config
    from farm.virtual_farm import FarmConfig, build_default_farm
    from rf.channel import ChannelConfig, simulate_link
    if args.sionna:
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
        from rf.sionna_backend import run_sionna_snapshot
        from importlib.metadata import version
        sionna_version = version("sionna-rt")
        package_versions = {name: version(name) for name in ("sionna-rt", "mitsuba", "drjit", "numpy")}
    else:
        run_sionna_snapshot = None
        sionna_version = None
        package_versions = {}

    args.output = args.output.expanduser().resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    artifact_dir = args.output / "geometry"
    artifact_dir.mkdir(exist_ok=True)
    base = build_default_farm(FarmConfig(animals=1, duration_s=0, frequency_hz=FREQUENCY_HZ,
                                        bandwidth_hz=BANDWIDTH_HZ, tx_power_dbm=TX_POWER_DBM,
                                        seed=SEED))
    channel = ChannelConfig(FREQUENCY_HZ, BANDWIDTH_HZ, TX_POWER_DBM)
    raw: list[dict[str, Any]] = []
    run_counts = {"analytic": 0, "sionna-rt": 0, "failed": 0, "no_path": 0}
    sionna_cache: dict[str, dict[str, object]] = {}
    start = time.monotonic()
    riose_root = Path(__file__).resolve().parents[1]
    riose_revision = subprocess.check_output(["git", "-C", str(riose_root), "rev-parse", "HEAD"],
                                               text=True).strip()
    riose_dirty = bool(subprocess.check_output(["git", "-C", str(riose_root), "status",
                                                "--porcelain=v1"], text=True).strip())

    def record_analytic(case: str, tx: tuple[float, float, float],
                        rx: tuple[float, float, float], *, group: str = "") -> dict[str, Any]:
        run_counts["analytic"] += 1
        link = simulate_link(tx, rx, channel)
        power = float(link["received_power_dbm"])
        record = {"case": case, "group": group, "backend": "ANALYTIC_SIMULATION",
                  "status": "PATH_AVAILABLE", "tx_position_m": list(tx), "rx_position_m": list(rx),
                  "frequency_hz": FREQUENCY_HZ, "bandwidth_hz": BANDWIDTH_HZ,
                  "tx_power_dbm": TX_POWER_DBM, "seed_requested": SEED,
                  "seed_effective": None, "power_dbm": power,
                  "path_loss_db": TX_POWER_DBM - power,
                  "snr_db_engineering_estimate": power - (-174 + 10 * math.log10(BANDWIDTH_HZ)
                                                        + NOISE_FIGURE_DB),
                  "coverage_engineering_assumption": power >= COVERAGE_DBM,
                  "delay_s": link["delay_s"], "path_count": link["multipath_count"],
                  "paths": link["paths"], "cir": "NOT_PROVIDED_AS_CIR",
                  "cfr": {"offsets_hz": link["cfr_frequency_offsets_hz"],
                          "magnitude_db": link["cfr_magnitude_db"]},
                  "requested": {"frequency_hz": FREQUENCY_HZ, "bandwidth_hz": BANDWIDTH_HZ,
                                "tx_power_dbm": TX_POWER_DBM, "tx_position_m": list(tx),
                                "rx_position_m": list(rx), "seed": SEED},
                  "effective": {"model": link["channel_model"],
                                "reflection_coefficient": channel.reflection_coefficient,
                                "cfr_points": channel.cfr_points,
                                "seed": "NOT_CONSUMED_DETERMINISTIC_MODEL",
                                "antenna": "SCALAR_GAIN_NOT_MODELED"},
                  "los_nlos": "LOS", "classification": "SIMULATED"}
        if group == "combined_stress:NLOS" or group.startswith("gap_closure:NLOS"):
            record["requested_environment"] = "synthetic vertical wall crossing direct path"
            record["effective_obstacle"] = "NOT_SUPPORTED_IGNORED_BY_ANALYTIC_BACKEND"
        raw.append(record)
        return record

    def record_sionna(case: str, tx: tuple[float, float, float],
                      gateways: tuple[Any, ...], *, mesh: Path, obstacle: Path | None = None,
                      los: bool = True, reflection: bool = True, group: str = "",
                      primary_only: bool = False,
                      reflector_y_m: float | None = None) -> list[dict[str, Any]]:
        if run_sionna_snapshot is None:
            return []
        run_counts["sionna-rt"] += 1
        scenario = one_tag_scenario(base, tx, gateways)
        geometry_key = tuple((gateway.gateway_id, gateway.position) for gateway in gateways)
        cache_key = (group + ":" + str(mesh) + ":" + str(obstacle) + ":" + str(los)
                     + ":" + str(reflection) + ":" + repr(geometry_key))
        cache = sionna_cache.setdefault(cache_key, {})
        try:
            value = run_sionna_snapshot(scenario, mesh_path=mesh, obstacle_mesh_path=obstacle,
                                        max_depth=1, los=los, specular_reflection=reflection,
                                        cfr_points=5, max_num_paths_per_src=200,
                                        samples_per_src=200, scene_cache=cache)
            records = []
            for link_index, link in enumerate(value["records"]):
                status = link["los_nlos"]
                if status == "NO_PATH":
                    run_counts["no_path"] += 1
                power = link["received_power_dbm"]
                power_num = float(power) if power is not None else None
                rx = tuple(link["rx_position_m"])
                item = {"case": case, "group": group, "backend": "SIONNA_RT_SIMULATION",
                        "status": status, "tx_position_m": list(tx), "rx_position_m": list(rx),
                        "frequency_hz": value["frequency_hz"], "bandwidth_hz": value["bandwidth_hz"],
                        "tx_power_dbm": value["tx_power_dbm"], "seed_requested": SEED,
                        "seed_effective": scenario.config.seed, "power_dbm": power_num,
                        "path_loss_db": TX_POWER_DBM - power_num if power_num is not None else None,
                        "snr_db_engineering_estimate": (power_num - (-174 + 10 * math.log10(BANDWIDTH_HZ)
                                                                  + NOISE_FIGURE_DB)
                                                         if power_num is not None else None),
                        "coverage_engineering_assumption": power_num >= COVERAGE_DBM if power_num is not None else None,
                        "delay_s": min((float(p["delay_s"]) for p in link["paths"]), default=None),
                        "path_count": len(link["paths"]), "paths": link["paths"],
                        "cir": link["cir"], "cfr": link["cfr"], "los_nlos": status,
                        "requested": {"los": los, "specular_reflection": reflection,
                                      "max_depth": 1, "samples_per_src": 200,
                                      "max_num_paths_per_src": 200},
                        "effective": {"los": value["los"], "specular_reflection": value["specular_reflection"],
                                      "max_depth": value["max_depth"],
                                      "samples_per_src": value["samples_per_src"],
                                      "max_num_paths_per_src": value["max_num_paths_per_src"],
                                      "ground_material": value["ground_material"],
                                      "obstacle_material": value["obstacle_material"],
                                      "obstacle_mesh": value["obstacle_mesh"],
                                      "seed": scenario.config.seed},
                        "classification": "SIMULATED"}
                item["aggregate_population"] = not primary_only or link_index == 0
                if group == "combined_stress:NLOS" or group.startswith("gap_closure:"):
                    item["direct_path_blocked_geometrically"] = (
                        obstacle is not None and segment_crosses_wall(tx, rx))
                    if group.startswith("gap_closure:"):
                        item["requested"]["geometry"] = {
                            "tx_position_m": list(tx), "rx_position_m": list(rx),
                            "blocker": ({"type": "vertical_plane", "x_m": 500.0,
                                         "y_bounds_m": [400.0, 600.0], "z_bounds_m": [0.0, 20.0]}
                                        if obstacle is not None else "ABSENT_IN_CLEAR_CONTROL"),
                            "reflector_y_m": reflector_y_m,
                            "obstacle_mesh_path": str(obstacle) if obstacle is not None else None,
                            "obstacle_mesh_sha256": sha256(obstacle) if obstacle is not None else None,
                        }
                        item["geometric_path_classification"] = classify_geometric_path(
                            item["direct_path_blocked_geometrically"], status,
                            power_num, link["paths"], tx=tx, rx=rx,
                            reflector_y_m=reflector_y_m)
                        if reflector_y_m is not None:
                            item["verified_indirect_path"] = (
                                item["geometric_path_classification"]
                                == "GEOMETRIC_NLOS_WITH_RECEIVED_PATH")
                        item["geometry"] = {
                            "blocker": ({"type": "vertical_plane", "x_m": 500.0,
                                         "y_bounds_m": [400.0, 600.0], "z_bounds_m": [0.0, 20.0]}
                                        if obstacle is not None else "ABSENT_IN_CLEAR_CONTROL"),
                            "reflector_y_m": reflector_y_m,
                            "reflector": ("separate finite vertical plane; synthetic concrete proxy"
                                          if reflector_y_m is not None
                                          else "ABSENT_IN_WALL_ONLY_CONTROL" if obstacle is not None
                                          else None),
                            "obstacle_mesh_sha256": sha256(obstacle) if obstacle is not None else None,
                        }
                if group == "multipath" and not los:
                    item["status_basis"] = "LOS_PATH_DISABLED_BY_SOLVER_CONFIGURATION; NOT_GEOMETRIC_NLOS"
                raw.append(item)
                records.append(item)
            return records
        except Exception as exc:
            run_counts["failed"] += 1
            raw.append({"case": case, "group": group, "backend": "SIONNA_RT_SIMULATION",
                        "status": "SIMULATION_FAILURE", "error": f"{type(exc).__name__}: {exc}",
                        "tx_position_m": list(tx), "seed_requested": SEED,
                        "classification": "SIMULATED"})
            return []

    if args.gap_closure_only:
        if not args.sionna:
            parser.error("--gap-closure-only requires --sionna; no backend substitution is permitted")
        flat = engine / "farm/assets/ground.ply"
        tx = (200.0, 500.0, 8.0)
        gateways = gateway_sites([(800.0, 500.0, 8.0), (800.0, 350.0, 8.0),
                                  (800.0, 650.0, 8.0)], "GAP")
        reflector_meshes: list[Path] = []
        # Identical endpoints/configuration in the clear, wall-only, and wall+panel cases.
        record_analytic("gap_los_control", tx, gateways[0].position, group="gap_closure:LOS_CONTROL")
        record_sionna("gap_los_control", tx, gateways, mesh=flat,
                      group="gap_closure:LOS_CONTROL", primary_only=True)
        wall_only = artifact_dir / "gap_wall_only.ply"
        wall_mesh(wall_only)
        record_analytic("gap_wall_no_path_control", tx, gateways[0].position,
                         group="gap_closure:NO_PATH_CONTROL")
        record_sionna("gap_wall_no_path_control", tx, gateways, mesh=flat, obstacle=wall_only,
                      group="gap_closure:NO_PATH_CONTROL", primary_only=True)
        for reflector_y in (250.0, 300.0, 350.0):
            mesh = artifact_dir / f"gap_wall_reflector_y{int(reflector_y)}.ply"
            wall_reflector_mesh(mesh, reflector_y)
            reflector_meshes.append(mesh)
            case = f"gap_wall_reflector_y{int(reflector_y)}"
            record_analytic(case, tx, gateways[0].position, group="gap_closure:NLOS_RECEIVED")
            record_sionna(case, tx, gateways, mesh=flat, obstacle=mesh,
                          group="gap_closure:NLOS_RECEIVED", primary_only=True,
                          reflector_y_m=reflector_y)

        # Keep the same campaign raw-record and summary evidence structure.
        paired_gap = []
        index_analytic = {(row["case"], tuple(row["rx_position_m"])): row for row in raw
                          if row.get("backend") == "ANALYTIC_SIMULATION"}
        for row in raw:
            if row.get("backend") != "SIONNA_RT_SIMULATION" or row.get("power_dbm") is None:
                continue
            analytic = index_analytic.get((row["case"], tuple(row.get("rx_position_m", []))))
            if analytic and analytic.get("power_dbm") is not None:
                row["paired_model_disagreement_db"] = float(row["power_dbm"]) - float(analytic["power_dbm"])
                paired_gap.append(row["paired_model_disagreement_db"])
        raw_path = args.output / "gap-closure-raw-runs.jsonl"
        with raw_path.open("w", encoding="utf-8") as stream:
            for row in raw:
                stream.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
        summary = {
            "schema_version": "riose.rf-realism-campaign/v1",
            "followup": "B.1 NLOS received and evidence closure",
            "classification": "SIMULATED", "riose_revision": riose_revision,
            "riose_dirty": riose_dirty, "frequencia_revision": actual_sha,
            "frequencia_dirty": dirty, "sionna_rt_version": sionna_version,
            "seed": SEED, "radio": {"frequency_hz": FREQUENCY_HZ,
                                     "bandwidth_hz": BANDWIDTH_HZ, "tx_power_dbm": TX_POWER_DBM},
            "runs": run_counts, "raw_records": len(raw),
            "raw_artifact_path": str(raw_path), "raw_sha256": sha256(raw_path),
            "paired_model_disagreement_db_sionna_minus_analytic": stats(paired_gap),
            "paired_model_comparisons": len(paired_gap),
            "geometry_sha256": {mesh.name: sha256(mesh) for mesh in [wall_only, *reflector_meshes]},
            "inputs": {"flat_ground_sha256": sha256(flat),
                       "campaign_script_sha256": sha256(Path(__file__).resolve()),
                       "analytic_source_sha256": sha256(engine / "rf/channel.py"),
                       "sionna_source_sha256": sha256(engine / "rf/sionna_backend.py")},
            "antenna_orientation": "NOT_MEANINGFULLY_TESTABLE_WITH_CURRENT_ISOTROPIC_MODEL",
            "vegetation": "NOT_SUPPORTED_DEFENSIBLY; geometry/material proxy is not a foliage model",
            "limitations": ["All results are SIMULATED; Sionna is not ground truth.",
                            "Obstacle and reflector use the same 915 MHz concrete proxy material.",
                            "The analytic model ignores obstacle geometry; its paired results are MODEL_DISAGREEMENT.",
                            "No antenna orientation or physical vegetation attenuation is modeled."],
            "runtime_seconds": time.monotonic() - start,
        }
        summary_path = args.output / "gap-closure-summary.json"
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": "COMPLETE", "raw_records": len(raw), "runs": run_counts,
                          "summary": str(summary_path), "raw_sha256": summary["raw_sha256"]}, indent=2))
        return 0 if run_counts["failed"] == 0 else 2

    # Baseline control and distance/height sweeps. The paired points use identical ENU inputs.
    fixed_rx = (0.0, 0.0, 8.0)
    for distance in (5, 10, 25, 50, 100, 250, 500, 1000):
        tx = (distance, 0.0, 1.5)
        record_analytic(f"distance_{distance}m", tx, fixed_rx, group="distance")
        if args.sionna:
            gws = gateway_sites([(0, 0, 8), (0, 250, 8), (0, 500, 8)], "DIST")
            record_sionna(f"distance_{distance}m", tx, gws, mesh=engine / "farm/assets/ground.ply",
                          group="distance", primary_only=True)
    for tx_height in (1.0, 1.5, 2.5):
        for rx_height in (4.0, 8.0, 12.0):
            record_analytic(f"height_tx{tx_height:g}_rx{rx_height:g}", (100, 0, tx_height),
                            (0, 0, rx_height), group="height")
            if args.sionna:
                gws = gateway_sites([(0, 0, rx_height), (0, 250, 8), (0, 500, 8)], "HEIGHT")
                record_sionna(f"height_tx{tx_height:g}_rx{rx_height:g}", (100, 0, tx_height),
                              gws, mesh=engine / "farm/assets/ground.ply", group="height",
                              primary_only=True)

    # Six gateway layouts; sample the corners, edges and interior of a synthetic property.
    geometry_cases = {
        "symmetric_corners": [(100, 100), (900, 100), (900, 900), (100, 900)],
        "asymmetric": [(60, 180), (850, 90), (720, 920), (210, 760)],
        "one_side": [(80, 180), (120, 500), (80, 820)],
        "sparse_three": [(80, 80), (920, 120), (500, 920)],
        "denser_six": [(100, 100), (900, 100), (900, 900), (100, 900), (500, 60), (500, 940)],
        "elongated": [(60, 60), (940, 60), (940, 360), (60, 360)],
    }
    flat = engine / "farm/assets/ground.ply"
    for name, xy in geometry_cases.items():
        gateways = gateway_sites([(float(x), float(y), 8.0) for x, y in xy], name[:3].upper())
        sample_y = (20.0, 200.0, 380.0) if name == "elongated" else (50.0, 500.0, 950.0)
        sample_xy = [(x, y) for y in sample_y for x in (50.0, 500.0, 950.0)]
        for x, y in sample_xy:
            tx = (x, y, 1.5)
            for gateway in gateways:
                record_analytic(f"farm_{name}_{int(x)}_{int(y)}", tx, gateway.position,
                                group=f"geometry:{name}")
            if args.sionna:
                record_sionna(f"farm_{name}_{int(x)}_{int(y)}", tx, gateways,
                              mesh=flat, group=f"geometry:{name}")

    # Controlled blocked-direct-path case. The analytic backend intentionally ignores this wall.
    wall = artifact_dir / "synthetic_vertical_wall.ply"
    wall_mesh(wall)
    wall_gateways = gateway_sites([(800, 500, 8), (800, 350, 8), (800, 650, 8)], "WALL")
    wall_tx = (200.0, 500.0, 1.5)
    for gateway in wall_gateways:
        record_analytic("wall_blocked_direct_path", wall_tx,
                        gateway.position, group="combined_stress:NLOS")
    if args.sionna:
        record_sionna("wall_blocked_direct_path", wall_tx, wall_gateways,
                      mesh=flat, obstacle=wall, group="combined_stress:NLOS")

    # Seeded Monte Carlo positions: analytic has no stochastic propagation variables.
    rng = random.Random(SEED)
    mc_gateway = (450.0, 500.0, 8.0)
    for index in range(30):
        tx = (rng.uniform(0, 1000), rng.uniform(0, 1000), rng.choice((1.0, 1.5, 2.5)))
        record_analytic(f"monte_carlo_{index:03d}", tx, mc_gateway, group="monte_carlo")
        if args.sionna:
            mc_gateways = gateway_sites([(mc_gateway[0], mc_gateway[1], mc_gateway[2]),
                                         (0, 0, 8), (1000, 1000, 8)], "MC")
            record_sionna(f"monte_carlo_{index:03d}", tx, mc_gateways,
                          mesh=engine / "farm/assets/ground.ply", group="monte_carlo")

    if args.sionna:
        # Baseline, explicit direct/reflection toggles, and repeat-seed determinism check.
        control_gws = gateway_sites([(0, 0, 8), (1000, 0, 8), (1000, 1000, 8), (0, 1000, 8)], "CTRL")
        control_tx = (500.0, 500.0, 1.5)
        for gateway in control_gws:
            record_analytic("control_los_reflection", control_tx, gateway.position, group="control")
        record_sionna("control_los_reflection", control_tx, control_gws,
                      mesh=flat, group="control")
        record_sionna("control_direct_only", control_tx, control_gws,
                      mesh=flat, los=True, reflection=False, group="multipath")
        record_sionna("control_reflection_only", control_tx, control_gws,
                      mesh=flat, los=False, reflection=True, group="multipath")
        # Repeat same deterministic request and compare its canonical path/power view.
        first = record_sionna("seed_repeat_a", control_tx, control_gws,
                              mesh=flat, group="seed_determinism")
        second = record_sionna("seed_repeat_b", control_tx, control_gws,
                               mesh=flat, group="seed_determinism")
        def physical_view(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [{"status": row["status"], "power_dbm": row["power_dbm"],
                     "delay_s": row["delay_s"], "path_count": row["path_count"],
                     "paths": [{"delay_s": path["delay_s"], "a": path["a"],
                                "interactions": [{"type": interaction["type"],
                                                  "vertex_m": interaction.get("vertex_m")}
                                                 for interaction in path.get("interactions", [])]}
                               for path in row["paths"]]} for row in rows]
        first_view = physical_view(first)
        second_view = physical_view(second)
        determinism = first_view == second_view
    else:
        determinism = None

    # Optional terrain comparison uses FREQUENCIA's procedural relief only as a geometry proxy.
    if args.sionna:
        config_path = engine / "configs/brazil_reference.yaml"
        _, reference = load_reference_config(config_path)
        terrain, _ = reference.write_meshes(artifact_dir / "reference_geometry")
        terrain_xy = [(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0)]
        terrain_gateway = gateway_sites([(x, y, reference.height_m(x, y) + 8.0)
                                         for x, y in terrain_xy], "TERR")
        terrain_tx = (500.0, 500.0, reference.height_m(500.0, 500.0) + 1.5)
        flat_control_tx = (500.0, 500.0, 1.5)
        flat_control_gateways = gateway_sites([(x, y, 8.0) for x, y in terrain_xy], "TFLAT")
        record_sionna("flat_terrain_control", flat_control_tx, flat_control_gateways,
                      mesh=flat, group="terrain")
        record_sionna("synthetic_relief_terrain", terrain_tx, terrain_gateway,
                      mesh=terrain, group="terrain")

    # Aggregate by backend and scenario group; failures and NO_PATH stay in denominators.
    paired: list[float] = []
    index_analytic = {(row["case"], tuple(row["rx_position_m"])): row for row in raw
                      if row.get("backend") == "ANALYTIC_SIMULATION"}
    for row in raw:
        if row.get("backend") != "SIONNA_RT_SIMULATION" or row.get("power_dbm") is None:
            continue
        analytic = index_analytic.get((row["case"], tuple(row.get("rx_position_m", []))))
        if analytic and analytic.get("power_dbm") is not None:
            delta = float(row["power_dbm"]) - float(analytic["power_dbm"])
            row["paired_model_disagreement_db"] = delta
            paired.append(delta)
    aggregate: dict[str, Any] = {}
    for backend in ("ANALYTIC_SIMULATION", "SIONNA_RT_SIMULATION"):
        for group in sorted({row.get("group", "") for row in raw if row.get("backend") == backend}):
            selected = [row for row in raw if row.get("backend") == backend
                        and row.get("group", "") == group
                        and row.get("aggregate_population", True)]
            values = [float(row["power_dbm"]) for row in selected if row.get("power_dbm") is not None]
            aggregate[f"{backend}:{group}"] = {
                "attempts": len(selected),
                "successfully_simulated": sum(row.get("status") != "SIMULATION_FAILURE" for row in selected),
                "simulation_failure": sum(row.get("status") == "SIMULATION_FAILURE" for row in selected),
                "no_path": sum(row.get("status") == "NO_PATH" for row in selected),
                "path_available": sum(row.get("status") in {"PATH_AVAILABLE", "LOS", "NLOS"} for row in selected),
                "coverage_at_engineering_assumption": sum(row.get("coverage_engineering_assumption") is True for row in selected),
                "power_dbm": stats(values),
                "delay_s": stats([float(row["delay_s"]) for row in selected if row.get("delay_s") is not None]),
                "path_count": stats([float(row["path_count"]) for row in selected if row.get("path_count") is not None]),
            }
    raw_path = args.output / "raw-runs.jsonl"
    with raw_path.open("w", encoding="utf-8") as stream:
        for row in raw:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
    summary = {
        "classification": "SIMULATED",
        "riose_revision": riose_revision,
        "riose_dirty": riose_dirty,
        "frequencia_revision": actual_sha,
        "frequencia_dirty": dirty,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "sionna_rt_version": sionna_version,
        "package_versions": package_versions,
        "seed": SEED,
        "radio": {"frequency_hz": FREQUENCY_HZ, "bandwidth_hz": BANDWIDTH_HZ,
                  "tx_power_dbm": TX_POWER_DBM,
                  "coverage_threshold_dbm": COVERAGE_DBM,
                  "coverage_threshold_origin": "ENGINEERING_ASSUMPTION",
                  "noise_figure_db": NOISE_FIGURE_DB, "snr_threshold_db": SNR_THRESHOLD_DB},
        "runs": run_counts,
        "raw_records": len(raw),
        "runtime_seconds": time.monotonic() - start,
        "seed_determinism_identical": determinism,
        "output_root": str(args.output),
        "raw_artifact_path": str(raw_path),
        "geometry_cases": {key: len(value) for key, value in geometry_cases.items()},
        "geometry_coverage_maps": {
            backend: {
                name: {
                    "sampled_positions": len({row["case"] for row in raw
                                               if row.get("backend") == backend
                                               and row.get("group") == f"geometry:{name}"}),
                    "positions_with_one_or_more_covered_links": sum(
                        any(row.get("coverage_engineering_assumption") is True
                            for row in raw if row.get("backend") == backend
                            and row.get("group") == f"geometry:{name}" and row.get("case") == case)
                        for case in {row["case"] for row in raw if row.get("backend") == backend
                                     and row.get("group") == f"geometry:{name}"}),
                    "link_attempts": sum(row.get("backend") == backend
                                         and row.get("group") == f"geometry:{name}"
                                         for row in raw),
                    "links_at_engineering_coverage_threshold": sum(
                        row.get("backend") == backend and row.get("group") == f"geometry:{name}"
                        and row.get("coverage_engineering_assumption") is True for row in raw),
                }
                for name in geometry_cases
            }
            for backend in ("ANALYTIC_SIMULATION", "SIONNA_RT_SIMULATION")
        },
        "aggregates": aggregate,
        "paired_model_disagreement_db_sionna_minus_analytic": stats(paired),
        "paired_model_comparisons": len(paired),
        "raw_sha256": sha256(raw_path),
        "inputs": {"frequencia_revision": FREQUENCIA_SHA,
                   "flat_ground_sha256": sha256(flat),
                   "wall_mesh_sha256": sha256(wall),
                   "campaign_script_sha256": sha256(Path(__file__).resolve()),
                   "campaign_spec_sha256": sha256(riose_root / "docs/research/rf-realism/campaign-spec.json"),
                   "frequencia_reference_config_sha256": sha256(engine / "configs/brazil_reference.yaml"),
                   "analytic_source_sha256": sha256(engine / "rf/channel.py"),
                   "sionna_source_sha256": sha256(engine / "rf/sionna_backend.py"),
                   "terrain_mesh_sha256": sha256(terrain) if args.sionna else None},
        "limitations": [
            "No field measurements, hardware sensitivity, or physical validation.",
            "Analytic backend has no obstacles; blocked-wall analytic runs intentionally do not model the wall.",
            "Sionna antennas are isotropic and vertical; orientation effects are not testable through this wrapper.",
            "Trees/vegetation/fences are not raytraced; synthetic relief and wall are geometric proxies.",
            "No LoRa demodulator/receiver detection is modeled; engineering coverage is not packet observability.",
            "Sionna PathSolver is deterministic; Monte Carlo varies positions, not fading or material randomness.",
            "Analytic and Sionna power definitions are different; differences are MODEL_DISAGREEMENT, not Sionna error."
        ]
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "COMPLETE", "raw_records": len(raw), "runs": run_counts,
                      "runtime_seconds": summary["runtime_seconds"],
                      "seed_determinism_identical": determinism,
                      "summary": str(args.output / "summary.json"),
                      "raw_sha256": summary["raw_sha256"]}, indent=2))
    return 0 if run_counts["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
