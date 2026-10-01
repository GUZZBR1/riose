from inspect import signature

import pytest

from cattle_rf.contracts import Anchor, Estimate, GroundTruth, RFObservation
from cattle_rf.localization import METHODS, estimate, evaluate, train_fingerprint_model


ANCHORS = [
    Anchor("a", 0.0, 0.0), Anchor("b", 100.0, 0.0),
    Anchor("c", 100.0, 100.0), Anchor("d", 0.0, 100.0),
]


def make_observations(x=40.0, y=35.0, timestamp=1.0, *, drop=()):
    rows = []
    # Deterministic log-distance synthetic values (noise-free for unit tests).
    for a in ANCHORS:
        if a.anchor_id in drop:
            rows.append(RFObservation(timestamp, "tag-1", a.anchor_id, None, None, False))
            continue
        distance = max(1.0, ((a.x - x) ** 2 + (a.y - y) ** 2) ** 0.5)
        rssi = -44.0 - 27.0 * __import__("math").log10(distance)
        rows.append(RFObservation(timestamp, "tag-1", a.anchor_id, rssi, 8.0, True,
                                   imu_accel_norm_g=1.0))
    return rows


def test_estimate_inference_contract_has_no_ground_truth_input():
    params = signature(estimate).parameters
    assert "ground_truth" not in params
    assert "truth" not in params
    assert set(METHODS) == {"strongest_anchor", "weighted_centroid", "path_loss",
                            "extra_trees", "gradient_boosting", "temporal_fusion"}


def test_strongest_anchor_and_centroid_are_observation_only():
    rows = make_observations()
    strongest = estimate(rows, ANCHORS, "strongest_anchor")[0]
    centroid = estimate(rows, ANCHORS, "weighted_centroid")[0]
    assert (strongest.x, strongest.y) == (0.0, 0.0)
    assert centroid.x == pytest.approx(40.0, abs=20.0)
    assert centroid.y == pytest.approx(35.0, abs=20.0)


def test_path_loss_returns_none_for_underdetermined_or_collinear_anchors():
    rows = make_observations(drop=("c", "d"))
    assert estimate(rows, ANCHORS, "path_loss")[0].x is None
    linear = [Anchor("a", 0, 0), Anchor("b", 10, 0), Anchor("c", 20, 0)]
    observations = [RFObservation(0, "t", a.anchor_id, -70, 0, True) for a in linear]
    assert estimate(observations, linear, "path_loss")[0].x is None


def test_missing_and_bad_packets_do_not_create_positions():
    rows = [RFObservation(0, "t", a.anchor_id, None, None, False) for a in ANCHORS]
    assert estimate(rows, ANCHORS, "weighted_centroid")[0].x is None
    with pytest.raises(ValueError, match="unknown localization method"):
        estimate(rows, ANCHORS, "gps")


def test_temporal_fusion_handles_gaps_and_prior_without_truth():
    first = make_observations(40, 35, 0)
    second = [RFObservation(60, "tag-1", a.anchor_id, None, None, False,
                            imu_accel_norm_g=1.0) for a in ANCHORS]
    estimates = estimate(first + second, ANCHORS, "temporal_fusion")
    assert estimates[0].x is not None
    assert estimates[1].x == pytest.approx(estimates[0].x)
    long_gap = [RFObservation(500, "tag-1", a.anchor_id, None, None, False) for a in ANCHORS]
    assert estimate(long_gap, ANCHORS, "temporal_fusion")[0].x is None
    seeded = estimate(second, ANCHORS, "temporal_fusion", prior_positions={"tag-1": (12, 9)})[0]
    assert (seeded.x, seeded.y) == (12, 9)


def test_small_anchor_clock_offsets_stay_in_one_epoch_and_align_to_truth():
    offsets = [-0.25, 0.25, -0.10, 0.10]
    rows = []
    truth = [GroundTruth(10.0, "tag-1", 40.0, 35.0)]
    for anchor, offset, source in zip(ANCHORS, offsets, make_observations(40, 35, 10), strict=True):
        rows.append(RFObservation(10.0 + offset, source.tag_id, anchor.anchor_id,
                                  source.rssi_dbm, source.snr_db, source.packet_received,
                                  source.imu_accel_norm_g))
    estimates = estimate(rows, ANCHORS, "weighted_centroid")
    assert len(estimates) == 1
    assert estimates[0].quality == pytest.approx(1.0)
    assert evaluate(estimates, truth)["coverage_pct"] == pytest.approx(100.0)


def test_fingerprint_train_and_inference_keeps_truth_out_of_predict_api():
    pytest.importorskip("sklearn")
    observations, truth = [], []
    for idx, (x, y) in enumerate([(20, 30), (35, 45), (60, 70), (80, 20)]):
        observations += make_observations(x, y, idx)
        truth.append(GroundTruth(idx, "tag-1", x, y))
    model = train_fingerprint_model(observations, truth, ANCHORS, "extra_trees", random_state=1)
    assert "ground_truth" not in signature(model.predict).parameters
    prediction = estimate(make_observations(35, 45, 9), ANCHORS, "extra_trees",
                          fingerprint_models={"extra_trees": model})[0]
    assert prediction.x is not None and prediction.y is not None
    unavailable = estimate(make_observations(), ANCHORS, "gradient_boosting")[0]
    assert unavailable.x is None


def test_gradient_boosting_fingerprint_supports_two_coordinate_output():
    pytest.importorskip("sklearn")
    observations, truth = [], []
    for idx, (x, y) in enumerate([(20, 30), (35, 45), (60, 70), (80, 20)]):
        observations += make_observations(x, y, idx)
        truth.append(GroundTruth(idx, "tag-1", x, y))
    model = train_fingerprint_model(observations, truth, ANCHORS,
                                    "gradient_boosting", random_state=1)
    prediction = estimate(make_observations(35, 45, 9), ANCHORS,
                          "gradient_boosting",
                          fingerprint_models={"gradient_boosting": model})[0]
    assert prediction.x is not None and prediction.y is not None


def test_evaluate_reports_raw_errors_and_coverage():
    estimates = [Estimate(1, "tag-1", 3.0, 4.0, "test"), Estimate(2, "tag-1", None, None, "test")]
    truth = [GroundTruth(1, "tag-1", 0.0, 0.0), GroundTruth(2, "tag-1", 0.0, 0.0)]
    metrics = evaluate(estimates, truth)
    assert metrics["mean_error_m"] == pytest.approx(5.0)
    assert metrics["max_error_m"] == pytest.approx(5.0)
    assert metrics["coverage_pct"] == pytest.approx(50.0)


def test_train_requires_matching_samples():
    with pytest.raises(ValueError, match="two matching"):
        train_fingerprint_model(make_observations(), [], ANCHORS)
