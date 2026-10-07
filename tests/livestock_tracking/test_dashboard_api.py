from fastapi.testclient import TestClient
from contextlib import ExitStack
import math
import sqlite3
import time

import pytest
from riose.products.livestock_tracking.adapters import api as livestock_api

from cattle_rf.api import (
    MAX_SIMULATION_MEMORY_UNITS,
    MAX_SIMULATION_OBSERVATIONS,
    SimulationRequest,
    create_app,
    estimate_simulation_memory_units,
    estimate_simulation_observations,
)


def test_farm_stream_interval_tracks_simulation_sample_rate():
    assert livestock_api.farm_stream_interval_seconds(30, 5) == 1.0
    assert livestock_api.farm_stream_interval_seconds(2, 5) == 0.8
    assert livestock_api.farm_stream_interval_seconds(30, 0) == 1.0


def test_farm_snapshot_cache_coalesces_clients_and_invalidates_on_run_changes(tmp_path, monkeypatch):
    app = create_app(tmp_path / "snapshot-cache.sqlite3")
    calls = 0
    original_get_metrics = app.state.store.get_metrics

    def counted_get_metrics():
        nonlocal calls
        calls += 1
        return original_get_metrics()

    monkeypatch.setattr(app.state.store, "get_metrics", counted_get_metrics)
    with TestClient(app) as client:
        first = client.get("/api/farm/snapshot")
        second = client.get("/api/farm/snapshot")
        assert first.status_code == second.status_code == 200
        assert calls == 1

        run = client.post("/api/simulation/run", json={
            "animal_count": 1, "anchor_count": 1,
            "anchors": [{"anchor_id": "anchor-one", "x": 500, "y": 500}],
            "duration_s": 60, "sample_period_s": 30, "seed": 13,
        })
        assert run.status_code == 200, run.text
        after_run = client.get("/api/farm/snapshot").json()
        assert after_run["simulation"]["run_id"] == run.json()["run_id"]
        assert calls == 2

        started = client.post("/api/simulation/control", json={"action": "start"})
        assert started.status_code == 200
        after_control = client.get("/api/farm/snapshot").json()
        assert after_control["simulation"]["status"] == "playing"
        assert calls == 3


def test_concurrent_farm_websockets_share_one_database_snapshot_per_tick(tmp_path, monkeypatch):
    app = create_app(tmp_path / "shared-websocket-snapshot.sqlite3")
    calls = 0
    original_get_metrics = app.state.store.get_metrics

    def counted_get_metrics():
        nonlocal calls
        calls += 1
        return original_get_metrics()

    monkeypatch.setattr(app.state.store, "get_metrics", counted_get_metrics)
    client = TestClient(app)
    with client:
        with ExitStack() as stack:
            sockets = [stack.enter_context(client.websocket_connect("/ws/farm")) for _ in range(10)]
            first_tick = [socket.receive_json() for socket in sockets]
            assert all(len(snapshot["animals"]) == 100 for snapshot in first_tick)
            assert calls == 1

            time.sleep(1.1)
            second_tick = [socket.receive_json() for socket in sockets]
            assert all(len(snapshot["scene_positions"]) == 0 for snapshot in second_tick)
            assert calls <= 2


