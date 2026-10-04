"""Translate validated simulation output without upgrading its evidence class.

The canonical ``RFObservation`` has no received-power field or channel-state
field. This adapter therefore defaults simulated power to unavailable and keeps
source states, per-run identity, coordinate frame, and units in a deterministic
sidecar aligned by record ID.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Any, Mapping

from riose.products.livestock_tracking.domain.contracts import Estimate, EvidenceStatus, RFObservation
from riose.simulation_contract.v1 import ContractError, content_hash, validate_result


class ConversionError(ValueError):
    """A result cannot be safely translated to canonical RIOSE contracts."""


class ConversionPolicy(StrEnum):
    STRICT = "STRICT"
    LENIENT = "LENIENT"


@dataclass(frozen=True, slots=True)
class ConversionReport:
    input_observations: int
    converted_observations: int
    input_locations: int
    converted_estimates: int
    skipped: int
    rejected: int
    non_received_observations: int
    warnings: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConversionBatch:
    observations: tuple[RFObservation, ...]
    estimates: tuple[Estimate, ...]
    # One sidecar entry per canonical record, with stable source identity.
    observation_provenance: tuple[Mapping[str, Any], ...]
    estimate_provenance: tuple[Mapping[str, Any], ...]
    report: ConversionReport


def _finite(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConversionError(f"{name} must be finite or null")
    return float(value)


def _mapping_index(result: Mapping[str, Any]) -> dict[tuple[str, str], tuple[str, str]]:
    mappings = result.get("id_mappings")
    if mappings is None and (result["observations"] or result["locations"]):
        raise ConversionError("result must carry explicit id_mappings")
    mappings = mappings or []
    index: dict[tuple[str, str], tuple[str, str]] = {}
    for row in mappings:
        source = (row["source_kind"], row["source_id"])
        target = (row["riose_kind"], row["riose_id"])
        if source in index or target in index.values():
            raise ConversionError("ambiguous or conflicting ID mapping")
        index[source] = target
    return index


def convert_result(
    result: Mapping[str, Any],
    *,
    policy: ConversionPolicy = ConversionPolicy.STRICT,
    map_received_power_to_rssi: bool = False,
    run_manifest: Mapping[str, Any] | None = None,
) -> ConversionBatch:
    """Convert a V1 result; power-to-RSSI mapping requires explicit opt-in.

    ``propagation_delay_s`` is converted to ``tof_ns`` only with explicit
    sidecar semantics ``SIMULATED_PROPAGATION_DELAY``; it is never labeled a
    measured hardware ToF. Location estimates keep the result's coordinate
    frame in their sidecar and retain only east/north in canonical Estimate.
    """
    pre_rejected = 0
    pre_reasons: list[str] = []
    candidate = dict(result)
    if policy == ConversionPolicy.LENIENT and isinstance(candidate.get("observations"), list):
        accepted = []
        for i, row in enumerate(candidate["observations"]):
            probe = dict(candidate, observations=[row], locations=[])
            try:
                validate_result(probe)
                accepted.append(row)
            except ContractError as exc:
                pre_rejected += 1
                pre_reasons.append(f"observations[{i}]: {exc}")
        candidate["observations"] = accepted
    if policy == ConversionPolicy.LENIENT and isinstance(candidate.get("locations"), list):
        accepted = []
        for i, row in enumerate(candidate["locations"]):
            probe = dict(candidate, observations=[], locations=[row])
            try:
                validate_result(probe)
                accepted.append(row)
            except ContractError as exc:
                pre_rejected += 1
                pre_reasons.append(f"locations[{i}]: {exc}")
        candidate["locations"] = accepted
    try:
        doc = validate_result(candidate)
        mappings = _mapping_index(doc)
    except (ContractError, KeyError, TypeError, ValueError) as exc:
        raise ConversionError(str(exc)) from exc
    source_system_by_identity = {
        (row["source_kind"], row["source_id"]): row["source_system"]
        for row in doc["id_mappings"]
    }
    if run_manifest is not None:
        engine = run_manifest.get("engine")
        if (run_manifest.get("campaign_id") != doc["campaign_id"]
                or run_manifest.get("backend_used") != doc["backend"]
                or run_manifest.get("evidence_classification") != "SIMULATED"
                or not isinstance(engine, Mapping)
                or engine.get("actual_sha") != doc["solver_version"]
                or run_manifest.get("output_sha256") != doc["provenance"]["output_sha256"]
                or run_manifest.get("request_sha256") != doc["provenance"]["request_sha256"]):
            raise ConversionError("result conflicts with run manifest provenance or backend")

    seen_records: set[tuple[str, str, float]] = set()
    previous_by_link: dict[tuple[str, str], float] = {}
    for i, row in enumerate(doc["observations"]):
        record_key = (row["source_tag_ref"], row["source_receiver_ref"], row["timestamp_s"])
        if record_key in seen_records:
            raise ConversionError(f"observations[{i}] duplicates a tag/receiver/timestamp record")
        seen_records.add(record_key)
        link = record_key[:2]
        if row["timestamp_s"] < previous_by_link.get(link, -math.inf):
            raise ConversionError(f"observations[{i}] timestamp is out of order for its tag/receiver link")
        previous_by_link[link] = row["timestamp_s"]

    run_id = f"{doc['campaign_id']}:{doc['scenario_id']}:{content_hash(doc)}"
    warnings = list(doc["warnings"])
    if map_received_power_to_rssi:
        warnings.append("received_power_dbm explicitly mapped to RFObservation.rssi_dbm; value remains SIMULATED, not hardware RSSI")
    observations: list[RFObservation] = []
    obs_meta: list[Mapping[str, Any]] = []
    estimates: list[Estimate] = []
    est_meta: list[Mapping[str, Any]] = []
    reasons: list[str] = list(pre_reasons)
    rejected = pre_rejected
    skipped = 0

    for i, row in enumerate(doc["observations"]):
        try:
            tag = mappings.get(("transmitter_id", row["source_tag_ref"]))
            anchor = mappings.get(("receiver_id", row["source_receiver_ref"]))
            if tag != ("tag_id", row["tag_id"]) or anchor != ("anchor_id", row["anchor_id"]):
                raise ConversionError(f"observations[{i}] has unresolved or conflicting identity mapping")
            metrics = row["metrics"]
            power = _finite(metrics["received_power_dbm"], f"observations[{i}].received_power_dbm")
            rssi = _finite(metrics["rssi_dbm"], f"observations[{i}].rssi_dbm")
            if rssi is None and map_received_power_to_rssi:
                rssi = power
                rssi_source = "received_power_dbm_explicitly_mapped"
            else:
                rssi_source = "rssi_dbm" if rssi is not None else None
            snr = _finite(metrics["snr_db"], f"observations[{i}].snr_db")
            delay = _finite(metrics["propagation_delay_s"], f"observations[{i}].propagation_delay_s")
            phase = _finite(metrics["phase_rad"], f"observations[{i}].phase_rad")
            received = row["rx_state"] in {"RECEIVED", "PHY_RECEIVED"}
            observations.append(RFObservation(
                timestamp_s=float(row["timestamp_s"]), tag_id=row["tag_id"], anchor_id=row["anchor_id"],
                rssi_dbm=rssi, snr_db=snr, packet_received=received,
                tof_ns=delay * 1e9 if delay is not None else None,
                phase_rad=phase, status=EvidenceStatus.SIMULATED,
            ))
            obs_meta.append({
                "record_id": f"{run_id}:observation:{i}", "run_id": run_id,
                "campaign_id": doc["campaign_id"], "scenario_id": doc["scenario_id"],
                "backend": doc["backend"], "solver_version": doc["solver_version"],
                "source_system": source_system_by_identity[("transmitter_id", row["source_tag_ref"])],
                "source_tag_ref": row["source_tag_ref"], "source_receiver_ref": row["source_receiver_ref"],
                "channel_state": row["channel_state"], "tx_state": row["tx_state"], "rx_state": row["rx_state"],
                "path_state": metrics["path_state"], "status": "SIMULATED",
                "received_power_dbm": power, "rssi_source": rssi_source,
                "snr_source": "result.snr_db" if snr is not None else None,
                "tof_semantics": "SIMULATED_PROPAGATION_DELAY" if delay is not None else None,
                "propagation_delay_s": delay, "phase_semantics": "result.phase_rad" if phase is not None else None,
                "coordinate_frame": "not_applicable", "provenance": dict(doc["provenance"]),
            })
        except (ConversionError, KeyError, TypeError, ValueError) as exc:
            rejected += 1
            reasons.append(str(exc))
            if policy == ConversionPolicy.STRICT:
                raise ConversionError(str(exc)) from exc

    for i, row in enumerate(doc["locations"]):
        try:
            tag = mappings.get(("transmitter_id", row["source_tag_ref"]))
            if tag != ("tag_id", row["tag_id"]):
                raise ConversionError(f"locations[{i}] has unresolved or conflicting tag mapping")
            pos = row["position_m"]
            estimates.append(Estimate(
                timestamp_s=float(row["timestamp_s"]), tag_id=row["tag_id"],
                x=float(pos[0]) if pos is not None else None,
                y=float(pos[1]) if pos is not None else None,
                method=row["method"], quality=row["quality"], status=EvidenceStatus.SIMULATED,
            ))
            est_meta.append({
                "record_id": f"{run_id}:estimate:{i}", "run_id": run_id,
                "campaign_id": doc["campaign_id"], "scenario_id": doc["scenario_id"],
                "backend": doc["backend"], "coordinate_frame": "ENU_LOCAL", "position_units": "m",
                "source_system": source_system_by_identity[("transmitter_id", row["source_tag_ref"])],
                "source_tag_ref": row["source_tag_ref"], "source_z_m": pos[2] if pos is not None and len(pos) > 2 else None,
                "method": row["method"], "status": "SIMULATED", "provenance": dict(doc["provenance"]),
                "solver_status": row.get("solver_status"),
                "quality_status": row.get("quality_status"),
                "quality_reason": row.get("quality_reason"),
                "quality_bounds_m": row.get("quality_bounds_m"),
            })
        except (ConversionError, KeyError, TypeError, ValueError) as exc:
            rejected += 1
            reasons.append(str(exc))
            if policy == ConversionPolicy.STRICT:
                raise ConversionError(str(exc)) from exc

    non_received = sum(row["rx_state"] not in {"RECEIVED", "PHY_RECEIVED"} for row in doc["observations"])
    return ConversionBatch(
        tuple(observations), tuple(estimates), tuple(obs_meta), tuple(est_meta),
        ConversionReport(len(result.get("observations", [])), len(observations), len(result.get("locations", [])),
                         len(estimates), skipped, rejected, non_received, tuple(warnings), tuple(reasons)),
    )
