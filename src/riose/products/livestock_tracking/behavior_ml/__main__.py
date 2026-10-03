"""Command line entry point: python -m riose.products.livestock_tracking.behavior_ml"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import (infer, load_artifact, read_windows,
                       run_training, save_artifact, write_fixture)


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline cattle behavior ML software MVP")
    commands = parser.add_subparsers(dest="command", required=True)
    fixture = commands.add_parser("fixture", help="write the explicitly synthetic software fixture")
    fixture.add_argument("--output", required=True)
    training = commands.add_parser("train", help="compare candidates and train the selected baseline")
    training.add_argument("--input", required=True, help="JSON array of BehaviorWindow records")
    training.add_argument("--artifact", required=True)
    training.add_argument("--seed", type=int, default=23)
    prediction = commands.add_parser("predict", help="run local inference from one JSON feature vector")
    prediction.add_argument("--artifact", required=True)
    prediction.add_argument("--features", required=True, help="JSON object with ordered feature keys")
    prediction.add_argument("--sample-rate-hz", type=float,
                            help="required only when training provenance contains a known rate")
    prediction.add_argument("--sensor-position", required=True)
    prediction.add_argument("--timestamp-s", type=float)
    args = parser.parse_args()

    if args.command == "fixture":
        write_fixture(args.output)
        print(json.dumps({"output": args.output, "evidence_status": "SIMULATED",
                          "scientific_validation": False}, indent=2))
    elif args.command == "train":
        payload, report = run_training(read_windows(args.input), seed=args.seed)
        save_artifact(payload, args.artifact)
        print(json.dumps({"artifact": args.artifact, **report}, indent=2))
    else:
        artifact = load_artifact(args.artifact)
        features = json.loads(Path(args.features).read_text(encoding="utf-8"))
        print(json.dumps(infer(artifact, features, sample_rate_hz=args.sample_rate_hz,
                               sensor_position=args.sensor_position, timestamp_s=args.timestamp_s), indent=2))


if __name__ == "__main__":
    main()
