"""Behavior observations with explicit origin and evidence provenance."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

from .contracts import EvidenceStatus


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)
_SOURCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+/-]{0,127}\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class BehaviorObservation:
    """One classified or annotated behavior observation; timestamps are Unix seconds."""

    animal_id: str
    timestamp_s: float
    behavior: str
    source: str
    evidence_status: EvidenceStatus
    observation_kind: str
    idempotency_key: str
    end_timestamp_s: float | None = None
    confidence: float | None = None
    model_version: str | None = None
    sensor_position: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.animal_id, str) or not _IDENTIFIER.fullmatch(self.animal_id):
            raise ValueError("animal_id must be a non-empty identifier")
        if not _finite(self.timestamp_s) or self.timestamp_s < 0:
            raise ValueError("timestamp_s must be a finite Unix timestamp >= 0")
        if self.end_timestamp_s is not None and (
            not _finite(self.end_timestamp_s) or self.end_timestamp_s < self.timestamp_s
        ):
            raise ValueError("end_timestamp_s must be finite and >= timestamp_s")
        if not isinstance(self.behavior, str) or not _IDENTIFIER.fullmatch(self.behavior):
            raise ValueError("behavior must be a non-empty identifier")
        if not isinstance(self.source, str) or not _SOURCE.fullmatch(self.source):
            raise ValueError("source must be a non-empty bounded identifier")
        if self.observation_kind not in {"PREDICTION", "GROUND_TRUTH", "MANUAL_ANNOTATION"}:
            raise ValueError("unsupported observation_kind")
        if not isinstance(self.evidence_status, EvidenceStatus):
            raise ValueError("evidence_status must be an EvidenceStatus")
        if not isinstance(self.idempotency_key, str) or not _IDENTIFIER.fullmatch(self.idempotency_key):
            raise ValueError("idempotency_key must be a non-empty identifier")
        if self.confidence is not None and (
            not _finite(self.confidence) or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidence must be a finite value in [0, 1]")
        if self.model_version is not None and (
            not isinstance(self.model_version, str) or not _SOURCE.fullmatch(self.model_version)
        ):
            raise ValueError("model_version must be a non-empty bounded identifier")
        if self.sensor_position is not None and (
            not isinstance(self.sensor_position, str) or not _IDENTIFIER.fullmatch(self.sensor_position)
        ):
            raise ValueError("sensor_position must be a non-empty identifier")
        if self.observation_kind == "PREDICTION" and not self.model_version:
            raise ValueError("prediction requires model_version")


def _finite(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False
