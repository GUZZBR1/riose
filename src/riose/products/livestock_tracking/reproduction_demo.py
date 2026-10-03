"""Offline synthetic demonstration of event-aligned activity summaries."""

from datetime import datetime, timedelta, timezone

from .domain.contracts import EvidenceStatus
from .reproduction import (
    ActivityObservation,
    EventSource,
    ReproductiveEvent,
    ReproductiveEventType,
    summarize_event_activity,
    summary_json,
)


def main() -> None:
    event_at = datetime(2026, 1, 3, tzinfo=timezone.utc)
    observations = tuple(
        ActivityObservation(
            animal_id="synthetic-cow-01",
            observed_at=event_at - timedelta(hours=36 - 6 * index),
            activity=1.0 + 0.1 * (index % 2),
            sensor="synthetic-activity-series",
            sensor_position="UNSPECIFIED_SYNTHETIC",
            evidence_status=EvidenceStatus.SIMULATED,
            source_ref="fixture:issue-26-v1",
        )
        for index in range(8)
    )
    event = ReproductiveEvent(
        animal_id="synthetic-cow-01",
        event_type=ReproductiveEventType.ESTRUS,
        occurred_at=event_at,
        recorded_at=event_at + timedelta(minutes=10),
        source=EventSource.SIMULATED,
        source_ref="fixture:issue-26-v1",
        evidence_status=EvidenceStatus.SIMULATED,
    )
    print(summary_json(summarize_event_activity(event, observations)))


if __name__ == "__main__":
    main()
