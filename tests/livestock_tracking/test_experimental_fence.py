from cattle_rf.contracts import EvidenceStatus, GroundTruth
from cattle_rf.experimental import simulate_wifi_csi
from cattle_rf.virtual_fence import FenceState, FenceZone, simulate_fence


def test_wifi_csi_is_deterministic_and_marked_experimental():
    first = simulate_wifi_csi(0, "tag-1", "anchor-1", 0.8, seed=12)
    second = simulate_wifi_csi(0, "tag-1", "anchor-1", 0.8, seed=12)
    assert first == second
    assert len(first.amplitude) == len(first.phase_rad) == 32
    assert first.status == EvidenceStatus.EXPERIMENTAL


def test_virtual_fence_only_emits_simulated_audio_or_vibration_cues():
    forbidden = FenceZone("north", "FORBIDDEN_ZONE",
                          ((0, 0), (10, 0), (10, 10), (0, 10)))
    truth = [GroundTruth(0, "tag-1", 12, 5),
             GroundTruth(1, "tag-1", 9, 5),
             GroundTruth(2, "tag-1", 20, 5)]
    events = simulate_fence(truth, [forbidden], warning_distance_m=3)
    assert [event.state for event in events] == [
        FenceState.WARNING, FenceState.SIMULATED_AUDIO_CUE, FenceState.NORMAL]
    assert all(event.status == EvidenceStatus.SIMULATED for event in events)
    assert all("electric" not in event.simulated_response for event in events)


def test_virtual_fence_api_logs_only_simulated_cues(tmp_path):
    from fastapi.testclient import TestClient
    from cattle_rf.api import create_app

    client = TestClient(create_app(tmp_path / "farm.sqlite3"))
    run = client.post("/api/simulation/run", json={
        "animal_count": 1, "anchor_count": 4, "duration_s": 60,
        "sample_period_s": 60, "seed": 4,
    })
    assert run.status_code == 200
    response = client.post("/api/experiments/virtual-fence", json={"zones": [{
        "zone_id": "whole-farm", "kind": "FORBIDDEN_ZONE",
        "polygon": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]],
    }]})
    assert response.status_code == 200
    result = response.json()
    assert result["electric_stimulus"] is False
    assert result["events"][0]["state"] == "simulated_audio_cue"
    assert "ground_truth_x" not in result["events"][0]


def test_virtual_fence_events_follow_hardware_to_animal_assignment(tmp_path):
    from fastapi.testclient import TestClient
    from cattle_rf.api import create_app

    client = TestClient(create_app(tmp_path / "assigned-animal.sqlite3"))
    created = client.post("/api/animals", json={
        "animal_id": "heifer-west",
        "hardware_id": "tag-0001",
    })
    assert created.status_code == 201, created.text

    run = client.post("/api/simulation/run", json={
        "animal_count": 1, "anchor_count": 4, "duration_s": 60,
        "sample_period_s": 60, "seed": 4,
    })
    assert run.status_code == 200, run.text
    response = client.post("/api/experiments/virtual-fence", json={"zones": [{
        "zone_id": "whole-farm", "kind": "FORBIDDEN_ZONE",
        "polygon": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]],
    }]})

    assert response.status_code == 200, response.text
    assert response.json()["events"]
    animal = client.get("/api/animals/heifer-west").json()
    assert any(event["event_type"] == "VIRTUAL_FENCE_SIMULATED"
               for event in animal["events"])
    assert client.get("/api/animals/cow-0001").status_code == 404
