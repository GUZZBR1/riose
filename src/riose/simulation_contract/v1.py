"""Strict V1 JSON contract and deterministic serialization helpers.

Coordinates are local ENU meters; timestamps and propagation delays are seconds.
Received power is simulator output (dBm), never physical receiver RSSI unless a
backend explicitly declares that metric's semantics. This boundary does not
map values into product ``RFObservation`` records.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from collections.abc import Mapping
from typing import Any


REQUEST_SCHEMA = "riose.simulation.request/v1"
RESULT_SCHEMA = "riose.simulation.result/v1"
_FRAME = "ENU_LOCAL"
_EVIDENCE = {"SIMULATED", "ASSUMED", "EXPERIMENTAL", "FUTURE"}


class ContractError(ValueError):
    """Raised when a document does not satisfy its declared contract version."""


def _object(value: Any, where: str, required: set[str], optional: set[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{where} must be an object")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing:
        raise ContractError(f"{where} missing required fields: {', '.join(sorted(missing))}")
    if extra:
        raise ContractError(f"{where} has unsupported fields: {', '.join(sorted(extra))}")
    return value


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{where} must be a non-empty string")
    return value


def _timestamp(value: Any, where: str) -> None:
    text = _text(value, where)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{where} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(f"{where} must include a UTC offset")


def _number(value: Any, where: str, *, minimum: float | None = None, maximum: float | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ContractError(f"{where} must be a finite number")
    if minimum is not None and value < minimum:
        raise ContractError(f"{where} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ContractError(f"{where} must be <= {maximum}")


def _array(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{where} must be an array")
    return value


def _unique_ids(items: list[dict[str, Any]], key: str, where: str) -> None:
    ids = [_text(item.get(key), f"{where}[].{key}") for item in items]
    if len(set(ids)) != len(ids):
        raise ContractError(f"{where} contains duplicate {key}")


def validate_id_mappings(mappings: Any) -> None:
    """Require a one-to-one, explicitly namespaced source-to-RIOSE mapping."""
    items = _array(mappings, "id_mappings")
    sources: set[tuple[str, str, str]] = set()
    references: set[tuple[str, str]] = set()
    targets: set[tuple[str, str]] = set()
    for index, raw in enumerate(items):
        item = _object(raw, f"id_mappings[{index}", {"source_system", "source_kind", "source_id", "riose_kind", "riose_id"})
        source = tuple(_text(item[k], f"id_mappings[{index}].{k}") for k in ("source_system", "source_kind", "source_id"))
        target = (_text(item["riose_kind"], f"id_mappings[{index}].riose_kind"),
                  _text(item["riose_id"], f"id_mappings[{index}].riose_id"))
        reference = (source[1], source[2])
        if source in sources:
            raise ContractError(f"duplicate source identity mapping: {source}")
        if reference in references:
            raise ContractError(f"ambiguous source mapping for {reference}")
        if target in targets:
            raise ContractError(f"conflicting RIOSE identity mapping: {target}")
        sources.add(source)
        references.add(reference)
        targets.add(target)


def _mapping_index(mappings: list[dict[str, Any]]) -> dict[tuple[str, str], tuple[str, str]]:
    index = {}
    for item in mappings:
        source = (item["source_kind"], item["source_id"])
        target = (item["riose_kind"], item["riose_id"])
        if source in index:
            raise ContractError(f"ambiguous source mapping for {source}")
        index[source] = target
    return index


def validate_request(doc: Any) -> dict[str, Any]:
    d = _object(doc, "request", {"schema_version", "campaign_id", "scenario_id", "seed", "backend",
        "coordinate_frame", "units", "tags", "receivers", "id_mappings", "trajectory",
        "radio", "solver", "input_references", "provenance", "expected_evidence"},
        {"operational_bounds_m"})
    if d["schema_version"] != REQUEST_SCHEMA:
        raise ContractError(f"unsupported request schema_version: {d['schema_version']!r}")
    for key in ("campaign_id", "scenario_id", "backend"):
        _text(d[key], f"request.{key}")
    if isinstance(d["seed"], bool) or not isinstance(d["seed"], int) or d["seed"] < 0:
        raise ContractError("request.seed must be a non-negative integer")
    if d["coordinate_frame"] != _FRAME:
        raise ContractError("request.coordinate_frame must be ENU_LOCAL")
    if "operational_bounds_m" in d:
        bounds = _object(d["operational_bounds_m"], "request.operational_bounds_m",
                         {"east_min_m", "east_max_m", "north_min_m", "north_max_m"})
        for key, value in bounds.items():
            _number(value, f"request.operational_bounds_m.{key}")
        if bounds["east_min_m"] >= bounds["east_max_m"] or bounds["north_min_m"] >= bounds["north_max_m"]:
            raise ContractError("request.operational_bounds_m must have increasing east and north limits")
    units = _object(d["units"], "request.units", {"position", "timestamp", "frequency", "bandwidth", "power", "delay", "phase"})
    expected_units = {"position": "m", "timestamp": "s", "frequency": "Hz", "bandwidth": "Hz", "power": "dBm", "delay": "s", "phase": "rad"}
    if units != expected_units:
        raise ContractError("request.units must use the V1 units: m, s, Hz, dBm, s, rad")
    tags = _array(d["tags"], "request.tags")
    receivers = _array(d["receivers"], "request.receivers")
    if not tags or not receivers:
        raise ContractError("request requires at least one tag and receiver")
    validate_id_mappings(d["id_mappings"])
    mapping_index = _mapping_index(d["id_mappings"])
    for group_name, group, fields, optional_fields in (
            ("tags", tags, {"tag_ref", "transmitter_ref", "position_m", "trajectory_ref"},
             {"animal_ref", "device_ref"}),
            ("receivers", receivers, {"receiver_ref", "anchor_ref", "position_m"},
             {"gateway_ref"})):
        key = "tag_ref" if group_name == "tags" else "receiver_ref"
        for i, item in enumerate(group):
            _object(item, f"request.{group_name}[{i}]", fields, optional_fields)
            _text(item[key], f"request.{group_name}[{i}].{key}")
            if group_name == "tags":
                _text(item["transmitter_ref"], f"request.tags[{i}].transmitter_ref")
                for source_field, source_kind in (("animal_ref", "animal_id"), ("device_ref", "device_id")):
                    if source_field in item:
                        source_id = _text(item[source_field], f"request.tags[{i}].{source_field}")
                        if mapping_index.get((source_kind, source_id)) is None:
                            raise ContractError(f"tag {source_id!r} has no explicit {source_kind} mapping")
            else:
                _text(item["anchor_ref"], f"request.receivers[{i}].anchor_ref")
                if "gateway_ref" in item:
                    gateway_id = _text(item["gateway_ref"], f"request.receivers[{i}].gateway_ref")
                    if mapping_index.get(("gateway_id", gateway_id)) is None:
                        raise ContractError(f"gateway {gateway_id!r} has no explicit gateway_id mapping")
            _position(item["position_m"], f"request.{group_name}[{i}].position_m")
            if group_name == "tags" and item["trajectory_ref"] is not None:
                _text(item["trajectory_ref"], f"request.tags[{i}].trajectory_ref")
        _unique_ids(group, key, f"request.{group_name}")
    for item in tags:
        if mapping_index.get(("transmitter_id", item["transmitter_ref"])) != ("tag_id", item["tag_ref"]):
            raise ContractError(f"transmitter {item['transmitter_ref']!r} has no exact tag_id mapping")
    for item in receivers:
        if mapping_index.get(("receiver_id", item["receiver_ref"])) != ("anchor_id", item["anchor_ref"]):
            raise ContractError(f"receiver {item['receiver_ref']!r} has no exact anchor_id mapping")
    traj = _object(d["trajectory"], "request.trajectory", {"samples", "reference"})
    if (traj["samples"] is None) == (traj["reference"] is None):
        raise ContractError("trajectory must contain exactly one of samples or reference")
    if traj["reference"] is not None:
        _text(traj["reference"], "request.trajectory.reference")
    else:
        samples = _array(traj["samples"], "request.trajectory.samples")
        if not samples:
            raise ContractError("trajectory.samples must not be empty")
        known_tags = {item["tag_ref"] for item in tags}
        previous: dict[str, float] = {}
        timestamps_by_tag: dict[str, set[float]] = {}
        for i, raw in enumerate(samples):
            sample = _object(raw, f"trajectory.samples[{i}]", {"tag_ref", "timestamp_s", "position_m"})
            tag_ref = _text(sample["tag_ref"], f"trajectory.samples[{i}].tag_ref")
            if tag_ref not in known_tags:
                raise ContractError(f"trajectory sample references unknown tag {tag_ref!r}")
            _number(sample["timestamp_s"], f"trajectory.samples[{i}].timestamp_s", minimum=0)
            if tag_ref in previous and sample["timestamp_s"] <= previous[tag_ref]:
                raise ContractError(f"trajectory timestamps must increase strictly for tag {tag_ref!r}")
            previous[tag_ref] = float(sample["timestamp_s"])
            timestamps_by_tag.setdefault(tag_ref, set()).add(float(sample["timestamp_s"]))
            _position(sample["position_m"], f"trajectory.samples[{i}].position_m")
        if set(timestamps_by_tag) != known_tags or len({frozenset(values) for values in timestamps_by_tag.values()}) != 1:
            raise ContractError("every tag must have a trajectory sample at each shared timestamp")
    radio = _object(d["radio"], "request.radio", {"frequency_hz", "bandwidth_hz", "tx_power_dbm", "phy"})
    _number(radio["frequency_hz"], "radio.frequency_hz", minimum=1)
    _number(radio["tx_power_dbm"], "radio.tx_power_dbm", minimum=-100, maximum=100)
    if radio["bandwidth_hz"] is not None:
        _number(radio["bandwidth_hz"], "radio.bandwidth_hz", minimum=1)
    _object(radio["phy"], "radio.phy", set(), set(radio["phy"]))
    solver = _object(d["solver"], "request.solver", {"parameters"})
    _object(solver["parameters"], "request.solver.parameters", set(), set(solver["parameters"]))
    refs = _array(d["input_references"], "request.input_references")
    for i, raw in enumerate(refs):
        ref = _object(raw, f"input_references[{i}]", {"name", "sha256"})
        _text(ref["name"], f"input_references[{i}].name")
        digest = _text(ref["sha256"], f"input_references[{i}].sha256")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ContractError(f"input_references[{i}].sha256 must be lowercase SHA-256 hex")
    _object(d["provenance"], "request.provenance", {"riose_revision", "frequencia_revision", "dirty", "created_at"})
    if d["provenance"]["riose_revision"] is not None:
        _text(d["provenance"]["riose_revision"], "provenance.riose_revision")
    if d["provenance"]["frequencia_revision"] is not None:
        _text(d["provenance"]["frequencia_revision"], "provenance.frequencia_revision")
    if not isinstance(d["provenance"]["dirty"], bool):
        raise ContractError("provenance.dirty must be boolean")
    _timestamp(d["provenance"]["created_at"], "provenance.created_at")
    if d["expected_evidence"] not in _EVIDENCE:
        raise ContractError("request.expected_evidence must be a known non-validated evidence class")
    return d


def _position(value: Any, where: str) -> None:
    if not isinstance(value, list) or len(value) != 3:
        raise ContractError(f"{where} must be [east, north, up] in meters")
    for i, part in enumerate(value):
        _number(part, f"{where}[{i}]")


def validate_result(doc: Any) -> dict[str, Any]:
    d = _object(doc, "result", {"schema_version", "campaign_id", "scenario_id", "backend", "solver_version",
        "status", "id_mappings", "observations", "locations", "warnings", "limitations", "provenance"})
    if d["schema_version"] != RESULT_SCHEMA:
        raise ContractError(f"unsupported result schema_version: {d['schema_version']!r}")
    for key in ("campaign_id", "scenario_id", "backend", "status"):
        _text(d[key], f"result.{key}")
    if d["status"] != "SIMULATED":
        raise ContractError("contract fixture results must retain status SIMULATED")
    if d["solver_version"] is not None:
        _text(d["solver_version"], "result.solver_version")
    for key in ("warnings", "limitations"):
        for i, value in enumerate(_array(d[key], f"result.{key}")):
            _text(value, f"result.{key}[{i}]")
    _object(d["provenance"], "result.provenance", {"request_sha256", "output_sha256", "completed_at"})
    for key in ("request_sha256", "output_sha256"):
        value = d["provenance"][key]
        if value is not None and (not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
            raise ContractError(f"result.provenance.{key} must be null or lowercase SHA-256 hex")
    _timestamp(d["provenance"]["completed_at"], "result.provenance.completed_at")
    validate_id_mappings(d["id_mappings"])
    mapping_index = _mapping_index(d["id_mappings"])
    for i, raw in enumerate(_array(d["observations"], "result.observations")):
        o = _object(raw, f"observations[{i}]", {"timestamp_s", "source_tag_ref", "source_receiver_ref", "tag_id", "anchor_id",
            "channel_state", "tx_state", "rx_state", "metrics", "status"})
        _number(o["timestamp_s"], f"observations[{i}].timestamp_s", minimum=0)
        for k in ("source_tag_ref", "source_receiver_ref", "channel_state", "tx_state", "rx_state", "status"):
            _text(o[k], f"observations[{i}].{k}")
        for k in ("tag_id", "anchor_id"):
            if o[k] is not None:
                _text(o[k], f"observations[{i}].{k}")
        for source_kind, source_id, target_kind, target_id in (
            ("transmitter_id", o["source_tag_ref"], "tag_id", o["tag_id"]),
            ("receiver_id", o["source_receiver_ref"], "anchor_id", o["anchor_id"]),
        ):
            mapped = mapping_index.get((source_kind, source_id))
            if target_id is not None and mapped != (target_kind, target_id):
                raise ContractError(f"observations[{i}] has unknown or conflicting mapped identity for {source_id!r}")
        if o["status"] != "SIMULATED":
            raise ContractError("all simulator observations must remain SIMULATED")
        if o["channel_state"] not in {"PATH", "NO_PATH", "UNKNOWN"}:
            raise ContractError("channel_state must be PATH, NO_PATH, or UNKNOWN")
        if o["tx_state"] not in {"NOT_TRANSMITTED", "TRANSMITTED", "UNKNOWN"}:
            raise ContractError("invalid tx_state")
        if o["rx_state"] not in {"NOT_APPLICABLE", "NOT_RECEIVED", "RECEIVED", "PHY_NOT_RECEIVED", "PHY_RECEIVED", "DATA_UNAVAILABLE", "UNKNOWN"}:
            raise ContractError("invalid rx_state")
        metrics = _object(o["metrics"], f"observations[{i}].metrics", {"received_power_dbm", "rssi_dbm", "snr_db",
            "propagation_delay_s", "tof_measured_s", "phase_rad", "path_state"})
        if metrics["path_state"] not in {"LOS", "NLOS", "NO_PATH", "UNKNOWN", None}:
            raise ContractError("invalid metrics.path_state")
        if o["channel_state"] == "NO_PATH" or metrics["path_state"] == "NO_PATH":
            if any(metrics[k] is not None for k in ("received_power_dbm", "rssi_dbm", "snr_db", "propagation_delay_s", "tof_measured_s", "phase_rad")):
                raise ContractError("NO_PATH cannot contain received-signal metrics")
            if o["rx_state"] in {"RECEIVED", "PHY_RECEIVED"}:
                raise ContractError("NO_PATH cannot have rx_state RECEIVED")
        if o["tx_state"] == "NOT_TRANSMITTED" and o["rx_state"] in {"RECEIVED", "NOT_RECEIVED", "PHY_RECEIVED", "PHY_NOT_RECEIVED"}:
            raise ContractError("a non-transmitted packet cannot have a reception outcome")
        if o["channel_state"] == "NO_PATH" and o["rx_state"] in {"RECEIVED", "PHY_RECEIVED"}:
            raise ContractError("a NO_PATH channel cannot have a received packet")
        if o["rx_state"] in {"RECEIVED", "PHY_RECEIVED"} and o["tx_state"] != "TRANSMITTED":
            raise ContractError("a received packet requires tx_state TRANSMITTED")
        # Propagation models can report simulated channel power even when they
        # do not implement packet reception. Keep that metric distinct from RSSI.
        if o["channel_state"] != "PATH" and metrics["received_power_dbm"] is not None:
            raise ContractError("simulated received power requires a channel path")
        if o["rx_state"] not in {"RECEIVED", "PHY_RECEIVED"} and any(metrics[k] is not None for k in ("rssi_dbm", "snr_db")):
            raise ContractError("RSSI and SNR require a PHY reception")
        if metrics["rssi_dbm"] is not None and metrics["received_power_dbm"] is not None:
            raise ContractError("simulated received power and physical RSSI cannot be conflated")
        for key in ("received_power_dbm", "rssi_dbm", "snr_db", "propagation_delay_s", "tof_measured_s", "phase_rad"):
            if metrics[key] is not None:
                minimum = -200 if key in {"received_power_dbm", "rssi_dbm"} else -100 if key == "snr_db" else 0 if key in {"propagation_delay_s", "tof_measured_s"} else None
                maximum = 100 if key in {"received_power_dbm", "rssi_dbm", "snr_db"} else None
                _number(metrics[key], f"observations[{i}].metrics.{key}", minimum=minimum, maximum=maximum)
        if metrics["phase_rad"] is not None and not -math.pi <= metrics["phase_rad"] <= math.pi:
            raise ContractError(f"observations[{i}].metrics.phase_rad must use principal radians [-pi, pi]")
    for i, raw in enumerate(_array(d["locations"], "result.locations")):
        loc = _object(raw, f"locations[{i}]", {"timestamp_s", "source_tag_ref", "tag_id", "position_m", "quality", "method", "status"},
                      {"solver_status", "quality_status", "quality_reason", "quality_bounds_m"})
        _number(loc["timestamp_s"], f"locations[{i}].timestamp_s", minimum=0)
        _text(loc["source_tag_ref"], f"locations[{i}].source_tag_ref")
        if loc["tag_id"] is not None:
            _text(loc["tag_id"], f"locations[{i}].tag_id")
            if mapping_index.get(("transmitter_id", loc["source_tag_ref"])) != ("tag_id", loc["tag_id"]):
                raise ContractError(f"locations[{i}] has unknown or conflicting tag identity mapping")
        if loc["position_m"] is not None:
            position = loc["position_m"]
            if not isinstance(position, list) or len(position) not in {2, 3}:
                raise ContractError(f"locations[{i}].position_m must contain east/north and optional up in meters")
            for j, value in enumerate(position):
                _number(value, f"locations[{i}].position_m[{j}]")
        if loc["quality"] is not None:
            _number(loc["quality"], f"locations[{i}].quality", minimum=0, maximum=1)
        _text(loc["method"], f"locations[{i}].method")
        quality_fields = {"solver_status", "quality_status", "quality_reason", "quality_bounds_m"}
        if quality_fields & loc.keys():
            if not quality_fields <= loc.keys():
                raise ContractError(f"locations[{i}] must provide complete solver/quality audit fields")
            if not isinstance(loc["solver_status"], str) or not loc["solver_status"]:
                raise ContractError(f"locations[{i}].solver_status must be non-empty")
            if loc["quality_status"] not in {"ACCEPTED", "REJECTED", "NOT_EVALUATED"}:
                raise ContractError(f"locations[{i}].quality_status is invalid")
            if not isinstance(loc["quality_reason"], str) or not loc["quality_reason"]:
                raise ContractError(f"locations[{i}].quality_reason must be non-empty")
            bounds = loc["quality_bounds_m"]
            if bounds is not None:
                bounds = _object(bounds, f"locations[{i}].quality_bounds_m",
                                 {"east_min_m", "east_max_m", "north_min_m", "north_max_m"})
                for key, value in bounds.items():
                    _number(value, f"locations[{i}].quality_bounds_m.{key}")
                if bounds["east_min_m"] >= bounds["east_max_m"] or bounds["north_min_m"] >= bounds["north_max_m"]:
                    raise ContractError(f"locations[{i}].quality_bounds_m must have increasing limits")
            if loc["quality_status"] == "ACCEPTED" and loc["position_m"] is None:
                raise ContractError(f"locations[{i}] cannot accept a missing estimate")
            if loc["quality_status"] in {"ACCEPTED", "REJECTED"} and loc["quality_bounds_m"] is None:
                raise ContractError(f"locations[{i}] cannot evaluate quality without declared bounds")
            if loc["quality_status"] == "NOT_EVALUATED" and not loc["quality_reason"].strip():
                raise ContractError(f"locations[{i}] must explain why quality was not evaluated")
        if loc["status"] != "SIMULATED":
            raise ContractError("location status must remain SIMULATED")
    return d


def canonical_json(doc: Mapping[str, Any]) -> str:
    """Serialize JSON deterministically; reject NaN/Infinity and non-JSON values."""
    try:
        return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ContractError("document must contain only finite JSON-compatible values") from exc


def content_hash(doc: Mapping[str, Any]) -> str:
    """SHA-256 of canonical UTF-8 JSON, including array order by contract."""
    return hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest()


def load_json(raw: str, *, kind: str) -> dict[str, Any]:
    try:
        doc = json.loads(raw, parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ContractError("malformed JSON or non-finite numeric constant") from exc
    validator = {"request": validate_request, "result": validate_result}.get(kind)
    if validator is None:
        raise ContractError("kind must be request or result")
    return validator(doc)
