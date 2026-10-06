"""Command line interface for the independent Simulation Lab runner."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .runner import EXPECTED_FREQUENCIA_SHA, RunnerError, doctor, run


def _expected_sha(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise argparse.ArgumentTypeError("expected SHA must be 40 lowercase hexadecimal characters")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m riose.simulation_lab")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("doctor", help="inspect frequencia pin, checkout and optional capabilities")
    check.add_argument("--repo", type=Path, help="frequencia checkout (or FREQUENCIA_REPO)")
    check.add_argument("--expected-sha", type=_expected_sha, default=EXPECTED_FREQUENCIA_SHA)
    execute = sub.add_parser("run", help="validate a Simulation Request V1 and run its explicitly selected backend")
    execute.add_argument("request", type=Path)
    execute.add_argument("--repo", type=Path, help="frequencia checkout (or FREQUENCIA_REPO)")
    execute.add_argument("--expected-sha", type=_expected_sha, default=EXPECTED_FREQUENCIA_SHA)
    execute.add_argument("--output-root", type=Path, help="isolated run storage outside the RIOSE checkout")
    execute.add_argument("--timeout", type=float, default=300)
    execute.add_argument("--dry-run", action="store_true", help="validate and record a plan without starting frequencia")
    execute.add_argument("--allow-dirty", action="store_true", help="explicitly allow a dirty pinned checkout")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            report = doctor(args.repo, expected_sha=args.expected_sha)
            print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
            return 0 if report["status"] == "READY" else 1
        report = run(args.request, repo=args.repo, expected_sha=args.expected_sha,
                     output_root=args.output_root, dry_run=args.dry_run,
                     allow_dirty=args.allow_dirty, timeout_seconds=args.timeout)
    except (RunnerError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