def test_dashboard_explicit_anchors_and_debug_only_truth(tmp_path):
    app = create_app(tmp_path / "dashboard.sqlite3")
    client = TestClient(app)
    page = client.get("/demo")
    assert page.status_code == 200
    assert 'id="root"' in page.text
    assert "/assets/digital-twin/farm.js" in page.text
    assert "farm-map.webp" not in page.text
    anchors = [
        {"anchor_id": "north-west", "x": 0, "y": 0},
        {"anchor_id": "north-east", "x": 1000, "y": 0},
        {"anchor_id": "south-east", "x": 1000, "y": 1000},
        {"anchor_id": "south-west", "x": 0, "y": 1000},
    ]
    response = client.post("/api/simulation/run", json={
        "animal_count": 1,
        "anchor_count": 4,
        "anchors": anchors,
        "duration_s": 60,
        "sample_period_s": 30,
        "seed": 19,
    })
    assert response.status_code == 200, response.text
    assert response.json()["evidence"] == "SIMULATED"
    assert [a["anchor_id"] for a in client.get("/api/anchors").json()] == [
        "north-west", "north-east", "south-east", "south-west"
    ]
    assert all(isinstance(a["enabled"], bool) for a in client.get("/api/anchors").json())
    snapshot = client.get("/api/farm/snapshot").json()
    assert len(snapshot["anchors"]) == 4
    assert all(isinstance(a["enabled"], bool) for a in snapshot["anchors"])

    tag_id = "tag-0001"
    regular = client.get("/api/positions", params={"limit": 100, "at_s": 60}).json()
    assert regular and "ground_truth_x" not in regular[0]
    history = client.get("/api/positions/history", params={"tag_id": tag_id, "limit": 100}).json()
    assert history and "ground_truth_x" not in history[0]
    debug = client.get("/api/positions/history", params={
        "tag_id": tag_id, "limit": 100, "debug": "true"
    }).json()
    assert debug and "ground_truth_x" in debug[0]
    assert debug == sorted(debug, key=lambda row: row["timestamp"])


def test_animal_asset_intent_keeps_public_metadata_separate_and_submission_unverified(tmp_path):
    client = TestClient(create_app(tmp_path / "animal-assets.sqlite3"))
    created = client.post("/api/animals", json={
        "animal_id": "private-cow-42",
        "hardware_id": "private-ear-tag-42",
        "name": "Boi confidencial",
        "property_name": "Fazenda confidencial",
        "breed": "Nelore",
    })
    assert created.status_code == 201, created.text

    intent = client.post("/api/animals/private-cow-42/asset-intent")
    assert intent.status_code == 200, intent.text
    prepared = intent.json()
    assert prepared["cluster"] == "devnet"
    assert prepared["status"] == "PREPARED"
    assert prepared["metadata_uri"].startswith("http://testserver/api/animal-assets/metadata/")
    assert "private-cow-42" not in intent.text
    assert "private-ear-tag-42" not in intent.text

    reservation = client.post("/api/animals/private-cow-42/asset-reserve", json={
        "asset_address": "A" * 32,
        "owner_address": "B" * 32,
        "attempt_ref": "a" * 32,
    })
    assert reservation.status_code == 200, reservation.text
    assert reservation.json()["status"] == "RESERVED"
    reserved_intent = client.post("/api/animals/private-cow-42/asset-intent").json()
    assert reserved_intent["status"] == "SIGNING"
    assert reserved_intent["evidence"] == "ATTEMPT_RESERVED"
    assert client.post("/api/animals/private-cow-42/asset-reserve", json={
        "asset_address": "C" * 32,
        "owner_address": "B" * 32,
        "attempt_ref": "b" * 32,
    }).status_code == 409

    metadata = client.get(prepared["metadata_uri"])
    assert metadata.status_code == 200, metadata.text
    public_metadata = metadata.json()
    assert public_metadata["name"] == "RIOSE · Ativo bovino"
    assert public_metadata["attributes"] == []
    assert "Boi confidencial" not in metadata.text
    assert "Fazenda confidencial" not in metadata.text
    assert "Nelore" not in metadata.text
    assert "private-cow-42" not in metadata.text
    assert "private-ear-tag-42" not in metadata.text

    submission = client.post("/api/animals/private-cow-42/asset-submission", json={
        "asset_address": "A" * 32,
        "owner_address": "B" * 32,
        "transaction_signature": "1" * 88,
        "attempt_ref": "a" * 32,
    })
    assert submission.status_code == 200, submission.text
    assert submission.json()["status"] == "SUBMITTED"
    assert submission.json()["evidence"] == "SUBMITTED_UNVERIFIED"

    repeated_intent = client.post("/api/animals/private-cow-42/asset-intent")
    assert repeated_intent.json()["public_ref"] == prepared["public_ref"]
    assert repeated_intent.json()["status"] == "SUBMITTED"
    state = client.get("/api/animals/private-cow-42/asset")
    assert state.json()["evidence"] == "SUBMITTED_UNVERIFIED"

    bundle = client.get("/assets/animal-tokenization.bundle.js")
    assert bundle.status_code == 200
    assert "VALIDATED_ON_DEVNET" in bundle.text

    conflicting_submission = client.post(
        "/api/animals/private-cow-42/asset-submission",
        json={
            "asset_address": "C" * 32,
            "owner_address": "B" * 32,
            "transaction_signature": "2" * 88,
            "attempt_ref": "a" * 32,
        },
    )
    assert conflicting_submission.status_code == 409


