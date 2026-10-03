import sqlite3

import pytest
from fastapi.testclient import TestClient

from riose.products.livestock_tracking.adapters.api import create_app
from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.domain.behavior import BehaviorObservation
from riose.products.livestock_tracking.domain.contracts import EvidenceStatus


def registered_store(path):
    store = Store(path)
    store.create_animal("cow-1", "tag-1", "crypto-1")
    store.create_animal("cow-2", "tag-2", "crypto-2")
    return store


def observation(**overrides):
    values = dict(
        animal_id="cow-1", timestamp_s=100.0, behavior="GRAZE", confidence=0.731,
        model_version="behavior-v0.1", source="fixture.synthetic-v1",
        observation_kind="PREDICTION", evidence_status=EvidenceStatus.SIMULATED,
        idempotency_key="fixture-cow1-100",
    )
    values.update(overrides)
    return BehaviorObservation(**values)


def test_round_trip_history_restart_and_idempotency(tmp_path):
    db = tmp_path / "behavior.sqlite3"
    store = registered_store(db)
    saved, created = store.save_behavior_observation(observation())
    retry, retry_created = store.save_behavior_observation(observation())
    assert created is True
    assert retry_created is False
    assert retry == saved
    # Same timestamp is legitimate for a different behavior/model/key.
    store.save_behavior_observation(observation(
        behavior="REST", model_version="behavior-v0.2", idempotency_key="second-event"
    ))
    store.save_behavior_observation(observation(
        animal_id="cow-2", idempotency_key="other-animal"
    ))
    store.save_behavior_observation(observation(
        timestamp_s=50.0, behavior="WALK", idempotency_key="out-of-order"
    ))
    store.close()

    reopened = Store(db)
    history = reopened.behavior_history("cow-1")
    assert [row["behavior"] for row in history] == ["WALK", "GRAZE", "REST"]
    assert history[1]["confidence"] == pytest.approx(0.731)
    assert history[1]["model_version"] == "behavior-v0.1"
    assert history[1]["source"] == "fixture.synthetic-v1"
    assert history[1]["evidence_status"] == "SIMULATED"
    assert history[1]["observation_kind"] == "PREDICTION"
    assert history[1]["persisted_at"] >= 0
    assert reopened.behavior_history("cow-1", start_s=100, end_s=100, limit=1)[0]["behavior"] == "GRAZE"
    assert [row["behavior"] for row in reopened.behavior_history(
        "cow-1", behavior="GRAZE", model_version="behavior-v0.1"
    )] == ["GRAZE"]
    assert len(reopened.behavior_history("cow-1", offset=1, limit=1)) == 1
    assert all(row["animal_id"] == "cow-1" for row in history)
    with pytest.raises(ValueError, match="idempotency_key"):
        reopened.save_behavior_observation(observation(behavior="REST"))
    reopened.close()


def test_validation_and_existing_animal_foreign_key(tmp_path):
    store = registered_store(tmp_path / "invalid.sqlite3")
    for bad in (
        {"timestamp_s": float("nan")}, {"timestamp_s": -1},
        {"behavior": ""}, {"confidence": 1.01}, {"confidence": -0.01},
        {"source": ""},
        {"end_timestamp_s": 99}, {"model_version": None},
        {"evidence_status": "SIMULATED"},
    ):
        with pytest.raises((ValueError, TypeError)):
            observation(**bad)
    with pytest.raises(sqlite3.IntegrityError):
        store.save_behavior_observation(observation(animal_id="missing"))
    assert store.behavior_history("cow-1") == []
    store.close()


