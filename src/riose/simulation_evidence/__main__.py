"""Build or verify a simulation evidence package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .pipeline import EvidenceError, build_package, verify_package


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="riose-simulation-evidence")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="build a compact evidence package")
    build.add_argument("campaign", type=Path)
    build.add_argument("destination", type=Path)
    build.add_argument("--artifact", action="append", default=[], help="explicit source-relative artifact to include under plots/")
    build.add_argument("--riose-repo", type=Path)
    build.add_argument("--frequencia-repo", type=Path)
    verify = sub.add_parser("verify", help="verify a built evidence package")
    verify.add_argument("package", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            build_package(args.campaign, args.destination, selected_artifacts=args.artifact,
                          riose_repo=args.riose_repo, frequencia_repo=args.frequencia_repo)
            result = verify_package(args.destination)
        else:
            result = verify_package(args.package)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["valid"] else 1
    except EvidenceError as exc:
        print(f"evidence error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