def test_asset_reconciliation_only_retries_after_confirmed_devnet_failure(tmp_path, monkeypatch):
    client = TestClient(create_app(tmp_path / "animal-asset-reconcile.sqlite3"))
    created = client.post("/api/animals", json={
        "animal_id": "cow-retry",
        "hardware_id": "tag-retry",
    })
    assert created.status_code == 201
    client.post("/api/animals/cow-retry/asset-intent")
    reservation = client.post("/api/animals/cow-retry/asset-reserve", json={
        "asset_address": "A" * 32,
        "owner_address": "B" * 32,
        "attempt_ref": "c" * 32,
    })
    assert reservation.status_code == 200
    submitted = client.post("/api/animals/cow-retry/asset-submission", json={
        "asset_address": "A" * 32,
        "owner_address": "B" * 32,
        "transaction_signature": "1" * 88,
        "attempt_ref": "c" * 32,
    })
    assert submitted.status_code == 200
    assert client.post("/api/animals/cow-retry/asset-release", json={
        "attempt_ref": "c" * 32,
    }).status_code == 409

    monkeypatch.setattr(livestock_api, "devnet_signature_status", lambda _signature: None)
    unknown = client.post("/api/animals/cow-retry/asset-reconcile", json={
        "transaction_signature": "1" * 88,
    })
    assert unknown.status_code == 409
    assert client.get("/api/animals/cow-retry/asset").json()["status"] == "SUBMITTED"

    monkeypatch.setattr(livestock_api, "devnet_signature_status", lambda _signature: {
        "confirmationStatus": "confirmed",
        "err": None,
    })
    succeeded = client.post("/api/animals/cow-retry/asset-reconcile", json={
        "transaction_signature": "1" * 88,
    })
    assert succeeded.status_code == 409
    assert client.get("/api/animals/cow-retry/asset").json()["status"] == "SUBMITTED"

    monkeypatch.setattr(livestock_api, "devnet_signature_status", lambda _signature: {
        "confirmationStatus": "confirmed",
        "err": {"InstructionError": [0, "Custom"]},
    })
    failed = client.post("/api/animals/cow-retry/asset-reconcile", json={
        "transaction_signature": "1" * 88,
    })
    assert failed.status_code == 200, failed.text
    assert failed.json() == {
        "cluster": "devnet",
        "status": "PREPARED",
        "evidence": "ONCHAIN_FAILURE_CONFIRMED",
    }
    assert client.get("/api/animals/cow-retry/asset").json()["status"] == "PREPARED"