def test_additive_migration_preserves_legacy_rows_and_reopens(tmp_path):
    db = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(db)
    connection.executescript("""
        CREATE TABLE animals (
          animal_id TEXT PRIMARY KEY, hardware_id TEXT NOT NULL UNIQUE,
          cryptographic_id TEXT NOT NULL UNIQUE, name TEXT, sex TEXT, breed TEXT,
          birth_date TEXT, weight_kg REAL, property_name TEXT, lot TEXT, created_at REAL NOT NULL
        );
        CREATE TABLE animal_events (
          event_id INTEGER PRIMARY KEY AUTOINCREMENT, animal_id TEXT NOT NULL,
          event_type TEXT NOT NULL, timestamp REAL NOT NULL, payload TEXT NOT NULL,
          previous_hash TEXT NOT NULL, hash TEXT NOT NULL, signature TEXT
        );
        INSERT INTO animals(animal_id,hardware_id,cryptographic_id,created_at)
          VALUES('legacy-cow','legacy-tag','legacy-crypto',1.0);
        INSERT INTO animal_events(animal_id,event_type,timestamp,payload,previous_hash,hash)
          VALUES('legacy-cow','ANIMAL_CREATED',1,'{}','0','legacy-hash');
    """)
    connection.commit()
    connection.close()

    store = Store(db)
    assert store.connection.execute("SELECT COUNT(*) FROM animal_events").fetchone()[0] == 1
    assert "schema_version" in {
        row[1] for row in store.connection.execute("PRAGMA table_info(animal_events)")
    }
    migrated = BehaviorObservation(
        animal_id="legacy-cow", timestamp_s=2, behavior="REST", confidence=None,
        model_version=None, source="manual.review", observation_kind="MANUAL_ANNOTATION",
        evidence_status=EvidenceStatus.EXPERIMENTAL, idempotency_key="legacy-note",
    )
    store.save_behavior_observation(migrated)
    store.close()
    reopened = Store(db)
    assert reopened.behavior_history("legacy-cow")[0]["evidence_status"] == "EXPERIMENTAL"
    assert reopened.connection.execute("SELECT COUNT(*) FROM animal_events").fetchone()[0] == 1
    reopened.close()


def test_api_keeps_simulated_status_and_filters_history(tmp_path):
    client = TestClient(create_app(tmp_path / "api.sqlite3"))
    created = client.post("/api/animals", json={
        "animal_id": "cow-1", "hardware_id": "tag-1", "name": "Cow"
    })
    assert created.status_code == 201
    payload = {
        "animal_id": "cow-1", "timestamp_s": 5, "behavior": "WALK",
        "confidence": 0.5, "model_version": "m1", "source": "synthetic.fixture",
        "observation_kind": "PREDICTION", "evidence_status": "SIMULATED",
        "idempotency_key": "api-event-1",
    }
    assert client.post("/api/animals/cow-1/behaviors", json=payload).status_code == 201
    assert client.post("/api/animals/cow-1/behaviors", json=payload).status_code == 200
    assert client.get("/api/animals/cow-1/behaviors", params={
        "evidence_status": "SIMULATED", "source": "synthetic.fixture"
    }).json()[0]["evidence_status"] == "SIMULATED"
    assert client.get("/api/animals/cow-1/behaviors", params={
        "model_version": "m1"
    }).json()[0]["model_version"] == "m1"
    assert client.post("/api/animals/cow-2/behaviors", json=payload).status_code == 422
    invalid = {**payload, "idempotency_key": "bad-confidence", "confidence": 1.2}
    assert client.post("/api/animals/cow-1/behaviors", json=invalid).status_code == 422
    boolean_confidence = {**payload, "idempotency_key": "bool-confidence", "confidence": True}
    assert client.post("/api/animals/cow-1/behaviors", json=boolean_confidence).status_code == 422
    missing_model = {**payload, "idempotency_key": "no-model", "model_version": None}
    assert client.post("/api/animals/cow-1/behaviors", json=missing_model).status_code == 422
    assert client.get("/api/animals/cow-1/behaviors", params={
        "source": "' OR 1=1 --"
    }).json() == []
    assert client.get("/api/animals/missing/behaviors").status_code == 404
