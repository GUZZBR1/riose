"""Shared, inference-safe data contracts for simulation and localization.

Ground truth intentionally lives in a separate type and is never accepted by
the localization API. Keep these contracts dependency-light so firmware,
simulation, backend, and UI work can proceed independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EvidenceStatus(StrEnum):
    VALIDATED = "VALIDATED"
    SIMULATED = "SIMULATED"
    ASSUMED = "ASSUMED"
    EXPERIMENTAL = "EXPERIMENTAL"
    FUTURE = "FUTURE"


@dataclass(frozen=True, slots=True)
class Anchor:
    anchor_id: str
    x: float
    y: float
    height_m: float = 3.0
    kind: str = "esp32-c6-subghz"
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class RFObservation:
    """Fields observable at an anchor; deliberately excludes coordinates."""

    timestamp_s: float
    tag_id: str
    anchor_id: str
    rssi_dbm: float | None
    snr_db: float | None
    packet_received: bool
    imu_accel_norm_g: float | None = None
    behavior_state: str | None = None
    tof_ns: float | None = None
    phase_rad: float | None = None
    status: EvidenceStatus = EvidenceStatus.SIMULATED


@dataclass(frozen=True, slots=True)
class GroundTruth:
    timestamp_s: float
    tag_id: str
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class Estimate:
    timestamp_s: float
    tag_id: str
    x: float | None
    y: float | None
    method: str
    quality: float | None = None
    status: EvidenceStatus = EvidenceStatus.SIMULATED


@dataclass(frozen=True, slots=True)
class FarmConfig:
    width_m: float = 1000.0
    height_m: float = 1000.0
    animal_count: int = 100
    anchor_count: int = 8
    duration_s: float = 3600.0
    sample_period_s: float = 60.0
    seed: int = 7
    packet_loss_probability: float = 0.05
    tx_power_dbm: float = 14.0
    path_loss_exponent: float = 2.7


@dataclass(frozen=True, slots=True)
class SimulationEpisode:
    observations: tuple[RFObservation, ...]
    ground_truth: tuple[GroundTruth, ...]
    anchors: tuple[Anchor, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
