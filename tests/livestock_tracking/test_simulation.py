from dataclasses import fields
import math

from cattle_rf.contracts import FarmConfig, RFObservation
from cattle_rf.sim.episode import generate_anchors, simulate_episode
from cattle_rf.sim.farm import (Behavior, COLLISION_RADIUS_M, FarmSimulator,
                                MotionFeatures, Obstacle, segment_crosses_obstacle)
from cattle_rf.sim.rf import RFConfig, free_space_path_loss_db, log_distance_path_loss_db, simulate_observations


def test_legacy_package_modules_are_canonical_forwarders():
    import cattle_rf.contracts as legacy_contracts
    import cattle_rf.sim.episode as legacy_episode
    import riose.products.livestock_tracking.domain.contracts as canonical_contracts
    import riose.products.livestock_tracking.simulation.episode as canonical_episode

    assert legacy_contracts is canonical_contracts
    assert legacy_episode is canonical_episode


def test_radio_path_loss_formulas_and_invalid_inputs():
    assert round(free_space_path_loss_db(1000, 915), 1) == 91.7
    assert log_distance_path_loss_db(10, exponent=2.0) > log_distance_path_loss_db(1, exponent=2.0)


def test_obstacle_segment_intersection():
    obstacle = Obstacle(4, 4, 6, 6)
    assert segment_crosses_obstacle(0, 5, 10, 5, obstacle)
    assert not segment_crosses_obstacle(0, 0, 3, 3, obstacle)


def test_episode_is_reproducible_and_truth_is_separate():
    cfg = FarmConfig(width_m=100, height_m=100, animal_count=3, anchor_count=4,
                     duration_s=120, sample_period_s=60, seed=21, packet_loss_probability=0)
    a = simulate_episode(cfg)
    b = simulate_episode(cfg)
    assert a == b
    assert len(a.anchors) == 4
    assert len(a.ground_truth) == 3 * 2
    assert a.observations
    obs_fields = {f.name for f in fields(RFObservation)}
    assert not ({"x", "y", "ground_truth_x", "ground_truth_y"} & obs_fields)
    assert all(o.packet_received for o in a.observations)


def test_anchor_positions_can_be_overridden_and_disabled_anchors_not_observed():
    cfg = FarmConfig(width_m=100, height_m=100, animal_count=1, anchor_count=8,
                     duration_s=0, sample_period_s=60, packet_loss_probability=0)
    anchors = (generate_anchors(cfg)[0],)
    ep = simulate_episode(cfg, anchors=anchors)
    assert ep.anchors == anchors
    assert {o.anchor_id for o in ep.observations} == {anchors[0].anchor_id}


def test_motion_stays_in_bounds_and_avoids_rectangular_obstacles():
    obstacle = Obstacle(40, 40, 60, 60, "barn")
    cfg = FarmConfig(width_m=100, height_m=100, animal_count=8, anchor_count=4,
                     duration_s=1200, sample_period_s=30, seed=3)
    truth, motion = FarmSimulator(cfg, [obstacle]).generate()
    assert len(truth) == len(motion)
    assert all(0 <= p.x <= 100 and 0 <= p.y <= 100 for p in truth)
    assert all(not obstacle.contains(p.x, p.y) for p in truth)
    assert {m["behavior_state"] for m in motion} <= {b.value for b in Behavior}


def test_motion_features_are_compact_and_preserve_legacy_lookup_and_rf_output():
    cfg = FarmConfig(width_m=100, height_m=100, animal_count=2, anchor_count=4,
                     duration_s=60, sample_period_s=30, seed=101, packet_loss_probability=0)
    farm = FarmSimulator(cfg)
    truth, motion = farm.generate()
    assert isinstance(motion[0], MotionFeatures)
    assert not hasattr(motion[0], "__dict__")
    assert motion[0]["tag_id"] == truth[0].tag_id
    assert motion[0]["timestamp_s"] == truth[0].timestamp_s
    assert motion[0]["behavior_state"] in {behavior.value for behavior in Behavior}
    assert motion[0].get("tag_id") == truth[0].tag_id
    assert dict(motion[0])["imu_accel_norm_g"] == motion[0]["imu_accel_norm_g"]

    anchors = generate_anchors(cfg)
    compact_result = simulate_observations(cfg, anchors, truth, motion, (), RFConfig())
    legacy_map = {(sample.timestamp_s, sample.tag_id): {
        "timestamp_s": sample.timestamp_s,
        "tag_id": sample.tag_id,
        "imu_accel_norm_g": sample.imu_accel_norm_g,
        "behavior_state": sample.behavior_state,
    } for sample in motion}
    legacy_result = simulate_observations(cfg, anchors, truth, legacy_map, (), RFConfig())
    assert compact_result == legacy_result


def test_rf_packet_loss_and_nlos_are_configurable():
    cfg = FarmConfig(width_m=100, height_m=100, animal_count=1, anchor_count=4,
                     duration_s=0, sample_period_s=60, packet_loss_probability=1)
    ep = simulate_episode(cfg, rf_config=RFConfig(nlos_probability=1))
    assert ep.observations
    assert all(not o.packet_received and o.rssi_dbm is None for o in ep.observations)


def test_forced_escape_scenario_can_leave_property():
    cfg = FarmConfig(width_m=100, height_m=100, animal_count=1, anchor_count=0,
                     duration_s=6000, sample_period_s=60, seed=4)
    ep = simulate_episode(cfg, obstacles=[], escape_targets={"tag-0001": (-100.0, 50.0)})
    assert any(p.x < 0 for p in ep.ground_truth)


def test_hundred_animal_spawn_respects_collision_clearance_and_obstacles():
    cfg = FarmConfig(width_m=1000, height_m=1000, animal_count=100, anchor_count=8,
                     duration_s=0, sample_period_s=1, seed=92)
    farm = FarmSimulator(cfg)
    for index, animal in enumerate(farm.states):
        assert farm._valid_point(animal.x, animal.y, COLLISION_RADIUS_M)
        for other in farm.states[index + 1:]:
            assert math.hypot(animal.x - other.x, animal.y - other.y) >= 2 * COLLISION_RADIUS_M


def test_hundred_animals_remain_collision_free_and_inside_obstacles_after_motion():
    cfg = FarmConfig(width_m=1000, height_m=1000, animal_count=100, anchor_count=8,
                     duration_s=30, sample_period_s=5, seed=17)
    farm = FarmSimulator(cfg)
    for timestamp in range(1, 31):
        farm._step(timestamp, 1.0)
        for index, animal in enumerate(farm.states):
            assert farm._valid_point(animal.x, animal.y, COLLISION_RADIUS_M)
            for other in farm.states[index + 1:]:
                assert math.hypot(animal.x - other.x, animal.y - other.y) + 1e-4 >= 2 * COLLISION_RADIUS_M
    assert farm.diagnostics["residual_overlap_m"] <= 1e-4


def test_farm_fixed_step_motion_is_independent_of_snapshot_cadence():
    cfg = FarmConfig(width_m=1000, height_m=1000, animal_count=10, anchor_count=4,
                     duration_s=0, sample_period_s=1, seed=23)
    slow_snapshots = FarmSimulator(cfg)
    fast_snapshots = FarmSimulator(cfg)
    for timestamp in range(1, 11):
        slow_snapshots._step(timestamp, 1.0)
        for _ in range(2):
            fast_snapshots._step(timestamp - 0.5, 0.5)
    assert [(s.x, s.y, s.vx, s.vy) for s in slow_snapshots.states] == [
        (s.x, s.y, s.vx, s.vy) for s in fast_snapshots.states]