def test_animal_asset_attempt_reservation_serializes_mint_and_only_releases_matching_attempt(tmp_path):
    client = TestClient(create_app(tmp_path / "animal-asset-reservation.sqlite3"))
    created = client.post("/api/animals", json={
        "animal_id": "cow-reserve",
        "hardware_id": "tag-reserve",
    })
    assert created.status_code == 201
    client.post("/api/animals/cow-reserve/asset-intent")
    reservation = client.post("/api/animals/cow-reserve/asset-reserve", json={
        "asset_address": "A" * 32,
        "owner_address": "B" * 32,
        "attempt_ref": "d" * 32,
    })
    assert reservation.status_code == 200
    state = client.get("/api/animals/cow-reserve/asset").json()
    assert state["status"] == "SIGNING"
    assert state["evidence"] == "ATTEMPT_RESERVED"

    wrong_release = client.post("/api/animals/cow-reserve/asset-release", json={
        "attempt_ref": "e" * 32,
    })
    assert wrong_release.status_code == 409
    assert client.get("/api/animals/cow-reserve/asset").json()["status"] == "SIGNING"

    released = client.post("/api/animals/cow-reserve/asset-release", json={
        "attempt_ref": "d" * 32,
    })
    assert released.status_code == 200
    assert released.json()["evidence"] == "UNSIGNED_RESERVATION_RELEASED"
    assert client.get("/api/animals/cow-reserve/asset").json()["status"] == "PREPARED"
    assert client.post("/api/animals/cow-reserve/asset-release", json={
        "attempt_ref": "d" * 32,
    }).status_code == 200


def test_dashboard_rerun_replaces_duplicate_visible_samples_and_keeps_latest_page(tmp_path):
    client = TestClient(create_app(tmp_path / "rerun-history.sqlite3"))
    common = {"animal_count": 1, "anchor_count": 4, "duration_s": 90,
              "sample_period_s": 30, "method": "strongest_anchor"}
    for seed in (11, 29):
        response = client.post("/api/simulation/run", json={**common, "seed": seed})
        assert response.status_code == 200, response.text

    history = client.get("/api/positions/history", params={
        "tag_id": "tag-0001", "limit": 100,
    }).json()
    assert [row["timestamp"] for row in history] == [0.0, 30.0, 60.0]
    assert [row["timestamp"] for row in client.get(
        "/api/positions/history", params={"tag_id": "tag-0001", "limit": 2}
    ).json()] == [30.0, 60.0]
    animal = client.get("/api/animals/cow-0001").json()
    assert [row["timestamp"] for row in animal["trajectory"]] == [0.0, 30.0, 60.0]

    telemetry = client.get("/api/telemetry", params={"tag_id": "tag-0001", "limit": 100}).json()
    assert len(telemetry) == 12
    assert len({(row["timestamp"], row["anchor_id"]) for row in telemetry}) == 12
    assert "sample_rank" not in telemetry[0]
    latest_telemetry = client.get("/api/telemetry", params={
        "tag_id": "tag-0001", "limit": 4,
    }).json()
    assert len(latest_telemetry) == 4
    assert {row["timestamp"] for row in latest_telemetry} == {60.0}


def test_dashboard_exposes_simulation_only_virtual_fence_action(tmp_path):
    client = TestClient(create_app(tmp_path / "virtual-fence-ui.sqlite3"))
    page = client.get("/demo")

    assert page.status_code == 200
    assert 'id="root"' in page.text
    assert 'id="runFence"' not in page.text
    assert "api/experiments/virtual-fence" not in page.text
    simulation = client.post("/api/simulation/run", json={
        "animal_count": 1, "anchor_count": 4, "duration_s": 30,
        "sample_period_s": 30, "seed": 12,
    })
    assert simulation.status_code == 200
    response = client.post("/api/experiments/virtual-fence", json={
        "zones": [{"zone_id": "zone-central-demo", "kind": "WARNING_ZONE",
                   "polygon": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]]}],
    })
    assert response.status_code == 200
    assert response.json()["status"] == "SIMULATED"
    assert response.json()["electric_stimulus"] is False


