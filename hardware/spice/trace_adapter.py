#!/usr/bin/env python3
"""Convert portable firmware point events to assumed current intervals.

The C firmware trace supplies times and event boundaries only. Current values
and zero-resolution fallbacks must come from a caller-supplied ASSUMED profile;
this adapter never supplies or labels current as measured.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


class TraceConversionError(ValueError):
    """Trace cannot be converted without inventing a duration or load."""


def _number(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise TraceConversionError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise TraceConversionError(f"{label} must be finite")
    return result


def _load_config(loads: dict[str, dict[str, Any]], key: str) -> dict[str, Any] | None:
    config = loads.get(key)
    if config is None:
        return None
    if config.get("current_status") != "ASSUMED":
        raise TraceConversionError(f"{key}: current_status must be ASSUMED")
    if not config.get("source"):
        raise TraceConversionError(f"{key}: source is required for current provenance")
    current = _number(config.get("load_current_ma"), f"{key}.load_current_ma")
    if current < 0:
        raise TraceConversionError(f"{key}: current must be nonnegative")
    if not config.get("component"):
        raise TraceConversionError(f"{key}: component is required")
    return {**config, "load_current_ma": current}


def _duration(config: dict[str, Any], key: str, measured_interval_s: float) -> tuple[float, str]:
    if measured_interval_s > 0:
        return measured_interval_s, "TRACE_TIMESTAMP"
    fallback = config.get("fallback_duration_s")
    if fallback is None:
        raise TraceConversionError(
            f"{key}: event interval has zero timestamp resolution and no ASSUMED fallback_duration_s"
        )
    if config.get("duration_status") != "ASSUMED":
        raise TraceConversionError(f"{key}: fallback duration_status must be ASSUMED")
    if not config.get("duration_source"):
        raise TraceConversionError(f"{key}: fallback duration_source is required")
    duration = _number(fallback, f"{key}.fallback_duration_s")
    if duration <= 0:
        raise TraceConversionError(f"{key}: fallback duration must be positive")
    return duration, "ASSUMED_FALLBACK"


def trace_to_schedule(records: list[dict[str, Any]],
                      loads: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Build power interval rows from firmware JSONL records and a load profile.

    `loads` keys use `state:<name>`, `event:<name>`, or
    `pair:<start_event>:<end_event>`. State intervals use adjacent STATE events;
    paired event intervals use their event timestamps. A configured point event
    uses its explicit ASSUMED fallback duration. The `MCU_SLEEP` payload can
    close a terminal SLEEP state interval because the harness may end during it.
    """
    if not records:
        raise TraceConversionError("trace contains no records")
    parsed = []
    previous_us = -1
    for index, record in enumerate(records, start=1):
        if record.get("status") != "SIMULATED":
            raise TraceConversionError(f"record {index}: expected status=SIMULATED")
        timestamp_us = _number(record.get("timestamp_us"), f"record {index}.timestamp_us")
        if timestamp_us < 0 or timestamp_us < previous_us:
            raise TraceConversionError(f"record {index}: timestamps must be nonnegative and monotonic")
        previous_us = timestamp_us
        if not record.get("event") or not record.get("state"):
            raise TraceConversionError(f"record {index}: event and state are required")
        parsed.append({**record, "_timestamp_s": timestamp_us / 1_000_000.0})

    rows: list[dict[str, Any]] = []

    def append(key: str, event: str, state: str, start_s: float, elapsed_s: float,
               elapsed_source: str | None = None) -> None:
        config = _load_config(loads, key)
        if config is None:
            return
        duration, duration_source = _duration(config, key, elapsed_s)
        rows.append({
            "timestamp_s": start_s,
            "event": event,
            "state": state,
            "component": str(config["component"]),
            "duration_s": duration,
            "load_current_ma": config["load_current_ma"],
            "status": "SIMULATED",
            "current_status": "ASSUMED",
            "duration_source": elapsed_source or duration_source,
            "provenance": str(config["source"]),
        })

    # State intervals are inferred from adjacent transitions; close a terminal
    # SLEEP interval from the HAL wait duration recorded by the C FSM.
    state_records = [r for r in parsed if r["event"] == "STATE"]
    for i, record in enumerate(state_records):
        state = str(record["state"])
        key = f"state:{state}"
        config = _load_config(loads, key)
        if config is None:
            continue
        start = record["_timestamp_s"]
        if i + 1 < len(state_records):
            elapsed = state_records[i + 1]["_timestamp_s"] - start
            # Several state transitions may share a HAL millisecond tick. They
            # represent zero-duration markers at this trace resolution, not a
            # request to invent an entire dwell interval for each repeated state.
            # The explicit idle baseline in the power model still spans time.
            if elapsed == 0:
                continue
        else:
            sleep = next((r for r in parsed if r["event"] == "MCU_SLEEP" and
                          r["state"] == state and r.get("value0") is not None), None)
            elapsed = (_number(sleep["value0"], "MCU_SLEEP.value0") / 1000.0
                       if sleep is not None else 0.0)
            append(key, state, state, start, elapsed,
                   "TRACE_EVENT_PAYLOAD" if sleep is not None and elapsed > 0 else None)
            continue
        append(key, state, state, start, elapsed)

    # Explicitly paired radio stages preserve their event duration. A missing
    # end marker is an error when that interval is requested in the load profile.
    for start_event, end_event, label in (("TX_START", "TX_DONE", "TX"),
                                          ("RX_START", "RX_DONE", "RX")):
        key = f"pair:{start_event}:{end_event}"
        config = _load_config(loads, key)
        if config is None:
            continue
        starts = [r for r in parsed if r["event"] == start_event]
        ends = [r for r in parsed if r["event"] == end_event]
        if len(starts) != len(ends):
            raise TraceConversionError(
                f"{label} trace has {len(starts)} start(s) and {len(ends)} end(s); cannot infer interval"
            )
        for start, end in zip(starts, ends):
            elapsed = end["_timestamp_s"] - start["_timestamp_s"]
            interval_state = "RF_TX" if label == "TX" else "RF_RX"
            append(key, label, interval_state, start["_timestamp_s"], elapsed)

    # Point events can represent short component work only when the caller
    # provides an explicit ASSUMED duration; no default dwell is fabricated.
    for record in parsed:
        key = f"event:{record['event']}"
        config = _load_config(loads, key)
        if config is None:
            continue
        if config.get("fallback_duration_s") is None:
            raise TraceConversionError(f"{key}: point event requires ASSUMED fallback_duration_s")
        append(key, str(record["event"]), str(record["state"]),
               record["_timestamp_s"], 0.0)

    return sorted(rows, key=lambda row: (row["timestamp_s"], row["component"], row["event"]))


