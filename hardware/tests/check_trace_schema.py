"""Validate exported deterministic C firmware trace files."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def validate(path: Path) -> None:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not records:
        raise ValueError(f"{path}: empty trace")
    timestamps = []
    for sequence, record in enumerate(records):
        if record.get("schema_version") != "riose.firmware.trace/v1":
            raise ValueError(f"{path}: unsupported schema at record {sequence}")
        if record.get("sequence") != sequence:
            raise ValueError(f"{path}: sequence is not contiguous at record {sequence}")
        if record.get("status") != "SIMULATED" or not record.get("event") or not record.get("state"):
            raise ValueError(f"{path}: missing event evidence at record {sequence}")
        packet_hex = record.get("packet_hex", "")
        if record["event"] == "PACKET_CREATED":
            if len(packet_hex) != int(record["value0"]) * 2 or any(
                char not in "0123456789abcdef" for char in packet_hex
            ):
                raise ValueError(f"{path}: packet bytes do not match packet length at record {sequence}")
        elif packet_hex:
            raise ValueError(f"{path}: packet bytes appear outside PACKET_CREATED at record {sequence}")
        timestamps.append(int(record["timestamp_us"]))
    if timestamps != sorted(timestamps):
        raise ValueError(f"{path}: timestamps are not monotonic")


def main() -> int:
    try:
        for name in ("normal", "active", "alert", "worst_reasonable_case"):
            validate(Path(sys.argv[1]) / f"{name}-trace.jsonl")
    except (IndexError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"trace schema check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
