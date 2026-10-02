"""Compare repeat native_sim captures by their deterministic event semantics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trace_export import load_jsonl

SEMANTIC_FIELDS = (
    "sequence", "state_id", "event_id", "source_id", "result",
    "value0", "value1", "value2", "packet_hex",
)


def semantic_trace(path: Path) -> list[dict[str, object]]:
    return [{key: record[key] for key in SEMANTIC_FIELDS} for record in load_jsonl(path)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args()
    first, second = semantic_trace(args.first), semantic_trace(args.second)
    if first != second:
        raise SystemExit("native_sim semantic traces differ")
    print(json.dumps({"status": "DETERMINISTIC", "records": len(first)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
