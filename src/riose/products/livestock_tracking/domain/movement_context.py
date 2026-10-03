"""Movement observations kept independent from RF and position contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from .contracts import EvidenceStatus, RFObservation


class MovementStatus(StrEnum):
    OBSERVED = "OBSERVED"
    LOW_QUALITY = "LOW_QUALITY"
    MISSING = "MISSING"
    STALE = "STALE"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class MovementObservation:
    """A movement-side sample; behavior labels are source claims, not truth."""

    timestamp_s: float
    tag_id: str
    activity_level: float | None
    behavior_state: str | None = None
    quality: float | None = None
    status: MovementStatus = MovementStatus.OBSERVED
    evidence_status: EvidenceStatus = EvidenceStatus.EXPERIMENTAL
    provenance: str = "unspecified"
    clock_id: str = "simulation"
    raw_imu_accel_norm_g: float | None = None

    def __post_init__(self) -> None:
        if not self.tag_id or not self.tag_id.strip():
            raise ValueError("tag_id must be a non-empty opaque identity")
        if (isinstance(self.timestamp_s, bool)
                or not isinstance(self.timestamp_s, (int, float))
                or not isfinite(self.timestamp_s)):
            raise ValueError("timestamp_s must be finite")
        if self.activity_level is not None and (
            not isfinite(self.activity_level) or self.activity_level < 0
        ):
            raise ValueError("activity_level must be finite and non-negative")
        if self.quality is not None and (
            not isfinite(self.quality) or not 0 <= self.quality <= 1
        ):
            raise ValueError("quality must be between 0 and 1")
        if self.raw_imu_accel_norm_g is not None and (
            not isfinite(self.raw_imu_accel_norm_g) or self.raw_imu_accel_norm_g < 0
        ):
            raise ValueError("raw_imu_accel_norm_g must be finite and non-negative")
        if not isinstance(self.status, MovementStatus):
            raise ValueError("status must be a MovementStatus")
        if not isinstance(self.evidence_status, EvidenceStatus):
            raise ValueError("evidence_status must be an EvidenceStatus")
        if not self.clock_id.strip():
            raise ValueError("clock_id must be non-empty")

    @classmethod
    def from_rf_hooks(cls, observation: RFObservation, *,
                      clock_id: str = "simulation") -> MovementObservation:
        """Preserve existing movement hooks without deriving activity or packet health."""
        has_hook = observation.imu_accel_norm_g is not None or observation.behavior_state is not None
        return cls(
            timestamp_s=observation.timestamp_s,
            tag_id=observation.tag_id,
            activity_level=None,
            behavior_state=observation.behavior_state,
            status=MovementStatus.OBSERVED if has_hook else MovementStatus.MISSING,
            evidence_status=observation.status,
            provenance="RFObservation.imu_accel_norm_g/behavior_state",
            clock_id=clock_id,
            raw_imu_accel_norm_g=observation.imu_accel_norm_g,
        )
