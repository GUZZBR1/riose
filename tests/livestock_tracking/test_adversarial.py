"""System-level and adversarial checks for the simulated MVP.

These checks validate software boundaries and simulation behavior only. They
do not establish RF performance on a physical farm.
"""

from __future__ import annotations

import csv
from dataclasses import fields
import json
import math
from pathlib import Path

import pytest

from cattle_rf.contracts import Anchor, Estimate, FarmConfig, GroundTruth, RFObservation
from cattle_rf.datasets import write_episode_dataset
from cattle_rf.db import Store
from cattle_rf.firmware.energy import EnergyLedger, EnergyProfile
from cattle_rf.firmware.tag import Activity, MemoryHAL, TagConfig, TagController
from cattle_rf.identity import append_event, verify_event_chain
from cattle_rf.localization import estimate, evaluate
from cattle_rf.sim.episode import simulate_episode
from cattle_rf.sim.farm import Behavior, FarmSimulator
from cattle_rf.sim.rf import RFConfig


def test_inference_and_serialized_features_cannot_carry_truth_coordinates(tmp_path: Path):
    config = FarmConfig(width_m=100, height_m=100, animal_count=2, anchor_count=4,
                        duration_s=60, sample_period_s=60, seed=88, packet_loss_probability=0)
    episode = simulate_episode(config)
    observation_fields = {field.name for field in fields(RFObservation)}
    assert not observation_fields.intersection({"x", "y", "ground_truth_x", "ground_truth_y"})

    outputs = write_episode_dataset(episode.observations, episode.ground_truth,
                                    tmp_path, "holdout")
    with Path(outputs["features_csv"]).open(newline="", encoding="utf-8") as stream:
        feature_header = next(csv.reader(stream))
    feature_fields = set(feature_header)
    with Path(outputs["ground_truth_csv"]).open(newline="", encoding="utf-8") as stream:
        truth_fields = set(next(csv.reader(stream)))
    assert feature_fields.isdisjoint({"x", "y", "ground_truth_x", "ground_truth_y"})
    assert {"x", "y"} <= truth_fields
    manifest = json.loads(Path(outputs["manifest"]).read_text(encoding="utf-8"))
    assert manifest["feature_fields"] == feature_header


def test_packet_loss_is_seeded_and_all_loss_produces_no_position():
    config = FarmConfig(width_m=100, height_m=100, animal_count=1, anchor_count=4,
                        duration_s=300, sample_period_s=30, seed=11,
                        packet_loss_probability=0.5)
    first, second = simulate_episode(config), simulate_episode(config)
    assert first == second
    received = sum(row.packet_received for row in first.observations)
    assert 0 < received < len(first.observations)

    all_loss = simulate_episode(FarmConfig(width_m=100, height_m=100, animal_count=1,
                              anchor_count=4, duration_s=0, sample_period_s=60,
                              seed=11, packet_loss_probability=1))
    assert all(not row.packet_received for row in all_loss.observations)
    assert estimate(all_loss.observations, all_loss.anchors, "weighted_centroid")[0].x is None


def test_forced_nlos_reduces_received_signal_without_claiming_ranging():
    config = FarmConfig(width_m=100, height_m=100, animal_count=1, anchor_count=4,
                        duration_s=0, sample_period_s=60, seed=72,
                        packet_loss_probability=0)
    los = simulate_episode(config, rf_config=RFConfig(nlos_probability=0))
    nlos = simulate_episode(config, rf_config=RFConfig(nlos_probability=1))
    los_by_anchor = {row.anchor_id: row for row in los.observations}
    nlos_by_anchor = {row.anchor_id: row for row in nlos.observations}
    assert all(row.packet_received for row in los.observations + nlos.observations)
    assert all(nlos_by_anchor[key].rssi_dbm < los_by_anchor[key].rssi_dbm
               for key in los_by_anchor)
    assert all(row.tof_ns is None and row.phase_rad is None for row in nlos.observations)


def test_corrupt_or_missing_anchor_measurements_are_not_silently_truth_corrected():
    anchors = [Anchor("a", 0, 0), Anchor("b", 100, 0), Anchor("c", 100, 100), Anchor("d", 0, 100)]
    truth = GroundTruth(0, "tag-1", 50, 50)
    clean = [RFObservation(0, "tag-1", a.anchor_id, -80, 10, True) for a in anchors]
    corrupt = [RFObservation(0, "tag-1", a.anchor_id, 0 if a.anchor_id == "a" else -80, 10, True)
               for a in anchors]
    missing = [RFObservation(0, "tag-1", a.anchor_id, None, None, False) if a.anchor_id == "a" else row
               for a, row in zip(anchors, clean, strict=True)]
    clean_estimate = estimate(clean, anchors, "strongest_anchor")[0]
    corrupt_estimate = estimate(corrupt, anchors, "strongest_anchor")[0]
    missing_estimate = estimate(missing, anchors, "strongest_anchor")[0]
    assert (clean_estimate.x, clean_estimate.y) == (0, 0)
    assert (corrupt_estimate.x, corrupt_estimate.y) == (0, 0)
    assert (missing_estimate.x, missing_estimate.y) == (100, 0)
    assert evaluate([corrupt_estimate], [truth])["max_error_m"] == pytest.approx(math.sqrt(5000))


