import sqlite3

import pytest
from fastapi.testclient import TestClient

from cattle_rf.api import create_app
from cattle_rf.db import Store
from cattle_rf.identity import append_event, verify_event_chain


def test_animal_creation_is_atomic_and_chain_is_verifiable(tmp_path):
    store = Store(tmp_path / "animals.sqlite3")
    animal = store.create_animal("cow-1", "ear-1", "a" * 64, weight_kg=420)
    assert animal["animal_id"] == "cow-1"
    assert len(animal["events"]) == 1
    assert store.verify_animal_chain("cow-1")

    with pytest.raises(sqlite3.IntegrityError):
        store.create_animal("cow-2", "ear-1", "b" * 64)
    assert store.get_animal("cow-2") is None
    store.close()


def test_hash_chain_detects_payload_and_link_tampering(tmp_path):
    store = Store(tmp_path / "chain.sqlite3")
    store.create_animal("cow-1", "ear-1", "a" * 64)
    store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"weight_kg": 411.5}, 100.0)
    assert store.verify_animal_chain("cow-1")

    store.connection.execute("UPDATE animal_events SET payload='{}' WHERE event_type='WEIGHT_RECORDED'")
    store.connection.commit()
    assert not store.verify_animal_chain("cow-1")
    store.close()


@pytest.mark.parametrize("event_type,payload,timestamp", [
    ("NOPE", {}, 1), ("WEIGHT_RECORDED", {"n": float("nan")}, 1),
    ("WEIGHT_RECORDED", [], 1), ("WEIGHT_RECORDED", {}, float("inf")),
])
def test_event_writer_rejects_invalid_data(tmp_path, event_type, payload, timestamp):
    store = Store(tmp_path / "bad-events.sqlite3")
    store.create_animal("cow-1", "ear-1", "a" * 64)
    with pytest.raises(ValueError):
        append_event(store.connection, "cow-1", event_type, payload, timestamp)
    assert store.verify_animal_chain("cow-1")
    store.close()


def test_api_validates_animal_event_and_keeps_truth_debug_only(tmp_path):
    app = create_app(tmp_path / "api.sqlite3")
    client = TestClient(app)
    created = client.post("/api/animals", json={
        "animal_id": "cow-1", "hardware_id": "ear-1", "birth_date": "2024-02-29",
        "weight_kg": 400.0,
    })
    assert created.status_code == 201
    assert client.post("/api/animals", json={
        "animal_id": "cow-2", "hardware_id": "ear-2", "birth_date": "2023-02-29",
    }).status_code == 422
    assert client.post("/api/animals", json={
        "animal_id": "cow-3", "hardware_id": "ear-3", "weight_kg": -2,
    }).status_code == 422
    assert client.post("/api/animals", json={
        "animal_id": "cow-1", "hardware_id": "ear-duplicate",
    }).status_code == 409

    event = client.post("/api/events", json={
        "animal_id": "cow-1", "event_type": "VACCINATION", "payload": {"product": "vax"},
        "timestamp": 1000,
    })
    assert event.status_code == 201
    assert event.json()["chain_valid"] is True
    assert client.get("/api/animals/cow-1/events/verify").json()["valid"] is True
    assert client.post("/api/events", json={
        "animal_id": "cow-1", "event_type": "EXECUTE_SQL", "payload": {},
    }).status_code == 422

    app.state.store.connection.execute(
        "INSERT INTO positions(timestamp,tag_id,x,y,method,quality,status) VALUES(1,'ear-1',10,20,'test',1,'SIMULATED')")
    app.state.store.connection.execute(
        "INSERT INTO debug_truth(timestamp,tag_id,x,y) VALUES(1,'ear-1',12,24)")
    app.state.store.connection.commit()
    normal = client.get("/api/positions").json()[0]
    debug = client.get("/api/positions?debug=true").json()[0]
    assert "ground_truth_x" not in normal
    assert debug["ground_truth_x"] == 12
    assert debug["ground_truth_y"] == 24
    trajectory = client.get("/api/animals/cow-1/trajectory").json()
    assert len(trajectory) == 1
    assert "ground_truth_x" not in trajectory[0]
    assert client.get("/api/animals/missing/trajectory").status_code == 404
    app.state.store.close()