def read_load_profile(path: Path) -> dict[str, dict[str, Any]]:
    """Read the orchestrator's ASSUMED profile envelope or a bare JSON mapping."""
    loads: Any = json.loads(path.read_text())
    if not isinstance(loads, dict):
        raise TraceConversionError("load profile must be a JSON object")
    if isinstance(loads.get("loads"), dict):
        if loads.get("status") != "ASSUMED":
            raise TraceConversionError("load profile envelope must have status=ASSUMED")
        if loads.get("schema_version") != "riose.power.loads/v1":
            raise TraceConversionError("unsupported load profile schema_version")
        loads = loads["loads"]
    return loads


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="SIMULATED firmware trace JSONL")
    parser.add_argument("--loads", required=True, type=Path,
                        help="ASSUMED JSON load profile generated from hardware/spec.yaml")
    parser.add_argument("--output", required=True, type=Path,
                        help="power-tool-compatible schedule JSONL output")
    args = parser.parse_args()
    records = [json.loads(line) for line in args.trace.read_text().splitlines() if line.strip()]
    try:
        loads = read_load_profile(args.loads)
        rows = trace_to_schedule(records, loads)
    except TraceConversionError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as stream:
        if args.output.suffix.lower() == ".json":
            json.dump(rows, stream, indent=2, sort_keys=True)
            stream.write("\n")
        else:
            for row in rows:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
