import hashlib
import re

import pytest
from fastapi.testclient import TestClient

from riose.products.livestock_tracking.adapters.api import create_app
from riose.products.livestock_tracking.adapters.persistence import Store
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


def test_upstream_site_and_mvp3_dashboard_routes_remain_available(tmp_path):
    with TestClient(create_app(tmp_path / "site.sqlite3")) as client:
        landing = client.get("/", headers={"accept-encoding": "gzip"})
        manifesto = client.get("/manifesto")
        dashboard = client.get("/demo")
        asset = client.get("/assets/landing.css")
        farm_bundle = client.get("/assets/digital-twin/farm.js")
        farm_styles = client.get("/assets/digital-twin/farm.css")
        chunk_names = re.findall(r'from"(\./chunk-[^"]+\.js)"', farm_bundle.text)
        chunks = [client.get(f"/assets/digital-twin/{name[2:]}") for name in chunk_names]

    assert landing.status_code == 200
    assert "RIOSE — Livestock technology" in landing.text
    assert landing.headers.get("content-encoding") == "gzip"
    assert manifesto.status_code == 200
    assert "RIOSE" in manifesto.text
    assert dashboard.status_code == 200
    assert 'id="root"' in dashboard.text
    assert "/assets/digital-twin/farm.js" in dashboard.text
    assert "farm-map.webp" not in dashboard.text
    assert farm_bundle.status_code == 200
    assert "/ws/farm" in farm_bundle.text
    assert chunk_names
    assert all(chunk.status_code == 200 for chunk in chunks)
    assert farm_styles.status_code == 200
    assert asset.status_code == 200
    assert "--" in asset.text
