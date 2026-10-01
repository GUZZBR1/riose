from dataclasses import fields

from cattle_rf.contracts import FarmConfig, RFObservation
from cattle_rf.sim.episode import generate_anchors, simulate_episode
from cattle_rf.sim.farm import Behavior, FarmSimulator, Obstacle, segment_crosses_obstacle
from cattle_rf.sim.rf import RFConfig, free_space_path_loss_db, log_distance_path_loss_db


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


def test_rf_packet_loss_and_nlos_are_configurable():
    cfg = FarmConfig(width_m=100, height_m=100, animal_count=1, anchor_count=4,
                     duration_s=0, sample_period_s=60, packet_loss_probability=1)
    ep = simulate_episode(cfg, rf_config=RFConfig(nlos_probability=1))
    assert ep.observations
    assert all(not o.packet_received and o.rssi_dbm is None for o in ep.observations)
