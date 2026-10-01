"""Simulation-only virtual fencing cues; no electrical stimulus exists."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

from .contracts import EvidenceStatus, GroundTruth


class FenceState(StrEnum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    SIMULATED_AUDIO_CUE = "simulated_audio_cue"
    SIMULATED_VIBRATION_CUE = "simulated_vibration_cue"


@dataclass(frozen=True, slots=True)
class FenceZone:
    zone_id: str
    kind: str
    polygon: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if self.kind not in {"ALLOWED_ZONE", "WARNING_ZONE", "FORBIDDEN_ZONE"}:
            raise ValueError("zone kind must be ALLOWED_ZONE, WARNING_ZONE, or FORBIDDEN_ZONE")
        if len(self.polygon) < 3:
            raise ValueError("zone polygon needs at least three points")


@dataclass(frozen=True, slots=True)
class FenceEvent:
    timestamp_s: float
    tag_id: str
    zone_id: str
    state: FenceState
    simulated_response: str
    status: EvidenceStatus = EvidenceStatus.SIMULATED


def contains(zone: FenceZone, point: tuple[float, float]) -> bool:
    x, y = point
    inside = False
    pts = zone.polygon
    j = len(pts) - 1
    for i, (xi, yi) in enumerate(pts):
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-30) + xi:
            inside = not inside
        j = i
    return inside


def boundary_distance(zone: FenceZone, point: tuple[float, float]) -> float:
    px, py = point
    distance = float("inf")
    pts = zone.polygon
    for i, (ax, ay) in enumerate(pts):
        bx, by = pts[(i + 1) % len(pts)]
        dx, dy = bx - ax, by - ay
        scale = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy + 1e-30)))
        distance = min(distance, ((px - ax - scale * dx) ** 2 + (py - ay - scale * dy) ** 2) ** 0.5)
    return distance


def simulate_fence(truth: Sequence[GroundTruth], zones: Sequence[FenceZone],
                   warning_distance_m: float = 20.0) -> list[FenceEvent]:
    """Emit progressively stronger audio/vibration cues in a toy response model."""
    events: list[FenceEvent] = []
    previous: dict[str, FenceState] = {}
    for point in truth:
        position = (point.x, point.y)
        for zone in zones:
            inside = contains(zone, position)
            state = FenceState.NORMAL
            response = "none"
            if zone.kind == "FORBIDDEN_ZONE" and inside:
                state, response = FenceState.SIMULATED_AUDIO_CUE, "animal_simulated_turn"
            elif zone.kind == "FORBIDDEN_ZONE" and boundary_distance(zone, position) <= warning_distance_m:
                state, response = FenceState.WARNING, "warning_only"
            elif zone.kind == "WARNING_ZONE" and inside:
                state, response = FenceState.SIMULATED_VIBRATION_CUE, "animal_simulated_slowdown"
            elif zone.kind == "ALLOWED_ZONE" and not inside:
                state, response = FenceState.SIMULATED_AUDIO_CUE, "animal_simulated_return"
            key = f"{point.tag_id}:{zone.zone_id}"
            if state != previous.get(key, FenceState.NORMAL):
                events.append(FenceEvent(point.timestamp_s, point.tag_id, zone.zone_id, state, response))
                previous[key] = state
    return events

