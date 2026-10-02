"""Headless MVP2 runner; missing solvers are reported, never replaced by fakes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .execution import _clear_previous_outputs, _run_command, _write_empty_csv
from .motion import generate_motion_profiles
from .paths import DEFAULT_OUTPUT, DEFAULT_SPEC, ROOT, SCENARIOS
from .power import _power_assumptions, _power_load_profile, _record
from .preflight import _module_available, _version_matches, preflight
from .reporting import _metrics_csv, _report
from .runner import _long_run_energy_uah, _stack_usage, run_twin
from .spec import load_spec, parameter_statuses

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m riose.products.ear_tag.digital_twin", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight", help="report headless toolchain/GPU availability")
    validate = sub.add_parser("validate-spec", help="validate hardware parameters and provenance")
    validate.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    run = sub.add_parser("run", help="run available digital-twin stages and generate report")
    run.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    run.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    run.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    if args.command == "preflight":
        print(json.dumps(preflight(), indent=2, sort_keys=True))
        return 0
    if args.command == "validate-spec":
        try:
            spec, digest = load_spec(args.spec)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        print(json.dumps({"status": "VALID", "sha256": digest, "parameter_statuses": parameter_statuses(spec)}, sort_keys=True))
        return 0
    try:
        summary = run_twin(args.spec, args.output, args.seed)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"digital twin run failed before report generation: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "REPORT_GENERATED", "gate": summary["gate"]["state"],
                      "blockers": summary["gate"]["blockers"], "output": str(args.output)}, sort_keys=True))
    return 1 if summary["gate"]["state"] == "NOT_READY_FOR_PHYSICAL_PROTOTYPE" else 0

if __name__ == "__main__":
    raise SystemExit(main())
