"""Dependency-free validation for the closed Beta scenario contract."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "riose.beta.scenario-contract/v1"
EVIDENCE = {"SIMULATED", "EXTERNAL_MEASURED_DATA", "REAL_ON_CHAIN",
            "EXPERIMENTAL", "ENGINEERING_ESTIMATE", "NOT_EVALUATED"}
FAULTS = {"NONE", "PACKET_LOSS", "GATEWAY_LOSS", "CLOCK_DRIFT",
          "BAD_TIMESTAMP", "INSUFFICIENT_ANCHORS", "DATABASE_FAILURE",
          "BLOCKCHAIN_RPC_FAILURE", "INTEGRITY_FAILURE", "SENSOR_STREAM_FAILURE",
          "SEVERE_DETECTOR_THRESHOLD"}


class BetaContractError(ValueError):
    """A scenario is ambiguous, incomplete, or outside this schema version."""


def _object(value: Any, where: str, required: set[str], optional: set[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BetaContractError(f"{where} must be an object")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing:
        raise BetaContractError(f"{where} missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise BetaContractError(f"{where} has unsupported fields: {', '.join(sorted(extra))}")
    return value


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BetaContractError(f"{where} must be a non-empty string")
    return value


def validate_scenario(doc: Any) -> dict[str, Any]:
    """Validate scenario identity, time ordering, evidence boundaries, and factors."""
    scenario = _object(doc, "scenario", {
        "schema_version", "scenario_id", "description", "seed", "identities",
        "environment", "rf", "network", "trajectory", "movement", "faults",
        "localization", "blockchain", "expected_evidence",
    })
    if scenario["schema_version"] != SCHEMA_VERSION:
        raise BetaContractError(f"unsupported schema_version: {scenario['schema_version']!r}")
    for key in ("scenario_id", "description"):
        _text(scenario[key], f"scenario.{key}")
    if isinstance(scenario["seed"], bool) or not isinstance(scenario["seed"], int) or scenario["seed"] < 0:
        raise BetaContractError("scenario.seed must be a non-negative integer")

    identities = scenario["identities"]
    if not isinstance(identities, list) or not identities:
        raise BetaContractError("scenario.identities must be a non-empty array")
    required_ids = {"animal_id", "tag_id", "device_id"}
    seen: dict[str, set[str]] = {name: set() for name in required_ids}
    for index, raw in enumerate(identities):
        item = _object(raw, f"scenario.identities[{index}]", required_ids)
        for key in required_ids:
            value = _text(item[key], f"scenario.identities[{index}].{key}")
            if value in seen[key]:
                raise BetaContractError(f"duplicate {key}: {value}")
            seen[key].add(value)

    environment = _object(scenario["environment"], "scenario.environment",
                          {"farm_id", "coordinate_frame", "bounds_m", "classification"})
    _text(environment["farm_id"], "scenario.environment.farm_id")
    if environment["coordinate_frame"] != "ENU_LOCAL":
        raise BetaContractError("scenario.environment.coordinate_frame must be ENU_LOCAL")
    bounds = _object(environment["bounds_m"], "scenario.environment.bounds_m",
                     {"east_min_m", "east_max_m", "north_min_m", "north_max_m"})
    for key, value in bounds.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise BetaContractError(f"scenario.environment.bounds_m.{key} must be finite")
    if bounds["east_min_m"] >= bounds["east_max_m"] or bounds["north_min_m"] >= bounds["north_max_m"]:
        raise BetaContractError("scenario.environment.bounds_m limits must increase")
    if environment["classification"] not in EVIDENCE:
        raise BetaContractError("scenario.environment.classification is unknown")

    for key in ("rf", "network", "movement", "localization", "blockchain"):
        _object(scenario[key], f"scenario.{key}", {"mode", "classification"}, {"parameters"})
        _text(scenario[key]["mode"], f"scenario.{key}.mode")
        if scenario[key]["classification"] not in EVIDENCE:
            raise BetaContractError(f"scenario.{key}.classification is unknown")
    _object(scenario["trajectory"], "scenario.trajectory",
            {"source", "classification", "samples"})
    _text(scenario["trajectory"]["source"], "scenario.trajectory.source")
    if scenario["trajectory"]["classification"] not in EVIDENCE:
        raise BetaContractError("scenario.trajectory.classification is unknown")
    samples = scenario["trajectory"]["samples"]
    if not isinstance(samples, list) or not samples:
        raise BetaContractError("scenario.trajectory.samples must be a non-empty array")
    timestamps: dict[str, float] = {}
    observed_tags: set[str] = set()
    for index, raw in enumerate(samples):
        row = _object(raw, f"scenario.trajectory.samples[{index}]",
                      {"animal_id", "tag_id", "timestamp_s", "position_m"})
        if row["animal_id"] not in seen["animal_id"] or row["tag_id"] not in seen["tag_id"]:
            raise BetaContractError("trajectory identity does not resolve to a declared animal/tag")
        tag_to_animal = {item["tag_id"]: item["animal_id"] for item in identities}
        if tag_to_animal[row["tag_id"]] != row["animal_id"]:
            raise BetaContractError("trajectory animal_id/tag_id mapping is contradictory")
        timestamp = row["timestamp_s"]
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            raise BetaContractError("trajectory timestamp_s must be finite")
        if timestamp < 0 or timestamp <= timestamps.get(row["tag_id"], -1):
            raise BetaContractError("trajectory timestamps must increase strictly per tag")
        timestamps[row["tag_id"]] = float(timestamp)
        observed_tags.add(row["tag_id"])
        position = row["position_m"]
        if not isinstance(position, list) or len(position) != 3:
            raise BetaContractError("trajectory position_m must be [east, north, up]")
        if any(isinstance(part, bool) or not isinstance(part, (int, float)) or not math.isfinite(part)
               for part in position):
            raise BetaContractError("trajectory position_m values must be finite")
    if observed_tags != seen["tag_id"]:
        raise BetaContractError("every declared tag must have trajectory evidence")

    faults = scenario["faults"]
    if not isinstance(faults, list) or any(value not in FAULTS for value in faults):
        raise BetaContractError("scenario.faults contains an unsupported fault")
    evidence = scenario["expected_evidence"]
    if not isinstance(evidence, dict) or not evidence:
        raise BetaContractError("scenario.expected_evidence must be a non-empty object")
    if set(evidence.values()) - EVIDENCE:
        raise BetaContractError("scenario.expected_evidence contains an unknown classification")
    return scenario


def load_scenario(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"),
                           parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise BetaContractError(f"cannot load scenario JSON: {Path(path)}") from exc
    return validate_scenario(value)