def test_landing_page_and_static_product_assets(tmp_path):
    client = TestClient(create_app(tmp_path / "landing.sqlite3"))

    page = client.get("/")
    assert page.status_code == 200
    assert "RIOSE — Livestock technology" in page.text
    assert "Machine learning-assisted self-powered ear tag for animal welfare" in page.text
    assert 'id="inspection-toggle"' not in page.text
    assert "turn toward the rear" in page.text
    assert "wire routing is illustrative" in page.text
    assert "Xiaoyu Su, Peidi Fan, Ying Liu, Jianfeng Ping, Xunjia Li and Yuxiang Pan" in page.text
    assert "Nature Communications · 2026" in page.text
    assert "Independent study" not in page.text
    assert "5,399 sampling windows from three animals" in page.text
    assert 'id="product-canvas"' in page.text
    assert "scene-fallback" not in page.text
    assert "/assets/product-scene.js" in page.text
    assert "/assets/landing.css" in page.text
    assert "/assets/landing.js" in page.text
    assert "<style>" not in page.text
    assert "<script>" not in page.text

    manifesto = client.get("/manifesto")
    assert manifesto.status_code == 200
    assert "Manifesto — RIOSE" in manifesto.text
    assert "The physical world takes no shortcuts." in manifesto.text
    assert "Named after Bel Riose" in manifesto.text
    assert "proper noun · origin" in manifesto.text
    assert "/assets/manifesto.css" in manifesto.text
    assert "/assets/manifesto.js" in manifesto.text
    assert "<style>" not in manifesto.text
    assert "<script>" not in manifesto.text

    landing_css = client.get("/assets/landing.css")
    assert landing_css.status_code == 200
    assert ".scene-wrap" in landing_css.text
    landing_js = client.get("/assets/landing.js")
    assert landing_js.status_code == 200
    assert "sceneObserver" in landing_js.text

    manifesto_css = client.get("/assets/manifesto.css")
    assert manifesto_css.status_code == 200
    assert ".manifesto-copy" in manifesto_css.text
    manifesto_js = client.get("/assets/manifesto.js")
    assert manifesto_js.status_code == 200
    assert "ascii-structure" in manifesto_js.text

    scene = client.get("/assets/product-scene.js")
    assert scene.status_code == 200
    assert "WebGLRenderer" in scene.text
    assert "smoothstep(faceAlignment" in scene.text
    assert "createTechnicalAnnotations" in scene.text
    assert "wireRoutes" in scene.text
    assert "Circuit board" in scene.text
    assert "PCB · concept" not in scene.text
    assert "CONCEPT STUDY" not in scene.text

    three = client.get("/assets/vendor/three.module.js")
    assert three.status_code == 200
    assert "Three.js Authors" in three.text
    assert three.headers.get("content-encoding") == "gzip"

    fallback = client.get("/assets/riose-ear-tag-fallback.webp")
    assert fallback.status_code == 404


def test_dashboard_closes_sqlite_store_on_lifespan_shutdown(tmp_path):
    app = create_app(tmp_path / "lifecycle.sqlite3")
    store = app.state.store

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200

    assert store.connection is not None
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        store.connection.execute("SELECT 1")


def test_simulation_rejects_duplicate_or_outside_farm_anchors(tmp_path):
    client = TestClient(create_app(tmp_path / "invalid.sqlite3"))
    common = {"animal_count": 1, "duration_s": 30, "sample_period_s": 30}
    duplicate = [{"anchor_id": "a", "x": 0, "y": 0}] * 2
    response = client.post("/api/simulation/run", json={**common, "anchors": duplicate})
    assert response.status_code == 422
    outside = [{"anchor_id": "a", "x": 1001, "y": 0}]
    response = client.post("/api/simulation/run", json={**common, "anchors": outside})
    assert response.status_code == 422


def test_simulation_rejects_nonfinite_and_extreme_numeric_inputs(tmp_path):
    client = TestClient(create_app(tmp_path / "numeric-input.sqlite3"))
    response = client.post("/api/simulation/run", json={
        "animal_count": 1,
        "anchor_count": 4,
        "duration_s": 1e308,
        "sample_period_s": 5e-324,
    })
    assert response.status_code == 422

    response = client.post("/api/simulation/run", content='{"width_m":null}',
                           headers={"content-type": "application/json"})
    assert response.status_code == 422
    with pytest.raises(ValueError):
        SimulationRequest(width_m=float("nan"))


