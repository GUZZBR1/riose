"""Small deterministic software demonstration; all observations are synthetic."""

from __future__ import annotations

import json
from dataclasses import asdict

from riose.products.ear_tag.health_anomaly.analysis import (
    BehaviorObservation,
    analyze_behavior,
)
from riose.products.livestock_tracking.domain.contracts import EvidenceStatus


def synthetic_demo() -> dict[str, object]:
    observations = [
        BehaviorObservation(
            animal_id="synthetic-cow-01",
            timestamp_s=float(day),
            sensor_position="EAR",
            activity=20.0 + (day % 2) * 0.2,
            rumination_minutes=500.0 + (day % 2),
            locomotion_steps=100.0 + (day % 2),
            evidence_status=EvidenceStatus.SIMULATED,
        )
        for day in range(1, 8)
    ]
    observations.append(BehaviorObservation(
        animal_id="synthetic-cow-01",
        timestamp_s=8.0,
        sensor_position="EAR",
        activity=0.0,
        rumination_minutes=None,
        locomotion_steps=100.0,
        evidence_status=EvidenceStatus.SIMULATED,
    ))
    result = analyze_behavior(
        observations,
        animal_id="synthetic-cow-01",
        observed_at_s=8.0,
        sensor_position="EAR",
    )
    return {
        "disclaimer": "Synthetic software fixture only; not clinical validation.",
        "result": {
            **asdict(result),
            "state": result.state.value,
            "evidence_status": result.evidence_status.value,
            "input_evidence_statuses": [status.value for status in result.input_evidence_statuses],
        },
    }


if __name__ == "__main__":
    print(json.dumps(synthetic_demo(), indent=2, sort_keys=True))