def test_per_anchor_clock_drift_is_aligned_to_one_epoch_and_truth_sample():
    anchors = [Anchor("a", 0, 0), Anchor("b", 100, 0), Anchor("c", 100, 100), Anchor("d", 0, 100)]
    offsets = {"a": -0.25, "b": 0.25, "c": -0.10, "d": 0.10}
    rows = [RFObservation(10.0 + offsets[a.anchor_id], "tag-1",
                          a.anchor_id, -70, 8, True) for a in anchors]
    estimates = estimate(rows, anchors, "weighted_centroid")
    assert len(estimates) == 1
    assert estimates[0].quality == pytest.approx(1.0)
    metrics = evaluate(estimates, [GroundTruth(10.0, "tag-1", 50, 50)])
    assert metrics["samples"] == 1
    assert metrics["coverage_pct"] == pytest.approx(100.0)


def test_stationary_animal_remains_stationary_in_controlled_rest_state():
    config = FarmConfig(width_m=100, height_m=100, animal_count=1, anchor_count=0,
                        duration_s=120, sample_period_s=60, seed=18)
    farm = FarmSimulator(config, obstacles=[])
    animal = farm.states[0]
    animal.behavior = Behavior.RESTING
    animal.behavior_until_s = float("inf")
    animal.vx = animal.vy = 0.0
    truth, _ = farm.generate()
    positions = [(point.x, point.y) for point in truth]
    assert len(positions) == 2
    assert positions[0] == positions[1]


def test_energy_ledger_arithmetic_and_unconfigured_battery_life():
    profile = EnergyProfile("test", sleep_ma=0.001, idle_ma=1, imu_monitoring_ma=2,
                            rf_tx_ma=10, rf_rx_ma=4, ble_active_ma=3, wifi_active_ma=20,
                            alert_ma=8)
    ledger = EnergyLedger(profile)
    ledger.record(10, 360)
    ledger.record(2, 360)
    report = ledger.report()
    assert report.consumed_mah == pytest.approx(1.2)
    assert report.average_current_ma == pytest.approx(6)
    assert report.energy_per_day_mah == pytest.approx(144)
    assert report.estimated_battery_life_days is None


def test_tag_fsm_energy_duration_matches_elapsed_wall_time():
    hal = MemoryHAL()
    tag = TagController(TagConfig("tag-1", normal_beacon_period_s=60), hal)
    tag.boot()
    tag.step(60, Activity.NORMAL)
    # Base state accounting must exclude the TX/RX subintervals already counted.
    assert tag.ledger.report().duration_s == pytest.approx(60)
    assert len(hal.transmissions) == 1


def test_dashboard_api_hides_truth_until_debug_query(tmp_path: Path):
    fastapi = pytest.importorskip("fastapi")
    httpx = pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from cattle_rf.api import create_app

    db_path = tmp_path / "api.sqlite3"
    app = create_app(db_path)
    store = app.state.store
    estimate_row = Estimate(60, "tag-1", 3, 4, "test")
    truth = GroundTruth(60, "tag-1", 0, 0)
    store.save_episode([], [estimate_row], [truth])
    client = TestClient(app)
    normal = client.get("/api/positions")
    debug = client.get("/api/positions?debug=true")
    assert normal.status_code == debug.status_code == 200
    assert "ground_truth_x" not in normal.json()[0]
    assert debug.json()[0]["ground_truth_x"] == 0
    assert debug.json()[0]["ground_truth_y"] == 0
    assert httpx.__version__  # Make the tested client dependency explicit.
    store.close()


def test_event_chain_detects_tampering(tmp_path: Path):
    store = Store(tmp_path / "identity.sqlite3")
    store.create_animal("cow-1", "tag-1", "crypto-1")
    append_event(store.connection, "cow-1", "WEIGHT_RECORDED", {"weight_kg": 410}, 2.0)
    assert verify_event_chain(store.connection, "cow-1")
    store.connection.execute("UPDATE animal_events SET payload=? WHERE event_type='WEIGHT_RECORDED'", ('{"weight_kg":1}',))
    store.connection.commit()
    assert not verify_event_chain(store.connection, "cow-1")
    store.close()
