import hashlib

import pytest
from fastapi.testclient import TestClient

from riose.products.livestock_tracking.adapters.api import create_app
from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.domain.contracts import Anchor
from riose.products.livestock_tracking.domain.identity import (
    EVENT_CONTRACT_V1,
    GENESIS_HASH,
    canonical_event,
    event_digest,
)


VECTOR_BYTES = (
    b'{"animal_id":"cow-\xcf\x80","event_type":"WEIGHT_RECORDED",'
    b'"payload":{"a":[true,null,1.25],"z":"quote:\\"/snowman:'
    b'\xe2\x98\x83"},"previous_hash":"' + GENESIS_HASH.encode("ascii") +
    b'","timestamp":12.5}'
)
VECTOR_SHA256 = "6acfbf7db10fde03c9779925db291056a55086b3549dbf05030b2be60cb58dd8"


def test_event_v1_historical_bytes_are_unchanged_and_version_is_external():
    payload = {"z": 'quote:"/snowman:☃', "a": [True, None, 1.25]}
    assert canonical_event("cow-π", "WEIGHT_RECORDED", 12.5, payload, GENESIS_HASH) == VECTOR_BYTES
    assert event_digest("cow-π", "WEIGHT_RECORDED", 12.5, payload, GENESIS_HASH) == VECTOR_SHA256
    assert event_digest("cow-π", "WEIGHT_RECORDED", 12.5, payload, GENESIS_HASH,
                        schema_version=EVENT_CONTRACT_V1) == VECTOR_SHA256
    assert hashlib.sha256(VECTOR_BYTES).hexdigest() == VECTOR_SHA256


@pytest.mark.parametrize("payload", [
    {"n": float("nan")}, {"n": float("inf")}, {1: "non-string key"}, {"tuple": (1, 2)},
])
def test_v1_rejects_values_that_cannot_round_trip_as_json(payload):
    with pytest.raises(ValueError):
        canonical_event("cow", "WEIGHT_RECORDED", 1.0, payload, GENESIS_HASH)


def test_v1_rejects_unknown_schema_version():
    with pytest.raises(ValueError, match="schema_version"):
        canonical_event("cow", "WEIGHT_RECORDED", 1.0, {}, GENESIS_HASH, schema_version="v99")


def test_v1_rejects_circular_payload_and_boolean_timestamp():
    payload = {}
    payload["self"] = payload
    with pytest.raises(ValueError, match="JSON-compatible"):
        canonical_event("cow", "WEIGHT_RECORDED", 1.0, payload, GENESIS_HASH)
    with pytest.raises(ValueError, match="timestamp"):
        canonical_event("cow", "WEIGHT_RECORDED", True, {}, GENESIS_HASH)


def test_legacy_sqlite_events_migrate_without_changing_hashes(tmp_path):
    db = tmp_path / "legacy.sqlite3"
    legacy = Store(db)
    legacy.create_animal("cow-1", "tag-1", "crypto-1")
    event = legacy.append_animal_event("cow-1", "WEIGHT_RECORDED", {"weight": 10}, 12.5)
    digest = event.hash
    legacy.close()

    migrated = Store(db)
    row = migrated.connection.execute(
        "SELECT hash,schema_version FROM animal_events WHERE event_id=?", (event.event_id,)
    ).fetchone()
    assert row["hash"] == digest
    assert row["schema_version"] == EVENT_CONTRACT_V1
    assert migrated.verify_animal_chain("cow-1")
    migrated.close()


def test_local_event_round_trip_survives_close_reopen(tmp_path):
    db = tmp_path / "local-event.sqlite3"
    store = Store(db)
    store.create_animal("cow-1", "tag-1", "crypto-1")
    event = store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"weight_kg": 420}, 12.5)
    store.close()

    reopened = Store(db)
    try:
        saved = reopened.events(limit=1)[0]
        assert saved["event_id"] == event.event_id
        assert saved["payload"] == {"weight_kg": 420}
        assert reopened.get_animal("cow-1")["hardware_id"] == "tag-1"
        assert reopened.verify_animal_chain("cow-1")
    finally:
        reopened.close()


def test_api_restores_saved_anchors_after_restart(tmp_path):
    db = tmp_path / "anchors.sqlite3"
    store = Store(db)
    store.save_anchors([Anchor("anchor-1", 10.0, 20.0)])
    store.close()

    with TestClient(create_app(db)) as client:
        response = client.get("/api/anchors")

    assert response.status_code == 200
    assert response.json() == [{
        "anchor_id": "anchor-1", "x": 10.0, "y": 20.0,
        "height_m": 3.0, "kind": "esp32-c6-subghz", "enabled": True,
    }]
