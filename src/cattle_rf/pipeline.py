"""Composition root joining the isolated simulator and estimator contracts."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .contracts import FarmConfig
from .localization import METHODS, estimate, evaluate, train_fingerprint_model
from .sim import simulate_episode


def run_episode(config: FarmConfig, method: str = "weighted_centroid"):
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; valid methods: {', '.join(METHODS)}")
    episode = simulate_episode(config)
    models = None
    if method in {"extra_trees", "gradient_boosting"}:
        # Supervision comes from distinct deterministic seeds; inference receives
        # only the holdout episode's RFObservation records.
        training_config = FarmConfig(
            width_m=config.width_m, height_m=config.height_m,
            animal_count=max(3, min(config.animal_count, 30)),
            anchor_count=config.anchor_count, duration_s=config.duration_s,
            sample_period_s=config.sample_period_s, seed=config.seed + 100_003,
            packet_loss_probability=config.packet_loss_probability,
            tx_power_dbm=config.tx_power_dbm, path_loss_exponent=config.path_loss_exponent,
        )
        training = simulate_episode(training_config, anchors=episode.anchors)
        model = train_fingerprint_model(training.observations, training.ground_truth,
                                        training.anchors, algorithm=method,
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


def energy_metrics(episode, config: FarmConfig) -> dict[str, Any]:
    """Run the virtual tag policy over simulated behavior and report profile-derived energy."""
    from .firmware.energy import EnergyProfile
    from .firmware.tag import Activity, MemoryHAL, TagConfig, TagController

    profile = EnergyProfile.reference_stm32wle5()
    states: dict[str, dict[float, str]] = {}
    for obs in episode.observations:
        states.setdefault(obs.tag_id, {})[obs.timestamp_s] = obs.behavior_state or "GRAZING"
    daily: list[float] = []
    messages_daily: list[float] = []
    for tag_id, timeline in states.items():
        hal = MemoryHAL()
        controller = TagController(TagConfig(tag_id=tag_id), hal, profile)
        controller.boot()
        times = sorted(timeline)
        for timestamp in times:
            behavior = timeline[timestamp]
            activity = Activity.RUNNING if behavior == "RUNNING" else Activity.NORMAL
            controller.step(config.sample_period_s, activity)
        report = controller.ledger.report()
        daily.append(report.energy_per_day_mah)
        messages_daily.append(len(hal.transmissions) * 86400.0 / max(config.duration_s, 1e-9))
    return {
        "energy_per_tag_day_mah": sum(daily) / len(daily) if daily else 0.0,
        "estimated_battery_life_days": None,
        "energy_profile": profile.profile_id,
        "energy_status": profile.status.value,
        "energy_source": profile.source,
        "messages_per_tag_day": sum(messages_daily) / len(messages_daily) if messages_daily else 0.0,
    }

