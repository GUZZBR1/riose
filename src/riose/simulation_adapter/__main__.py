"""Run the compact adapter demonstration using the committed V1 result fixture."""

import json
from pathlib import Path

from riose.simulation_adapter import convert_result


def main() -> int:
    fixture = Path(__file__).parents[1] / "simulation_contract" / "fixtures" / "result-v1.json"
    batch = convert_result(json.loads(fixture.read_text(encoding="utf-8")))
    print(json.dumps({
        "observations": [
            {"tag_id": o.tag_id, "anchor_id": o.anchor_id, "timestamp_s": o.timestamp_s,
             "rssi_dbm": o.rssi_dbm, "snr_db": o.snr_db, "packet_received": o.packet_received,
             "tof_ns": o.tof_ns, "status": o.status.value, "provenance": dict(p)}
            for o, p in zip(batch.observations, batch.observation_provenance, strict=True)
        ],
        "estimates": [
            {"tag_id": e.tag_id, "timestamp_s": e.timestamp_s, "x": e.x, "y": e.y,
             "method": e.method, "quality": e.quality, "status": e.status.value, "provenance": dict(p)}
            for e, p in zip(batch.estimates, batch.estimate_provenance, strict=True)
        ],
        "report": {field: getattr(batch.report, field) for field in batch.report.__dataclass_fields__},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
