from fastapi.testclient import TestClient

from cattle_rf.api import create_app


def test_dashboard_explicit_anchors_and_debug_only_truth(tmp_path):
    app = create_app(tmp_path / "dashboard.sqlite3")
    client = TestClient(app)
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


def test_simulation_rejects_duplicate_or_outside_farm_anchors(tmp_path):
    client = TestClient(create_app(tmp_path / "invalid.sqlite3"))
    common = {"animal_count": 1, "duration_s": 30, "sample_period_s": 30}
    duplicate = [{"anchor_id": "a", "x": 0, "y": 0}] * 2
    response = client.post("/api/simulation/run", json={**common, "anchors": duplicate})
    assert response.status_code == 422
    outside = [{"anchor_id": "a", "x": 1001, "y": 0}]
    response = client.post("/api/simulation/run", json={**common, "anchors": outside})
    assert response.status_code == 422
