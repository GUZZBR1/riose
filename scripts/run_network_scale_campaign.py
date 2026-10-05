"""Expand and execute the network-scale matrix through the RIOSE Simulation Lab."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from riose.simulation_contract import canonical_json, validate_request
from riose.simulation_lab.runner import EXPECTED_FREQUENCIA_SHA, run


GATEWAY_POSITIONS = (
    (20.0, 20.0, 12.0), (980.0, 20.0, 12.0),
    (980.0, 980.0, 12.0), (20.0, 980.0, 12.0),
    (500.0, 20.0, 12.0), (980.0, 500.0, 12.0),
    (500.0, 980.0, 12.0), (20.0, 500.0, 12.0),
)


def _hash_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _tag_position(index: int, count: int, distribution: str) -> list[float]:
    if count == 1:
        return [120.0, 200.0, 10.78]
    if distribution == "clustered":
        x, y = 480.0 + (index % 5) * 5.0, 480.0 + (index // 5) * 5.0
    elif distribution == "edge-heavy":
        x = 15.0 + (index % 2) * 970.0
        y = 80.0 + (index * 173) % 840.0
    elif distribution == "gateway-near":
        x, y = 25.0 + (index % 4) * 10.0, 25.0 + (index // 4) * 10.0
    elif distribution == "gateway-far":
        x, y = 485.0 + (index % 7) * 5.0, 485.0 + (index // 7) * 5.0
    elif distribution == "gateway-control":
        # Reuse the reachable single-tag point to remove spatial variation
        # from paired contention probes. Co-location is intentionally synthetic.
        x, y = 120.0, 200.0
    else:
        # Deterministic low-discrepancy placement across the synthetic 1 km field.
        x = 40.0 + ((index * 347) % 920)
        y = 40.0 + ((index * 541) % 920)
    return [float(x), float(y), 10.78]


def build_request(base: dict[str, Any], cell: dict[str, Any], seed: int) -> dict[str, Any]:
    """Bind one explicit simulated configuration to the current FARM contract."""
    tags_count = int(cell["tags"])
    gateway_count = int(cell["gateways"])
    cadence = int(cell["cadence_s"])
    if tags_count < 1 or not 3 <= gateway_count <= 8 or cadence < 1:
        raise ValueError("tags must be positive, gateways 3..8, and cadence_s a positive integer")
    distribution = str(cell.get("distribution", "uniform"))
    request = deepcopy(base)
    tags = []
    for index in range(tags_count):
        number = index + 1
        tag_ref = f"riose-tag-{number:03d}"
        tags.append({
            "tag_ref": tag_ref, "transmitter_ref": f"tx-{number:03d}",
            "animal_ref": f"animal-{number:03d}", "device_ref": f"device-{number:03d}",
            "position_m": _tag_position(index, tags_count, distribution),
            "trajectory_ref": "network-scale-synthetic-trajectory",
        })
    receivers = []
    for index, (east, north, up) in enumerate(GATEWAY_POSITIONS[:gateway_count], start=1):
        gateway = f"GW-{index}"
        receivers.append({"receiver_ref": f"rx-{gateway}", "gateway_ref": gateway,
                          "anchor_ref": f"riose-anchor-{index:03d}",
                          "position_m": [east, north, up]})
    samples = []
    raw_epochs = cell.get("epochs", 3)
    if isinstance(raw_epochs, bool) or not isinstance(raw_epochs, int) or raw_epochs < 1:
        raise ValueError("epochs must be a positive integer")
    epochs = raw_epochs
    schedule = str(cell.get("schedule", "SEEDED_PHASE"))
    for step in range(epochs):
        for tag in tags:
            x, y, z = tag["position_m"]
            timestamp = float(step * cadence)
            if schedule in {"SEEDED_PHASE", "NEAR_SYNCHRONIZED"}:
                # FREQUENCIA applies these device phases downstream.
                pass
            elif schedule not in {"SOURCE_TIMESTAMP", "SYNCHRONIZED"}:
                raise ValueError(f"unsupported schedule mode: {schedule}")
            position = [x, y, z] if distribution == "gateway-control" else [x + step, y + 0.5 * step, z]
            samples.append({"tag_ref": tag["tag_ref"], "timestamp_s": timestamp,
                            "position_m": position})
    mappings = []
    for tag in tags:
        mappings.extend([
            {"source_system": "frequencia", "source_kind": "animal_id",
             "source_id": tag["animal_ref"], "riose_kind": "animal_id",
             "riose_id": f"riose-{tag['animal_ref']}"},
            {"source_system": "RIOSE", "source_kind": "device_id",
             "source_id": tag["device_ref"], "riose_kind": "device_id",
             "riose_id": f"riose-{tag['device_ref']}"},
            {"source_system": "frequencia", "source_kind": "transmitter_id",
             "source_id": tag["transmitter_ref"], "riose_kind": "tag_id",
             "riose_id": tag["tag_ref"]},
        ])
    for receiver in receivers:
        index = int(receiver["gateway_ref"].split("-")[1])
        mappings.extend([
            {"source_system": "frequencia", "source_kind": "gateway_id",
             "source_id": receiver["gateway_ref"], "riose_kind": "gateway_id",
             "riose_id": f"riose-gateway-{index:03d}"},
            {"source_system": "frequencia", "source_kind": "receiver_id",
             "source_id": receiver["receiver_ref"], "riose_kind": "anchor_id",
             "riose_id": receiver["anchor_ref"]},
        ])

    if schedule in {"SOURCE_TIMESTAMP", "SYNCHRONIZED"}:
        phase_interval: float | None = None
    elif schedule == "SEEDED_PHASE":
        phase_interval = float(cell.get("phase_window_s") or cadence)
    elif schedule == "NEAR_SYNCHRONIZED":
        phase_interval = float(cell.get("phase_window_s") or 0.01)
    else:
        raise ValueError(f"unsupported schedule mode: {schedule}")

    case_key = (f"{tags_count}t-{gateway_count}g-{cadence}s-{epochs}e-{schedule.lower()}-"
                f"sf{int(cell.get('sf', 7))}-p{int(cell.get('payload_bytes', 12))}-"
                f"{distribution}-s{seed}")
    request["campaign_id"] = f"network-scale-{case_key}"
    request["scenario_id"] = f"synthetic-farm-network-{distribution}"
    request["seed"] = seed
    request["tags"] = tags
    request["receivers"] = receivers
    request["id_mappings"] = mappings
    request["trajectory"] = {"samples": samples, "reference": None}
    request["radio"]["phy"]["spreading_factor"] = int(cell.get("sf", 7))
    network = request["solver"]["parameters"]["network"]
    network.update({"spreading_factor": int(cell.get("sf", 7)),
                    "payload_bytes": int(cell.get("payload_bytes", 12)),
                    "traffic_interval_s": phase_interval})
    old_clocks = request["solver"]["parameters"]["temporal"]["clocks"]
    request["solver"]["parameters"]["temporal"]["clocks"] = {
        receiver["gateway_ref"]: old_clocks.get(receiver["gateway_ref"], {
            "offset_s": 0.0, "drift_ppm": 0.0,
            "jitter_std_s": 2.0e-9, "quantization_s": 1.0e-9,
        }) for receiver in receivers
    }
    request["provenance"]["created_at"] = "2026-10-05T00:00:00Z"
    request["provenance"]["dirty"] = False
    validate_request(request)
    return request


def expand_cells(spec: dict[str, Any]) -> list[dict[str, Any]]:
    expanded = []
    for group in spec["run_sets"]:
        for tags in group["tags"]:
            for gateways in group["gateways"]:
                for cadence in group["cadence_s"]:
                    for schedule in group["schedules"]:
                        for sf in group["spreading_factors"]:
                            for payload in group["payload_bytes"]:
                                for seed in group["seeds"]:
                                    expanded.append({
                                        "set_id": group["id"], "tags": tags, "gateways": gateways,
                                        "cadence_s": cadence, "schedule": schedule,
                                        "phase_window_s": group.get("phase_window_s"),
                                        "sf": sf, "payload_bytes": payload, "seed": seed,
                                        "distribution": group.get("distribution", "uniform"),
                                        "epochs": group.get("epochs", 3),
                                        "load_class": group.get("load_class", "ENGINEERING_SCENARIO"),
                                    })
    return expanded


def _packet_loss_summary(network: dict[str, Any]) -> dict[str, Any]:
    """Classify each requested packet without conflating link paths and PHY loss."""
    outcomes: dict[int, list[str]] = {}
    links: dict[int, list[dict[str, Any]]] = {}
    for event in network["gateway_events"]:
        event_index = int(event["event_index"])
        outcomes.setdefault(event_index, []).append(str(event["outcome"]))
        links.setdefault(event_index, []).append(event)
    counts: Counter[str] = Counter()
    rf_reachable = 0
    rf_reachable_received = 0
    packets = network["packets"]
    for packet in packets:
        index = int(packet["event_index"])
        states = outcomes.get(index, [])
        packet_links = links.get(index, [])
        if packet.get("tx_start_s") is None:
            counts["NOT_TRANSMITTED"] += 1
            continue
        has_rf_path = any(row.get("channel_status") != "NO_PATH" for row in packet_links)
        rf_reachable += int(has_rf_path)
        received = bool(packet.get("received_gateway_ids"))
        rf_reachable_received += int(has_rf_path and received)
        if received:
            counts["PHY_RECEIVED"] += 1
        elif "INTERFERENCE" in states:
            counts["INTERFERENCE_LOSS"] += 1
        elif states and all(value == "NO_PATH" for value in states):
            counts["NO_PATH"] += 1
        elif "NO_DEMODULATOR" in states:
            counts["NO_DEMODULATOR"] += 1
        elif "UNDER_SENSITIVITY" in states:
            counts["UNDER_SENSITIVITY"] += 1
        elif "UNTRACED_DROP" in states:
            counts["UNTRACED_DROP"] += 1
        else:
            counts["UNKNOWN_LOSS"] += 1
    return {
        "counts": dict(sorted(counts.items())),
        "requested_packet_denominator": len(packets),
        "tx_packet_denominator": int(network["metrics"]["transmitted_packets"]),
        "rf_reachable_tx_packets": rf_reachable,
        "rf_reachable_received_packets": rf_reachable_received,
        "pdr_conditional_on_rf_path": rf_reachable_received / rf_reachable if rf_reachable else None,
    }


def _summarize(report: dict[str, Any], cell: dict[str, Any], request_hash: str) -> dict[str, Any]:
    workspace = Path(report["workspace"])
    manifest = report["manifest"]
    network_path = workspace / "network" / "network_results.json"
    timestamps_path = workspace / "network" / "gateway_timestamps.json"
    localization_path = workspace / "network" / "localization.json"
    network = json.loads(network_path.read_text(encoding="utf-8"))
    timestamps = json.loads(timestamps_path.read_text(encoding="utf-8"))["records"]
    localization = json.loads(localization_path.read_text(encoding="utf-8"))
    outcomes = Counter(row["outcome"] for row in network["gateway_events"])
    latencies = sorted(float(row["latency_s"]) for row in network["gateway_events"]
                       if row.get("outcome") == "RX" and row.get("latency_s") is not None)
    airtimes = [float(row["airtime_s"]) for row in network["packets"]
                if row.get("tx_start_s") is not None and row.get("airtime_s") is not None]
    timestamp_counts: Counter[str] = Counter()
    for row in timestamps:
        if row.get("tdoa_timestamp_s") is not None:
            timestamp_counts[str(row["packet_id"])] += 1
    tx_packets = [row for row in network["packets"] if row.get("tx_start_s") is not None]
    packet_summary = _packet_loss_summary(network)
    actual_tx_times = sorted(float(row["tx_start_s"]) for row in tx_packets)
    tx_start_delays = [float(row["tx_start_s"]) - float(row["timestamp_s"])
                       for row in tx_packets]
    eligible_epochs = sum(timestamp_counts[str(row["event_index"])] >= 3 for row in tx_packets)
    eligible_anchor_observations = sum(timestamp_counts.values())
    delivered = int(network["metrics"]["delivered_packets"])
    transmitted = int(network["metrics"]["transmitted_packets"])
    pdr = network["metrics"]["pdr"]
    effective_phase_window = cell["phase_window_s"]
    if cell["schedule"] in {"SOURCE_TIMESTAMP", "SYNCHRONIZED"}:
        effective_phase_window = None
    elif cell["schedule"] == "SEEDED_PHASE" and effective_phase_window is None:
        effective_phase_window = cell["cadence_s"]
    elif cell["schedule"] == "NEAR_SYNCHRONIZED" and effective_phase_window is None:
        effective_phase_window = 0.01
    configuration = {key: cell[key] for key in (
        "tags", "gateways", "cadence_s", "schedule", "phase_window_s",
        "sf", "payload_bytes", "seed", "distribution", "load_class", "epochs")}
    configuration["phase_window_s"] = effective_phase_window
    parameter_binding = manifest.get("parameter_binding", {})
    actual_network = manifest.get("network", {})
    interference_packets = sum(any(
        event["event_index"] == packet["event_index"] and event["outcome"] == "INTERFERENCE"
        for event in network["gateway_events"]) for packet in tx_packets)
    return {
        "status": "SIMULATED", "set_id": cell["set_id"],
        "configuration": configuration,
        "run_id": report["run_id"], "workspace": str(workspace),
        "request_sha256": request_hash, "riose_sha": manifest["riose"]["revision"],
        "riose_dirty": manifest["riose"]["dirty"],
        "frequencia_sha": manifest["engine"]["actual_sha"],
        "frequencia_dirty": manifest["engine"]["dirty"],
        "raw_output_sha256": manifest["raw_output_sha256"],
        "network_output_sha256": hashlib.sha256(network_path.read_bytes()).hexdigest(),
        "requested_config": {
            **configuration,
            "network": parameter_binding.get("network", {}).get("requested", {}),
            "radio_and_backend": parameter_binding.get("radio_and_backend", {}).get("requested", {}),
            },
        "effective_config": {
            "backend": network["network_backend"],
            "channel_backend": network["channel_backend"],
            "network_parameter_binding_status": parameter_binding.get("network", {}).get("status"),
            "network_parameters": parameter_binding.get("network", {}).get("effective", {}),
            "bandwidth_hz": actual_network.get("bandwidth_hz"),
            "traffic_schedule": network.get("traffic_schedule"),
            "traffic_interval_s": network.get("traffic_interval_s"),
            "tx_attempted": transmitted, "requested_packets": int(network["metrics"]["requested_packets"]),
            "unique_ns3_tx_start_count": len(actual_tx_times),
            "actual_tx_start_delay_s": {
                "n": len(tx_start_delays), "mean": sum(tx_start_delays) / len(tx_start_delays)
                if tx_start_delays else None,
                "min": min(tx_start_delays) if tx_start_delays else None,
                "max": max(tx_start_delays) if tx_start_delays else None,
            },
        },
        "runtime_s": manifest["duration_seconds"],
        "requested_packets": int(network["metrics"]["requested_packets"]),
        "tx_attempted": transmitted, "phy_received_packets": delivered,
        "pdr_phy": pdr, "pdr_denominator": transmitted,
        "packet_loss_after_tx": transmitted - delivered,
        "packet_outcome_requested_denominator": packet_summary["requested_packet_denominator"],
        "packet_outcome_denominator_tx": packet_summary["tx_packet_denominator"],
        "packet_outcome_counts": packet_summary["counts"],
        "rf_reachable_tx_packets": packet_summary["rf_reachable_tx_packets"],
        "rf_reachable_received_packets": packet_summary["rf_reachable_received_packets"],
        "pdr_conditional_on_rf_path": packet_summary["pdr_conditional_on_rf_path"],
        "gateway_outcomes": dict(sorted(outcomes.items())),
        "interference_gateway_events": outcomes["INTERFERENCE"],
        "interference_gateway_event_rate": (
            outcomes["INTERFERENCE"] / len(network["gateway_events"])
            if network["gateway_events"] else None),
        "gateway_event_denominator": len(network["gateway_events"]),
        "packets_with_interference": interference_packets,
        "packet_interference_rate": interference_packets / transmitted if transmitted else None,
        "packet_interference_denominator": transmitted,
        "gateway_receptions": outcomes["RX"],
        "mean_phy_latency_s": sum(latencies) / len(latencies) if latencies else None,
        "p95_phy_latency_s": latencies[min(len(latencies) - 1, math.ceil(0.95 * len(latencies)) - 1)] if latencies else None,
        "latency_denominator_rx_events": len(latencies),
        "mean_airtime_s": sum(airtimes) / len(airtimes) if airtimes else None,
        "airtime_denominator_tx": len(airtimes),
        "gateway_reception_diversity_mean": (
            sum(len(row.get("received_gateway_ids", [])) for row in tx_packets) / transmitted
            if transmitted else None),
        "eligible_anchor_observations": eligible_anchor_observations,
        "eligible_anchor_observation_denominator": transmitted * int(cell["gateways"]),
        "localization_epochs": transmitted,
        "epochs_with_at_least_3_anchors": eligible_epochs,
        "localization_input_availability": eligible_epochs / transmitted if transmitted else None,
        "tdoa_eligible_epochs": localization.get("metrics", {}).get("tdoa", {}).get("eligible_packets"),
        "tdoa_converged_epochs": localization.get("metrics", {}).get("tdoa", {}).get("converged_packets"),
        "quality_accuracy_claim": "NOT_INFERRED_FROM_AVAILABILITY",
    }


def execute(spec_path: Path, base_path: Path, frequencia_repo: Path,
            output_dir: Path, timeout: float, set_ids: set[str] | None = None,
            limit: int | None = None) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    base = json.loads(base_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    requests_dir = output_dir / "requests"
    requests_dir.mkdir(exist_ok=True)
    results_path = output_dir / "campaign-results.json"
    records: list[dict[str, Any]] = []
    completed_by_request: dict[str, dict[str, Any]] = {}
    cells = [cell for cell in expand_cells(spec)
             if set_ids is None or cell["set_id"] in set_ids]
    if limit is not None:
        cells = cells[:limit]
    for cell in cells:
        request = build_request(base, cell, int(cell["seed"]))
        request_hash = _hash_json(request)
        request_path = requests_dir / f"{request['campaign_id']}.json"
        request_path.write_text(json.dumps(request, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if request_hash in completed_by_request:
            reused = deepcopy(completed_by_request[request_hash])
            reused["set_id"] = cell["set_id"]
            reused["reused_identical_request"] = True
            records.append(reused)
            continue
        try:
            report = run(request_path, repo=frequencia_repo,
                         expected_sha=EXPECTED_FREQUENCIA_SHA, output_root=output_dir / "runs",
                         timeout_seconds=timeout)
            row = _summarize(report, cell, request_hash)
        except Exception as exc:  # Retain every requested configuration in the campaign denominator.
            row = {"status": "FAILED", "set_id": cell["set_id"],
                   "configuration": {key: cell[key] for key in (
                       "tags", "gateways", "cadence_s", "schedule", "phase_window_s",
                       "sf", "payload_bytes", "seed", "distribution", "load_class", "epochs")},
                   "request_path": str(request_path), "request_sha256": request_hash,
                   "error": f"{type(exc).__name__}: {exc}"}
        completed_by_request[request_hash] = row
        records.append(row)
        results_path.write_text(json.dumps({"campaign_id": spec["campaign_id"],
            "updated_at": datetime.now(timezone.utc).isoformat(), "runs": records},
            indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    summary = {"campaign_id": spec["campaign_id"], "riose_base_sha": spec.get("riose_base_sha"),
               "frequencia_expected_sha": EXPECTED_FREQUENCIA_SHA,
               "base_request_sha256": _hash_json(base), "spec_sha256": _hash_json(spec),
               "requested_runs": len(records),
               "unique_requests": len(completed_by_request),
               "duplicate_requests_reused": sum(bool(row.get("reused_identical_request")) for row in records),
               "completed_runs": sum(row.get("status") == "SIMULATED" for row in records),
               "failed_runs": sum(row.get("status") == "FAILED" for row in records),
               "run_results_path": str(results_path), "runs": records}
    results_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False,
                                       allow_nan=False) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--base-request", type=Path, required=True)
    parser.add_argument("--frequencia-repo", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--set", dest="set_ids", action="append",
                        help="run only this run-set ID; repeat to select several")
    parser.add_argument("--limit", type=int, help="run only the first N expanded configurations")
    args = parser.parse_args()
    summary = execute(args.spec, args.base_request, args.frequencia_repo,
                      args.output_dir, args.timeout,
                      set_ids=set(args.set_ids) if args.set_ids else None, limit=args.limit)
    print(json.dumps({key: summary[key] for key in (
        "campaign_id", "requested_runs", "unique_requests", "completed_runs",
        "failed_runs", "duplicate_requests_reused", "run_results_path")}, indent=2))
    return 0 if summary["failed_runs"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
