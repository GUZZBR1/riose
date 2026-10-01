"""Composition root joining the isolated simulator and estimator contracts."""

from __future__ import annotations

from dataclasses import asdict
import random
from typing import Any

from .contracts import Anchor, FarmConfig
from .localization import METHODS, estimate, evaluate, train_fingerprint_model
from .sim import simulate_episode
from .sim.rf import RFConfig


def run_episode(config: FarmConfig, method: str = "weighted_centroid",
                anchors: tuple[Anchor, ...] | None = None):
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; valid methods: {', '.join(METHODS)}")
    episode = simulate_episode(config, anchors=anchors)
    models = None
    if method in {"extra_trees", "gradient_boosting"}:
        # Supervision comes from distinct, domain-randomized seeds; inference
        # receives only the holdout episode's RFObservation records.
        training_observations, training_truth = domain_randomized_training_data(
            config, episode.anchors)
        model = train_fingerprint_model(training_observations, training_truth,
                                        episode.anchors, algorithm=method,
                                        random_state=config.seed)
        models = {method: model}
    estimates = estimate(episode.observations, episode.anchors, method,
                         fingerprint_models=models)
    metrics = compute_metrics(episode, estimates, config)
    return episode, estimates, metrics


def compute_metrics(episode, estimates, config: FarmConfig) -> dict[str, Any]:
    metrics: dict[str, Any] = evaluate(estimates, episode.ground_truth)
    total_packets = len(episode.observations)
    received = sum(o.packet_received for o in episode.observations)
    metrics.update({
        "packet_delivery_ratio": received / total_packets if total_packets else 0.0,
        "anchor_observations_per_animal_per_day": (total_packets / max(config.animal_count, 1)
                                                    * 86400.0 / max(config.duration_s, 1e-9)),
        "anchor_count": len(episode.anchors),
        "animal_count": config.animal_count,
        "method": estimates[0].method if estimates else "unavailable",
        "evidence": "SIMULATED",
        "farm": {"width_m": config.width_m, "height_m": config.height_m},
        "duration_s": config.duration_s,
    })
    metrics.update(energy_metrics(episode, config))
    metrics["messages_per_animal_per_day"] = metrics["messages_per_tag_day"]
    return metrics


def domain_randomized_training_data(config: FarmConfig, anchors,
                                    episodes: int = 3):
    """Build farm-specific training samples across configured RF nuisance ranges."""
    rng = random.Random(config.seed + 902_103)
    observations, truth = [], []
    for index in range(episodes):
        training_config = FarmConfig(
            width_m=config.width_m, height_m=config.height_m,
            # Broad spatial coverage matters more than matching herd size for
            # supervised farm fingerprints. This stays local and bounded.
            animal_count=max(300, min(config.animal_count, 1000)),
            anchor_count=len(anchors), duration_s=max(600.0, config.duration_s),
            sample_period_s=min(30.0, config.sample_period_s),
            seed=config.seed + 100_003 + index * 7_919,
            packet_loss_probability=rng.uniform(0.02, 0.20),
            tx_power_dbm=rng.uniform(10.0, 18.0),
            path_loss_exponent=rng.uniform(2.2, 3.4),
        )
        rf = RFConfig(
            shadow_sigma_db=rng.uniform(2.0, 8.0),
            measurement_sigma_db=rng.uniform(1.0, 4.0),
            interference_probability=rng.uniform(0.005, 0.04),
            nlos_probability=rng.uniform(0.0, 0.25),
            weather_loss_db=rng.uniform(0.0, 6.0),
            orientation_sigma_db=rng.uniform(0.5, 5.0),
        )
        episode = simulate_episode(training_config, anchors=anchors, rf_config=rf)
        observations.extend(episode.observations)
        truth.extend(episode.ground_truth)
    return tuple(observations), tuple(truth)


def energy_metrics(episode, config: FarmConfig) -> dict[str, Any]:
    """Run the virtual tag policy over simulated behavior and report profile-derived energy."""
    from .firmware.energy import EnergyLedger, EnergyProfile

    profile = EnergyProfile.reference_stm32wle5()
    states: dict[str, dict[float, str]] = {}
    for obs in episode.observations:
        states.setdefault(obs.tag_id, {})[obs.timestamp_s] = obs.behavior_state or "GRAZING"
    daily: list[float] = []
    messages_daily: list[float] = []
    for tag_id, timeline in states.items():
        # Extrapolate from observed behavior fractions over a full day and the
        # configured cadence. Simulating only a short test window and dividing
        # by its length would over-weight the one immediate boot beacon.
        active_fraction = sum(state in {"RUNNING", "GROUP_MOVEMENT"}
                              for state in timeline.values()) / max(1, len(timeline))
        active_fraction = min(1.0, max(0.0, active_fraction))
        day_s = 86400.0
        active_s = day_s * active_fraction
        normal_s = day_s - active_s
        normal_beacons = normal_s / 900.0
        active_beacons = active_s / 60.0
        tx_duration_s, rx_duration_s = 0.1, 0.2
        base_sleep_s = max(0.0, normal_s - normal_beacons * (tx_duration_s + rx_duration_s))
        base_imu_s = max(0.0, active_s - active_beacons * (tx_duration_s + rx_duration_s))
        ledger = EnergyLedger(profile)
        ledger.record(profile.sleep_ma, base_sleep_s)
        ledger.record(profile.imu_monitoring_ma, base_imu_s)
        ledger.record(profile.rf_tx_ma, (normal_beacons + active_beacons) * tx_duration_s)
        ledger.record(profile.rf_rx_ma, (normal_beacons + active_beacons) * rx_duration_s)
        report = ledger.report()
        daily.append(report.energy_per_day_mah)
        messages_daily.append(normal_beacons + active_beacons)
    return {
        "energy_per_tag_day_mah": sum(daily) / len(daily) if daily else 0.0,
        "estimated_battery_life_days": None,
        "energy_profile": profile.profile_id,
        "energy_status": profile.status.value,
        "energy_source": profile.source,
        "messages_per_tag_day": sum(messages_daily) / len(messages_daily) if messages_daily else 0.0,
    }

