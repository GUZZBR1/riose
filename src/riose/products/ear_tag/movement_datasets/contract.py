"""Small canonical interchange contract for labeled accelerometer samples."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
import json
import math
from typing import Any

from riose.evidence.bridge import EvidenceBridgeRecord, EvidenceClass, serialize_evidence_bridge


class SensorPosition(StrEnum):
    EAR = "EAR"
    HEAD = "HEAD"
    NECK = "NECK"
    COLLAR = "COLLAR"
    LEG = "LEG"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class AxisUnit(StrEnum):
    G = "g"
    MG = "mg"
    M_S2 = "m/s^2"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CanonicalSample:
    """One source observation with raw label/value and its conversion trail."""

    dataset_id: str
    dataset_doi: str
    source_url: str
    source_file: str
    source_file_sha256: str
    source_row: int
    animal_id: str
    source_segment_id: str
    session_id: str | None
    timestamp: str
    timestamp_timezone: str
    sensor_position: SensorPosition
    sample_rate_hz: float
    x: float
    y: float
    z: float
    axis_unit: AxisUnit
    original_label: str
    canonical_label: str
    mapping_version: str
    mapping_reason: str
    evidence: EvidenceBridgeRecord
    adapter_version: str

    def __post_init__(self) -> None:
        for name in ("dataset_id", "dataset_doi", "source_url", "source_file", "animal_id",
                     "source_segment_id",
                     "timestamp", "original_label", "mapping_version", "mapping_reason",
                     "adapter_version"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.session_id is not None and (type(self.session_id) is not str or not self.session_id.strip()):
            raise ValueError("session_id must be null or a non-empty string")
        if any(ord(char) < 32 or ord(char) == 127
               for char in self.animal_id + self.source_segment_id + self.original_label + self.timestamp):
            raise ValueError("animal_id, source_segment_id, original_label, and timestamp cannot contain control characters")
        if type(self.source_row) is not int or self.source_row < 2:
            raise ValueError("source_row must identify a data row (2 or greater)")
        if len(self.source_file_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in self.source_file_sha256):
            raise ValueError("source_file_sha256 must be a lowercase SHA-256 digest")
        if self.timestamp_timezone not in {"UTC", "OFFSET", "UNKNOWN"}:
            raise ValueError("timestamp_timezone must be UTC, OFFSET, or UNKNOWN")
        try:
            if "T" not in self.timestamp and " " not in self.timestamp:
                raise ValueError("time component is required")
            parsed_timestamp = datetime.fromisoformat(self.timestamp.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be an ISO-8601 timestamp") from exc
        actual_timezone = (
            "UNKNOWN" if parsed_timestamp.tzinfo is None else
            "UTC" if parsed_timestamp.utcoffset().total_seconds() == 0 else "OFFSET"
        )
        if self.timestamp_timezone != actual_timezone:
            raise ValueError("timestamp_timezone does not match the timestamp value")
        if type(self.sensor_position) is not SensorPosition or type(self.axis_unit) is not AxisUnit:
            raise ValueError("sensor position and axis unit must use their declared enums")
        if type(self.evidence) is not EvidenceBridgeRecord:
            raise ValueError("evidence must use the shared EvidenceBridgeRecord contract")
        if (isinstance(self.sample_rate_hz, bool) or not isinstance(self.sample_rate_hz, (int, float))
                or not math.isfinite(self.sample_rate_hz) or self.sample_rate_hz <= 0):
            raise ValueError("sample_rate_hz must be finite and positive")
        for name in ("x", "y", "z"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite numeric data")
        if self.canonical_label != "UNKNOWN":
            raise ValueError("no behavior mappings are asserted by this adapter")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["sensor_position"] = self.sensor_position.value
        result["axis_unit"] = self.axis_unit.value
        result["evidence"] = json.loads(serialize_evidence_bridge(self.evidence))
        result["evidence_status"] = self.evidence.evidence_class.value
        return result

    @property
    def evidence_status(self) -> EvidenceClass:
        return self.evidence.evidence_class

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
