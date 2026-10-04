"""Run FREQUENCIA's existing network, detector, clock and TDoA modules.

This module is invoked with the FREQUENCIA interpreter and repository on the
path. It adapts Sionna records; it does not implement RF, ns-3 or localization
algorithms in RIOSE.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


def run_pipeline(payload: dict[str, Any], engine_root: str | Path) -> dict[str, Any]:
    """Use the pinned upstream network/temporal/localization APIs on RF links."""
    engine = Path(engine_root).resolve()
    sys.path.insert(0, str(engine))
    from network.adapter import run as run_ns3
    from localization.baseline import Gateway
    from localization.network_pipeline import evaluate_network_localization
    from temporal.clock import ClockModel, ClockNetwork
    from temporal.detectors import detect
    from temporal.phy import DetectionSweep, LoRaPhyConfig, evaluate_detection

    request = payload["request"]
    records = payload["records"]
    network_config = request["solver"]["parameters"]["network"]
    temporal = request["solver"]["parameters"]["temporal"]
    radio = request["radio"]
    gateways = request["receivers"]
    network_result = run_ns3(
        {"backend": "sionna-rt", "classification": "SIMULATED_CHANNEL_OBSERVATIONS",
         "seed": request["seed"], "frequency_hz": radio["frequency_hz"],
         "tx_power_dbm": radio["tx_power_dbm"], "records": records},
        ns3=Path(payload["ns3_root"]),
        sf=int(network_config["spreading_factor"]),
        payload_bytes=int(network_config["payload_bytes"]),
        traffic_interval_s=float(network_config["traffic_interval_s"]),
    )
    channels = {(str(row["animal_id"]), float(row["timestamp_s"]), str(row["gateway_id"])): row
                for row in records}
    packets = {str(row["event_index"]): row for row in network_result["packets"]}
    tag_by_animal = {tag["animal_ref"]: tag for tag in request["tags"]}
    device_by_animal = {tag["animal_ref"]: tag["device_ref"] for tag in request["tags"]}
    clock_models = tuple(ClockModel(
        gateway_id=str(gateway_id), offset_s=float(values["offset_s"]),
        drift_ppm=float(values["drift_ppm"]), jitter_std_s=float(values["jitter_std_s"]),
        quantization_s=(None if values["quantization_s"] is None else float(values["quantization_s"])),
    ) for gateway_id, values in temporal["clocks"].items())
    clock_network = ClockNetwork(
        clock_models, seed=int(request["seed"]),
        correlated_jitter_std_s=float(temporal["correlated_jitter_std_s"]),
        timestamp_error_std_s=float(temporal["timestamp_error_std_s"]),
    )
    detector = temporal["detector"]
    phy = LoRaPhyConfig(
        frequency_hz=float(radio["frequency_hz"]), bandwidth_hz=float(radio["bandwidth_hz"]),
        spreading_factor=int(network_config["spreading_factor"]),
        tx_power_dbm=float(radio["tx_power_dbm"]),
    )
    sweep = DetectionSweep(
        noise_figure_db=float(temporal["noise_figure_db"]),
        snr_threshold_db=float(temporal["snr_threshold_db"]),
        detection_margin_db=float(temporal["detection_margin_db"]),
    )
    transmissions = []
    for packet in network_result["packets"]:
        if packet.get("tx_start_s") is None:
            continue
        animal_id = str(packet["animal_id"])
        tag = tag_by_animal[animal_id]
        transmissions.append({"packet_id": str(packet["event_index"]),
                              "device_id": str(tag["device_ref"]),
                              "send_time_s": float(packet["tx_start_s"])})
    receptions = []
    timestamp_rows = []
    for event in network_result["gateway_events"]:
        if event.get("outcome") != "RX":
            continue
        packet_id = str(event["event_index"])
        packet = packets[packet_id]
        animal_id = str(packet["animal_id"])
        gateway_id = str(event["gateway_id"])
        channel = channels[(animal_id, float(packet["timestamp_s"]), gateway_id)]
        paths = [{"path_index": index, **path} for index, path in enumerate(channel.get("paths", []))]
        detection = detect({"paths": paths}, str(detector["mode"]),
                           threshold_dbm=detector["threshold_dbm"],
                           relative_threshold_db=float(detector["relative_threshold_db"]))
        snr = evaluate_detection(phy, float(channel["received_power_dbm"]), sweep)
        physical = event.get("tdoa_physical_timestamp_s")
        timestamp_observation = None
        detector_error_s = None
        tdoa_timestamp_s = None
        if physical is not None and detection.delay_s is not None and snr.detected:
            first_path_s = min(float(path["delay_s"]) for path in channel["paths"])
            detector_error_s = detection.delay_s - first_path_s
            timestamp_observation = clock_network.observe(
                gateway_id, float(physical) - float(packet["tx_start_s"]),
                sample_id=packet_id, epoch_s=float(packet["tx_start_s"]),
                detector_error_s=detector_error_s,
            )
            tdoa_timestamp_s = timestamp_observation.timestamp_s
        reception = {"packet_id": packet_id, "device_id": str(device_by_animal[animal_id]),
                     "gateway_id": gateway_id, "send_time_s": float(packet["tx_start_s"]),
                     "rx_time_s": float(event["rx_begin_s"]), "delivered": True,
                     "tdoa_timestamp_s": tdoa_timestamp_s,
                     "sionna_status": channel["los_nlos"],
                     "sionna_delay_s": min(float(path["delay_s"]) for path in channel["paths"])}
        receptions.append(reception)
        timestamp_rows.append({"packet_id": packet_id, "animal_id": animal_id,
            "device_id": device_by_animal[animal_id], "timestamp_s": float(packet["timestamp_s"]),
            "gateway_id": gateway_id, "classification": "SIMULATED",
            "channel_backend": "sionna-rt", "network_backend": network_result["network_backend"],
            "channel_status": channel["los_nlos"], "network_outcome": event["outcome"],
            "rx_begin_s": event["rx_begin_s"], "rx_end_s": event["rx_end_s"],
            "latency_s": event["latency_s"], "physical_first_arrival_s": physical,
            "detector_status": detection.status, "detector_path_index": detection.path_index,
            "detector_delay_s": detection.delay_s, "detector_error_s": detector_error_s,
            "snr_db": snr.snr_db, "required_snr_db": snr.required_snr_db,
            "snr_detected": snr.detected,
            "clock_timestamp_s": timestamp_observation.timestamp_s if timestamp_observation else None,
            "clock_components": timestamp_observation.to_dict() if timestamp_observation else None,
            "tdoa_timestamp_s": tdoa_timestamp_s})

    # This estimation call receives only transmitted packet metadata and PHY
    # receptions. Ground truth is deliberately omitted and scored afterwards.
    localization = evaluate_network_localization(
        transmissions=transmissions, receptions=receptions,
        gateways=[Gateway(str(row["gateway_ref"]), tuple(float(x) for x in row["position_m"][:2]))
                  for row in gateways], seed=int(request["seed"]),
        max_iterations=int(temporal["max_iterations"]),
    )
    localization["network_backend"] = network_result["network_backend"]
    localization["ground_truth_boundary"] = "not supplied to estimator; score in RIOSE after estimation"
    return {"network": network_result, "timestamps": timestamp_rows,
            "localization": localization}


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: frequencia_network.py INPUT.json OUTPUT.json ENGINE_ROOT")
    input_path, output_path, engine_root = map(Path, sys.argv[1:])
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    result = run_pipeline(payload, engine_root)
    output_path.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
