"""Demonstrate the V1 fixture round-trip without running a simulator."""

from __future__ import annotations

from pathlib import Path

from .v1 import canonical_json, content_hash, load_json


def main() -> int:
    root = Path(__file__).parent / "fixtures"
    request = load_json((root / "request-v1.json").read_text(encoding="utf-8"), kind="request")
    result = load_json((root / "result-v1.json").read_text(encoding="utf-8"), kind="result")
    for name, value in (("request", request), ("result", result)):
        roundtrip = load_json(canonical_json(value), kind=name)
        assert roundtrip == value
        print(f"{name}: valid {value['schema_version']} sha256={content_hash(value)}")
    print("fixture round-trip: OK (no simulator executed; evidence remains SIMULATED)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
