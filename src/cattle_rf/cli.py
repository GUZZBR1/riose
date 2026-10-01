"""Command line entry point for local demo and reproducible experiments."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics
import time
from typing import Any

from .contracts import FarmConfig
from .datasets import write_episode_dataset
from .localization import METHODS, estimate, evaluate, train_fingerprint_model
from .pipeline import run_episode
from .sim import simulate_episode
from .sim.rf import RFConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cattle-rf", description="Local cattle RF simulator")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="start the local interactive demo")
    demo.add_argument("--host", default="127.0.0.1")
    demo.add_argument("--port", type=int, default=8000)
    demo.add_argument("--animals", type=int, default=100)
    demo.add_argument("--anchors", type=int, default=8)
    demo.add_argument("--db", default="data/cattle_rf.sqlite3")
    benchmark = sub.add_parser("benchmark", help="run multi-method localization scenarios")
    benchmark.add_argument("--output", default="results")
    benchmark.add_argument("--profile", choices=("quick", "full"), default="full")
    benchmark.add_argument("--seeds", type=int, default=1)
    benchmark.add_argument("--duration", type=float, default=None)
    benchmark.add_argument("--animals", type=int, nargs="+", default=None)
    benchmark.add_argument("--anchors", type=int, nargs="+", default=None)
    dataset = sub.add_parser("dataset", help="generate separate train/validation/holdout files")
    dataset.add_argument("--output", default="datasets")
    dataset.add_argument("--seed", type=int, default=7)
    dataset.add_argument("--animals", type=int, default=20)
    dataset.add_argument("--anchors", type=int, default=8)
    dataset.add_argument("--duration", type=float, default=1800)
    dataset.add_argument("--period", type=float, default=30)
    args = parser.parse_args(argv)
    if args.command == "demo":
        return run_demo(args)
    if args.command == "benchmark":
        run_benchmark(args)
        return 0
    if args.command == "dataset":
        run_dataset(args)
        return 0
    return 2


def run_demo(args: argparse.Namespace) -> int:
    import uvicorn
    from .api import create_app, ensure_animals
    from .db import Store

    db_path = Path(args.db)
    store = Store(db_path)
    app = create_app(db_path)
    config = FarmConfig(animal_count=args.animals, anchor_count=args.anchors,
                        duration_s=1800, sample_period_s=30, seed=7)
    episode, estimates, metrics = run_episode(config, "weighted_centroid")
    store.save_anchors(episode.anchors)
    store.save_episode(episode.observations, estimates, episode.ground_truth)
    store.set_metrics(metrics)
    ensure_animals(store, args.animals)
    store.close()
    app.state.anchors = list(episode.anchors)
    app.state.last_config, app.state.last_episode = config, episode
    print(f"Dashboard local: http://{args.host}:{args.port} (SIMULATED)", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def run_dataset(args: argparse.Namespace) -> None:
    root = Path(args.output)
    for split, offset in (("train", 0), ("validation", 100_003), ("holdout", 200_003)):
        config = FarmConfig(animal_count=args.animals, anchor_count=args.anchors,
                            duration_s=args.duration, sample_period_s=args.period,
                            seed=args.seed + offset)
        episode = simulate_episode(config)
        outputs = write_episode_dataset(episode.observations, episode.ground_truth, root, split)
        print(json.dumps({"split": split, **outputs}))


def run_benchmark(args: argparse.Namespace) -> None:
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    if args.profile == "quick":
        animal_counts = args.animals or [1, 10, 100]
        anchor_counts = args.anchors or [4, 8, 20]
        duration, sample_period = args.duration or 180, 30
    else:
        animal_counts = args.animals or [1, 10, 50, 100, 500, 1000]
        anchor_counts = args.anchors or [4, 8, 12, 20]
        duration, sample_period = args.duration or 300, 60
    seeds = max(1, args.seeds)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    energy_rows: list[dict[str, Any]] = []
    cdf_values: dict[str, list[float]] = {method: [] for method in METHODS}
    start = time.perf_counter()
    for anchor_count in anchor_counts:
        anchors = None
        model_cache: dict[str, Any] = {}
        for animal_count in animal_counts:
            for repeat in range(seeds):
                seed = 7001 + anchor_count * 1009 + animal_count * 17 + repeat
                rf = RFConfig(shadow_sigma_db=3.0 + (seed % 5),
                              measurement_sigma_db=1.0 + (seed % 4),
                              nlos_probability=(seed % 4) * 0.04,
                              interference_probability=0.01 + (seed % 3) * 0.01)
                config = FarmConfig(animal_count=animal_count, anchor_count=anchor_count,
                                    duration_s=duration, sample_period_s=sample_period,
                                    seed=seed, packet_loss_probability=0.05)
                episode = simulate_episode(config, anchors=anchors, rf_config=rf)
                anchors = episode.anchors
                for model_name in ("extra_trees", "gradient_boosting"):
                    if model_name not in model_cache:
                        training_config = FarmConfig(
                            animal_count=20, anchor_count=anchor_count, duration_s=duration,
                            sample_period_s=sample_period, seed=900_000 + anchor_count * 13)
                        train = simulate_episode(training_config, anchors=anchors,
                                                 rf_config=RFConfig(shadow_sigma_db=4.0,
                                                                    measurement_sigma_db=2.0,
                                                                    nlos_probability=0.08))
                        try:
                            model_cache[model_name] = train_fingerprint_model(
                                train.observations, train.ground_truth, train.anchors,
                                algorithm=model_name, random_state=17)
                        except RuntimeError as exc:
                            model_cache[model_name] = exc
                for method in METHODS:
                    models = None
                    if method in {"extra_trees", "gradient_boosting"}:
                        cached = model_cache[method]
                        if isinstance(cached, Exception):
                            rows.append({"animal_count": animal_count, "anchor_count": anchor_count,
                                         "seed": seed, "method": method, "status": "UNAVAILABLE",
                                         "reason": str(cached), "evidence": "SIMULATED"})
                            continue
                        models = {method: cached}
                    method_start = time.perf_counter()
                    estimates = estimate(episode.observations, episode.anchors, method,
                                         fingerprint_models=models)
                    metrics = evaluate(estimates, episode.ground_truth)
                    elapsed = time.perf_counter() - method_start
                    received = sum(o.packet_received for o in episode.observations)
                    total = len(episode.observations)
                    rows.append({"animal_count": animal_count, "anchor_count": anchor_count,
                                 "seed": seed, "method": method, **metrics,
                                 "packet_delivery_ratio": received / total if total else 0.0,
                                 "runtime_seconds": elapsed, "evidence": "SIMULATED"})
                    if metrics.get("mean_error_m") is not None:
                        import math
                        truth_map = {(g.tag_id, g.timestamp_s): g for g in episode.ground_truth}
                        for estimate_row in estimates:
                            target = truth_map.get((estimate_row.tag_id, estimate_row.timestamp_s))
                            if target and estimate_row.x is not None and estimate_row.y is not None:
                                error = math.hypot(estimate_row.x - target.x, estimate_row.y - target.y)
                                errors.append({"animal_count": animal_count, "anchor_count": anchor_count,
                                               "seed": seed, "method": method,
                                               "tag_id": estimate_row.tag_id,
                                               "timestamp_s": estimate_row.timestamp_s,
                                               "error_m": error, "evidence": "SIMULATED"})
                                cdf_values[method].append(error)
                from .pipeline import energy_metrics
                energy = energy_metrics(episode, config)
                energy_rows.append({"animal_count": animal_count, "anchor_count": anchor_count,
                                    "seed": seed, **energy, "evidence": "SIMULATED"})
                if repeat == 0 and animal_count == animal_counts[0] and anchor_count == anchor_counts[0]:
                    write_episode_dataset(episode.observations, episode.ground_truth,
                                          root / "datasets", "holdout")
    write_csv(root / "metrics.csv", rows)
    write_csv(root / "localization_errors.csv", errors)
    write_csv(root / "energy.csv", energy_rows)
    write_csv(root / "cost_model.csv", create_cost_model())
    plots_dir = root / "plots"
    make_cdf_plot(cdf_values, plots_dir / "localization_error_cdf.png")
    summary = {
        "status": "SIMULATED", "profile": args.profile,
        "animal_counts": animal_counts, "anchor_counts": anchor_counts,
        "seeds_per_scenario": seeds, "duration_s": duration,
        "sample_period_s": sample_period, "methods": list(METHODS),
        "scenario_count": len(animal_counts) * len(anchor_counts) * seeds,
        "runtime_seconds": time.perf_counter() - start, "rows": len(rows),
        "error_rows": len(errors), "mean_error_by_method_m": aggregate_errors(errors),
        "energy_profile_note": "STM32WLE5 reference configuration; idle/BLE/Wi-Fi/alert currents are assumptions; no battery capacity is configured, so battery life is unavailable.",
        "limitations": ["Simulation only; no physical farm validation.",
                        "Path-loss calibration is assumed and RSSI ranging may be poor.",
                        "Advanced Sionna/ns-3/Zephyr/Wokwi integrations are optional and are not claimed as executed."],
    }
    (root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_report(root / "REPORT.md", summary)
    print(f"Benchmark concluído: {root.resolve()} ({summary['scenario_count']} cenários, {summary['runtime_seconds']:.1f}s)")


def create_cost_model() -> list[dict[str, Any]]:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    components = [("Tag: MCU + IMU + RFID + enclosure + battery", 100),
                  ("Anchor: ESP32-C6 + sub-GHz radio + power", 8),
                  ("Local gateway/computer", 1),
                  ("Shared infrastructure", 1)]
    return [{"component": name, "unit_cost": "", "currency": "BRL",
             "source_status": "PRICE_RESEARCH_REQUIRED", "quantity": qty,
             "date": today, "notes": "No verified supplier quote; blank cost is intentional."}
            for name, qty in components]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        if fields:
            writer.writeheader()
            writer.writerows(rows)


def make_cdf_plot(values: dict[str, list[float]], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    for method, data in values.items():
        if data:
            xs = sorted(data)
            ax.plot(xs, [(i + 1) / len(xs) for i in range(len(xs))], label=method)
    ax.set_xlabel("Localization error (m)")
    ax.set_ylabel("Cumulative fraction")
    ax.set_title("Simulated localization error CDF")
    ax.grid(True, alpha=0.25)
    if any(values.values()):
        ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    import matplotlib.pyplot as plt
    plt.close(fig)


def aggregate_errors(errors: list[dict[str, Any]]) -> dict[str, float | None]:
    return {method: statistics.mean(values) if values else None
            for method in METHODS
            for values in [[r["error_m"] for r in errors if r["method"] == method]]}


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = ["# Cattle RF benchmark report", "",
             "**Evidence: SIMULATED. Not validated on a physical farm.**", "",
             f"- Profile: {summary['profile']}", f"- Scenario count: {summary['scenario_count']}",
             f"- Runtime: {summary['runtime_seconds']:.1f} seconds", "",
             "## Mean localization error by method", "", "| Method | Mean error (m) |", "|---|---:|"]
    for method, value in summary["mean_error_by_method_m"].items():
        lines.append(f"| {method} | {value:.2f} |" if value is not None else f"| {method} | unavailable |")
    lines.extend(["", "## Interpretation and limits", "",
                  "All metrics come from a seeded software model and do not establish field performance. RSSI varies with assumed path loss, shadowing, obstacles, and packet loss. Fingerprint models train on distinct seeds and are evaluated on separate seeds; this still does not prove transfer to a farm.", "",
                  summary["energy_profile_note"], "",
                  "Cost entries are marked PRICE_RESEARCH_REQUIRED; blank values are not estimates.", "",
                  "Raw data: metrics.csv, localization_errors.csv, energy.csv. CDF: plots/localization_error_cdf.png."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
