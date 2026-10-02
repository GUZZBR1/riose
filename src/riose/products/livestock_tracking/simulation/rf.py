"""CPU-friendly sub-GHz RF link model. All generated measurements are SIMULATED."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Mapping, Sequence

from ..domain.contracts import Anchor, FarmConfig, GroundTruth, RFObservation
from .farm import MotionFeatures, Obstacle, segment_crosses_obstacle


@dataclass(frozen=True, slots=True)
class RFConfig:
    frequency_mhz: float = 915.0
    reference_distance_m: float = 1.0
    shadow_sigma_db: float = 4.0
    measurement_sigma_db: float = 2.0
    interference_probability: float = 0.015
    receiver_sensitivity_dbm: float = -137.0
    noise_floor_dbm: float = -120.0
    snr_threshold_db: float = -7.0
    nlos_probability: float = 0.0
    default_obstacle_attenuation_db: float = 6.0
    obstacle_attenuation_db: Mapping[str, float] | None = None
    weather_loss_db: float = 0.0
    orientation_sigma_db: float = 1.5

    def attenuation(self, obstacle: Obstacle) -> float:
        if obstacle.attenuation_db is not None:
            return obstacle.attenuation_db
        values = self.obstacle_attenuation_db or {
            "barn": 20.0, "trees": 8.0, "vegetation": 5.0,
            "reservoir": 12.0, "terrain": 10.0,
        }
        return float(values.get(obstacle.kind, self.default_obstacle_attenuation_db))


def free_space_path_loss_db(distance_m: float, frequency_mhz: float = 915.0) -> float:
    """Free-space path loss for distance in meters and frequency in MHz."""
    d = max(float(distance_m), 1.0)
    if frequency_mhz <= 0:
        raise ValueError("frequency_mhz must be positive")
    return 32.44 + 20.0 * math.log10(frequency_mhz) + 20.0 * math.log10(d / 1000.0)


def log_distance_path_loss_db(distance_m: float, frequency_mhz: float = 915.0,
                              exponent: float = 2.7, reference_distance_m: float = 1.0) -> float:
    if exponent <= 0 or reference_distance_m <= 0:
        raise ValueError("path-loss exponent and reference distance must be positive")
    d0 = reference_distance_m
    pl0 = free_space_path_loss_db(d0, frequency_mhz)
    return pl0 + 10.0 * exponent * math.log10(max(distance_m, d0) / d0)


def _line_attenuation(tx_x: float, tx_y: float, rx_x: float, rx_y: float,
                      obstacles: Sequence[Obstacle], rf: RFConfig) -> tuple[float, bool]:
    crossed = [o for o in obstacles if segment_crosses_obstacle(tx_x, tx_y, rx_x, rx_y, o)]
    return sum(rf.attenuation(o) for o in crossed), bool(crossed)


def simulate_observations(
    config: FarmConfig,
    anchors: Sequence[Anchor],
    truth: Sequence[GroundTruth],
    motion_by_key: Sequence[MotionFeatures | Mapping[str, float | str]] | Mapping[
        tuple[float, str], Mapping[str, float | str]
    ],
    obstacles: Sequence[Obstacle],
    rf: RFConfig | None = None,
) -> tuple[RFObservation, ...]:
    """Convert private truth samples into anchor-side measurements only."""
    rf = rf or RFConfig()
    rng = random.Random(config.seed + 2309)
    # Slow shadow fading is correlated per tag-anchor pair; measurement noise remains fast.
    shadow: dict[tuple[str, str], float] = {}
    records: list[RFObservation] = []
    if isinstance(motion_by_key, Mapping):
        samples = ((point, motion_by_key[(point.timestamp_s, point.tag_id)])
                   for point in truth)
    else:
        samples = ((point, motion) for point, motion in zip(truth, motion_by_key, strict=True))
    for point, motion in samples:
        for anchor in anchors:
            if not anchor.enabled:
                continue
            key = (point.tag_id, anchor.anchor_id)
            old_shadow = shadow.get(key, rng.gauss(0.0, rf.shadow_sigma_db))
            shadow[key] = 0.85 * old_shadow + rng.gauss(0.0, rf.shadow_sigma_db * math.sqrt(1 - 0.85**2))
            dx, dy = point.x - anchor.x, point.y - anchor.y
            distance_3d = math.sqrt(dx * dx + dy * dy + anchor.height_m * anchor.height_m)
            attenuation, blocked = _line_attenuation(point.x, point.y, anchor.x, anchor.y, obstacles, rf)
            nlos_draw = rng.random()
            nlos_severity_db = rng.uniform(8.0, 28.0)
            forced_nlos = nlos_draw < rf.nlos_probability
            nlos_extra_db = nlos_severity_db if forced_nlos else 0.0
            tx_power = config.tx_power_dbm + rng.gauss(0, 0.5)  # modest production tolerance
            rssi = (tx_power - log_distance_path_loss_db(distance_3d, rf.frequency_mhz,
                    config.path_loss_exponent, rf.reference_distance_m) - attenuation
                    - nlos_extra_db - max(0.0, rf.weather_loss_db)
                    - abs(rng.gauss(0, rf.orientation_sigma_db))
                    + old_shadow + rng.gauss(0, rf.measurement_sigma_db))
            snr = rssi - rf.noise_floor_dbm
            lost = rng.random() < config.packet_loss_probability
            collision = rng.random() < rf.interference_probability
            below_sensitivity = rssi < rf.receiver_sensitivity_dbm or snr < rf.snr_threshold_db
            received = not (lost or collision or below_sensitivity)
            # No propagation geometry or ground truth coordinates are included in this record.
            records.append(RFObservation(
                timestamp_s=point.timestamp_s,
                tag_id=point.tag_id,
                anchor_id=anchor.anchor_id,
                rssi_dbm=round(rssi, 2) if received else None,
                snr_db=round(snr, 2) if received else None,
                packet_received=received,
                imu_accel_norm_g=float(motion["imu_accel_norm_g"]),
                behavior_state=str(motion["behavior_state"]),
            ))
    return tuple(records)
