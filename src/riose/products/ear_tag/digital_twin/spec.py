"""Hardware spec loading, provenance validation, and prototype-readiness gate."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import yaml


ALLOWED_STATUSES = {"DATASHEET", "ASSUMED", "SIMULATED"}
FORBIDDEN_STATUSES = {"MEASURED"}
REVIEW_KEYS = ("thresholds", "dimensions", "antenna", "fit")
ALLOWED_UNITS = {
    "A", "F", "Hz", "MHz", "GHz", "S/m", "V", "mV", "uV", "dB", "dBm",
    "deg", "degC", "g/cm3", "mA", "uA", "mAh", "uAh", "mm", "cm", "m", "in",
    "ohm", "kOhm", "part_number", "percent", "ratio", "reference", "s", "ms",
    "us", "topology", "mg", "g", "kg", "m/s2", "fraction", "text", "count",
}


class SpecError(ValueError):
    """Raised when a digital-only hardware specification is invalid."""


def load_spec(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    spec = yaml.safe_load(raw)
    if not isinstance(spec, dict):
        raise SpecError("hardware spec root must be a mapping")
    validate_spec(spec)
    return spec, hashlib.sha256(raw).hexdigest()


def validate_spec(spec: dict[str, Any]) -> None:
    if spec.get("schema_version") != 1:
        raise SpecError("schema_version must equal 1")
    if spec.get("milestone") != "MVP2_DIGITAL_TWIN":
        raise SpecError("milestone must be MVP2_DIGITAL_TWIN")
    forbidden = []
    malformed = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            if any(key in value for key in ("value", "unit", "source", "status")):
                status = str(value.get("status", "")).upper()
                if status in FORBIDDEN_STATUSES:
                    forbidden.append(path)
                elif status not in ALLOWED_STATUSES:
                    malformed.append(f"{path}.status={status!r}")
                missing = {"value", "unit", "source", "status"} - value.keys()
                if missing:
                    malformed.append(f"{path} missing {', '.join(sorted(missing))}")
                else:
                    if not isinstance(value["unit"], str) or not value["unit"].strip():
                        malformed.append(f"{path}.unit must be a non-empty string")
                    elif value["unit"] not in ALLOWED_UNITS:
                        malformed.append(f"{path}.unit is unsupported: {value['unit']!r}")
                    if not isinstance(value["source"], str) or not value["source"].strip():
                        malformed.append(f"{path}.source must be a non-empty string")
                    parameter = value["value"]
                    if isinstance(parameter, bool):
                        malformed.append(f"{path}.value must not be boolean")
                    elif isinstance(parameter, (int, float)) and not math.isfinite(parameter):
                        malformed.append(f"{path}.value must be finite")
                    elif not isinstance(parameter, (int, float, str)):
                        malformed.append(f"{path}.value must be a number or string")
                    elif isinstance(parameter, str) and not parameter.strip():
                        malformed.append(f"{path}.value must not be empty")
                    source = value.get("source")
                    if status == "DATASHEET" and isinstance(source, str) and source.strip().lower() in {
                        "assumed", "placeholder", "unknown", "n/a", "none"
                    }:
                        malformed.append(f"{path}.source must identify the datasheet or source document")
            for key, child in value.items():
                walk(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(spec, "")
    if forbidden:
        raise SpecError("MEASURED status is forbidden in digital-only MVP2: " + ", ".join(forbidden))
    if malformed:
        raise SpecError("Invalid spec: " + "; ".join(malformed))
    required = (
        "components.mcu.model", "components.radio.model", "components.imu.model",
        "components.battery.model", "regulator.model", "mechanical.enclosure.width_mm",
        "mechanical.enclosure.height_mm", "mechanical.enclosure.thickness_mm",
        "antenna.center_frequency_hz", "antenna.topology", "gate.provisional_limits",
    )
    missing = [key for key in required if _get(spec, key) is None]
    if missing:
        raise SpecError("Missing required spec keys: " + ", ".join(missing))
    for key in ("gate.provisional_limits", "gate.approval"):
        if not isinstance(_get(spec, key), dict):
            raise SpecError(f"{key} must be a mapping")
    approvals = _get(spec, "gate.approval")
    invalid_approvals = [key for key in REVIEW_KEYS if approvals.get(key) not in {"PENDING", "APPROVED"}]
    if invalid_approvals:
        raise SpecError("gate.approval entries must be PENDING or APPROVED: " + ", ".join(invalid_approvals))
    if spec.get("evidence_policy", {}).get("design_review_status") != "PENDING":
        raise SpecError("design_review_status must remain PENDING in this milestone")


def _get(mapping: dict[str, Any], dotted: str) -> Any:
    current: Any = mapping
    for key in dotted.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def parameter_statuses(spec: dict[str, Any]) -> dict[str, int]:
    totals = {status: 0 for status in sorted(ALLOWED_STATUSES)}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if "status" in value and str(value["status"]).upper() in totals:
                totals[str(value["status"]).upper()] += 1
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(spec)
    return totals


def evaluate_gate(spec: dict[str, Any], stages: dict[str, dict[str, Any]],
                  required_stage_names: tuple[str, ...] = ()) -> dict[str, Any]:
    """Fail closed; conditional readiness requires passing provisional limits."""
    blockers: list[str] = []
    failed: list[str] = []
    for name in required_stage_names:
        if name not in stages:
            blockers.append(f"{name}: MISSING")
    for name, result in stages.items():
        if not result.get("required", True):
            continue
        if result.get("status") not in {"COMPLETED", "PASSED"}:
            blockers.append(f"{name}: {result.get('status', 'UNKNOWN')}")
        for check in result.get("checks", []):
            if check.get("passed") is False:
                failed.append(f"{name}: {check.get('name', 'unnamed check')}")
    if failed or blockers:
        state = "NOT_READY_FOR_PHYSICAL_PROTOTYPE"
    else:
        approvals = spec.get("gate", {}).get("approval", {})
        pending = [key for key in REVIEW_KEYS if approvals.get(key) != "APPROVED"]
        if pending:
            state = "CONDITIONALLY_READY_PENDING_THRESHOLD_APPROVAL"
            blockers.extend(f"approval pending: {key}" for key in pending)
        else:
            state = "READY_FOR_PHYSICAL_PROTOTYPE"
    return {
        "state": state,
        "blockers": sorted(set(blockers + failed)),
        "failed_checks": failed,
        "approval": spec.get("gate", {}).get("approval", {}),
        "meaning": "Digital plausibility for a first prototype only; not product validation or measured evidence.",
    }


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