@pytest.mark.parametrize("nonfinite", ["NaN", "Infinity", "-Infinity"])
def test_simulation_rejects_nonfinite_packet_loss_before_persisting(tmp_path, nonfinite):
    app = create_app(tmp_path / f"nonfinite-{nonfinite}.sqlite3")
    with TestClient(app) as client:
        response = client.post(
            "/api/simulation/run",
            content=(
                '{"animal_count":1,"anchor_count":4,"duration_s":30,'
                f'"sample_period_s":30,"packet_loss_probability":{nonfinite}'
                "}"
            ),
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 422
        assert client.get("/api/anchors").json() == []
        assert client.get("/api/telemetry").json() == []
        assert client.get("/api/positions").json() == []
        assert client.get("/api/metrics").json() == {}
        assert client.get("/api/animals").json() == []


def test_simulation_rejects_requests_over_memory_budget_before_running(tmp_path, monkeypatch):
    from riose.products.livestock_tracking.application import pipeline

    def should_not_start(*args, **kwargs):
        raise AssertionError("oversized request reached the simulation pipeline")

    monkeypatch.setattr(pipeline, "run_episode", should_not_start)
    client = TestClient(create_app(tmp_path / "oversized.sqlite3"))
    response = client.post("/api/simulation/run", json={
        "animal_count": 1000,
        "anchor_count": 40,
        "duration_s": 86400,
        "sample_period_s": 1,
    })
    assert response.status_code == 422
    assert "observation budget" in response.json()["detail"]


def test_memory_budget_keeps_default_supervised_dashboard_scenario_available():
    request = SimulationRequest(
        animal_count=100,
        anchor_count=8,
        duration_s=1800,
        sample_period_s=30,
        method="extra_trees",
    )

    estimate = estimate_simulation_observations(request, enabled_anchors=8)
    assert estimate == 480_000
    assert estimate <= MAX_SIMULATION_OBSERVATIONS
    assert estimate_simulation_memory_units(request, enabled_anchors=8) <= MAX_SIMULATION_MEMORY_UNITS


def test_memory_budget_counts_truth_and_motion_when_anchors_are_disabled(tmp_path, monkeypatch):
    from riose.products.livestock_tracking.application import pipeline

    def should_not_start(*args, **kwargs):
        raise AssertionError("oversized disabled-anchor request reached the simulation pipeline")

    monkeypatch.setattr(pipeline, "run_episode", should_not_start)
    client = TestClient(create_app(tmp_path / "disabled-anchors.sqlite3"))
    anchors = [
        {"anchor_id": f"a{i}", "x": (i % 2) * 1000, "y": (i // 2) * 1000,
         "enabled": False}
        for i in range(4)
    ]
    response = client.post("/api/simulation/run", json={
        "animal_count": 1000,
        "anchor_count": 4,
        "anchors": anchors,
        "duration_s": 604800,
        "sample_period_s": 1,
    })
    assert response.status_code == 422
    assert "at least one anchor must be enabled" in response.json()["detail"]


def test_memory_budget_rejects_large_ground_truth_even_with_one_enabled_anchor(tmp_path, monkeypatch):
    from riose.products.livestock_tracking.application import pipeline

    def should_not_start(*args, **kwargs):
        raise AssertionError("oversized request reached the simulation pipeline")

    monkeypatch.setattr(pipeline, "run_episode", should_not_start)
    client = TestClient(create_app(tmp_path / "truth-memory.sqlite3"))
    anchors = [
        {"anchor_id": f"a{i}", "x": (i % 2) * 1000, "y": (i // 2) * 1000,
         "enabled": i == 0}
        for i in range(4)
    ]
    response = client.post("/api/simulation/run", json={
        "animal_count": 1000,
        "anchor_count": 4,
        "anchors": anchors,
        "duration_s": 1000,
        "sample_period_s": 2,
    })
    assert response.status_code == 422
    assert "in-memory observation budget" not in response.json()["detail"]
    assert "in-memory sample budget" in response.json()["detail"]


def test_farm_stream_and_playback_keep_100_animals_and_8_anchors(tmp_path):
    client = TestClient(create_app(tmp_path / "digital-twin.sqlite3"))
    with client:
        response = client.post("/api/simulation/run", json={
            "animal_count": 100,
            "anchor_count": 8,
            "duration_s": 30,
            "sample_period_s": 30,
            "seed": 41,
        })
        assert response.status_code == 200, response.text
        assert response.json()["evidence"] == "SIMULATED"

        # RF estimates can be unavailable while the simulator still has valid
        # positions. The farm renderer must retain its independent scene poses.
        store = client.app.state.store
        with store._lock:
            store.connection.execute(
                "UPDATE positions SET x=NULL,y=NULL WHERE run_id=?",
                (response.json()["run_id"],),
            )
            store.connection.commit()

        with client.websocket_connect("/ws/farm") as websocket:
            snapshot = websocket.receive_json()
            assert snapshot["evidence"] == "SIMULATED"
            assert snapshot["simulation"]["status"] == "paused"
            assert len(snapshot["animals"]) == 100
            assert len({animal["animal_id"] for animal in snapshot["animals"]}) == 100
            assert len(snapshot["positions"]) == 100
            assert len(snapshot["scene_positions"]) == 100
            assert len(snapshot["positions"]) == len(snapshot["animals"])
            assert all(position["x"] is None and position["y"] is None
                       for position in snapshot["positions"])
            assert len(snapshot["anchors"]) == 8
            assert {position["status"] for position in snapshot["positions"]} == {"SIMULATED"}
            assert all("ground_truth_x" not in position for position in snapshot["positions"])
            debug = client.get("/api/positions", params={"debug": "true", "at_s": 0}).json()
            truth_by_tag = {position["tag_id"]: (position["ground_truth_x"], position["ground_truth_y"])
                            for position in debug}
            scene_by_tag = {position["tag_id"]: (position["x"], position["y"])
                            for position in snapshot["scene_positions"]}
            assert scene_by_tag == truth_by_tag
            assert len(snapshot["telemetry"]) == 800
            asset = client.get("/api/animals/cow-0001/asset")
            assert asset.status_code == 200
            assert asset.json()["status"] == "UNREGISTERED"
            assert asset.json()["evidence"] == "UNREGISTERED"

        speed = client.post("/api/simulation/control", json={"action": "speed", "speed": 5})
        assert speed.status_code == 200
        assert speed.json()["speed"] == 5
        started = client.post("/api/simulation/control", json={"action": "start"})
        assert started.json()["status"] == "playing"
        paused = client.post("/api/simulation/control", json={"action": "pause"})
        assert paused.json()["status"] == "paused"
        reset = client.post("/api/simulation/control", json={"action": "reset"})
        assert reset.json()["time_s"] == 0

        latest_run = client.post("/api/simulation/run", json={
            "animal_count": 1,
            "anchor_count": 4,
            "duration_s": 30,
            "sample_period_s": 30,
            "seed": 12,
        })
        assert latest_run.status_code == 200
        with client.websocket_connect("/ws/farm") as websocket:
            snapshot = websocket.receive_json()
        assert len(snapshot["animals"]) == 1
        assert len(snapshot["positions"]) == 1
        assert len(snapshot["anchors"]) == 4


def test_empty_database_bootstraps_snapshot_and_websocket_farm(tmp_path):
    client = TestClient(create_app(tmp_path / "empty-farm.sqlite3"))
    with client:
        first = client.get("/api/farm/snapshot")
        assert first.status_code == 200, first.text
        seeded = first.json()
        assert seeded["type"] == "snapshot"
        assert seeded["simulation"]["run_id"] is None
        assert seeded["evidence"] == "SIMULATED"
        assert len(seeded["animals"]) == 100
        assert len(seeded["anchors"]) == 8
        assert seeded["scene_positions"] == []

        # Starting the regular simulator after bootstrap yields authoritative
        # positions; the GET snapshot and existing WS share that payload.
        response = client.post("/api/simulation/run", json={
            "animal_count": 100,
            "anchor_count": 8,
            "duration_s": 4,
            "sample_period_s": 2,
            "seed": 7,
            "anchors": seeded["anchors"],
        })
        assert response.status_code == 200, response.text
        snapshot = client.get("/api/farm/snapshot").json()
        assert snapshot["simulation"]["run_id"] == response.json()["run_id"]
        assert len(snapshot["scene_positions"]) == 100
        assert len(snapshot["positions"]) == 100
        assert {animal["hardware_id"] for animal in snapshot["animals"]} == {
            position["tag_id"] for position in snapshot["scene_positions"]
        }
        assert all(
            isinstance(position["x"], (int, float))
            and isinstance(position["y"], (int, float))
            and math.isfinite(position["x"])
            and math.isfinite(position["y"])
            for position in snapshot["scene_positions"]
        )

        # HTTP and WebSocket use the same authoritative farm snapshot.
        with client.websocket_connect("/ws/farm") as websocket:
            streamed = websocket.receive_json()
        assert streamed["simulation"]["run_id"] == snapshot["simulation"]["run_id"]
        assert len(streamed["animals"]) == 100
        assert len(streamed["scene_positions"]) == 100


def test_farm_snapshot_preserves_run_entities_when_scene_poses_are_missing(tmp_path):
    client = TestClient(create_app(tmp_path / "legacy-pose-gap.sqlite3"))
    with client:
        seeded = client.get("/api/farm/snapshot").json()
        run = client.post("/api/simulation/run", json={
            "animal_count": 100,
            "anchor_count": 8,
            "duration_s": 30,
            "sample_period_s": 2,
            "seed": 7,
            "anchors": seeded["anchors"],
        })
        assert run.status_code == 200, run.text

        # Reproduce a legacy run whose RF estimates remain but simulator pose
        # history was not retained/migrated. Entity IDs must survive so the
        # client can report and recover the missing pose source.
        store = client.app.state.store
        with store._lock:
            store.connection.execute("DELETE FROM scene_truth WHERE run_id=?", (run.json()["run_id"],))
            store.connection.execute("DELETE FROM debug_truth")
            store.connection.commit()

        snapshot = client.get("/api/farm/snapshot").json()
        assert snapshot["simulation"]["run_id"] == run.json()["run_id"]
        assert snapshot["simulation"]["status"] == "paused"
        assert len(snapshot["positions"]) == 100
        assert len(snapshot["animals"]) == 100
        assert snapshot["scene_positions"] == []


def test_animal_trajectory_can_be_limited_to_the_active_simulation_run(tmp_path):
    client = TestClient(create_app(tmp_path / "run-scoped-trajectory.sqlite3"))
    with client:
        long_run = client.post("/api/simulation/run", json={
            "animal_count": 1, "anchor_count": 4,
            "duration_s": 90, "sample_period_s": 30, "seed": 31,
        })
        assert long_run.status_code == 200
        old_run_id = client.get("/api/simulation/state").json()["run_id"]
        assert len(client.get("/api/animals/cow-0001/trajectory",
                             params={"run_id": old_run_id}).json()) == 3

        short_run = client.post("/api/simulation/run", json={
            "animal_count": 1, "anchor_count": 4,
            "duration_s": 30, "sample_period_s": 30, "seed": 32,
        })
        assert short_run.status_code == 200
        new_run_id = client.get("/api/simulation/state").json()["run_id"]
        latest = client.get("/api/animals/cow-0001/trajectory",
                            params={"run_id": new_run_id}).json()
        combined = client.get("/api/animals/cow-0001/trajectory").json()

    assert new_run_id != old_run_id
    assert len(latest) == 1
    assert len(combined) == 3
