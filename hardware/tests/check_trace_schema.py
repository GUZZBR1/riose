"""Apply the firmware trace contract to host-generated JSONL artifacts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hardware.firmware.zephyr.trace_export import TraceFormatError, load_jsonl  # noqa: E402


def main() -> int:
    try:
        output_dir = Path(sys.argv[1])
        for name in ("normal", "active", "alert", "worst_reasonable_case"):
            load_jsonl(output_dir / f"{name}-trace.jsonl")
    except (IndexError, OSError, TraceFormatError) as exc:
        print(f"trace schema check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
