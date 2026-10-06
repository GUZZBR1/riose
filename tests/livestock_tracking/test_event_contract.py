"""Frozen Event Contract V1 vectors and legacy SQLite compatibility checks."""

import hashlib
import sqlite3

import pytest

from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.domain.identity import (
    EVENT_CONTRACT_V1,
    append_event,
    canonical_event,
    event_digest,
    verify_event_chain,
)


GENESIS = "0" * 64
VECTOR_BYTES = (
    b'{"animal_id":"cow-\xcf\x80","event_type":"WEIGHT_RECORDED",'
    b'"payload":{"a":[true,null,1.25],"z":"quote:\\"/snowman:'
    b'\xe2\x98\x83"},"previous_hash":"' + GENESIS.encode("ascii") +
    b'","timestamp":12.5}'
)
VECTOR_SHA256 = "6acfbf7db10fde03c9779925db291056a55086b3549dbf05030b2be60cb58dd8"


def test_frozen_v1_vector_bytes_and_digest_are_exact():
    payload = {"z": 'quote:"/snowman:☃', "a": [True, None, 1.25]}

    assert canonical_event("cow-π", "WEIGHT_RECORDED", 12.5, payload, GENESIS) == VECTOR_BYTES
    assert event_digest("cow-π", "WEIGHT_RECORDED", 12.5, payload, GENESIS) == VECTOR_SHA256
    assert hashlib.sha256(VECTOR_BYTES).hexdigest() == VECTOR_SHA256


def test_nested_key_order_is_canonical_and_version_is_not_hashed():
    left = {"outer": {"z": 2, "a": 1}, "list": [{"b": 2, "a": 1}]}
    right = {"list": [{"a": 1, "b": 2}], "outer": {"a": 1, "z": 2}}

    assert canonical_event("cow", "WEIGHT_RECORDED", 1, left, GENESIS) == canonical_event(
        "cow", "WEIGHT_RECORDED", 1, right, GENESIS, schema_version=EVENT_CONTRACT_V1
    )
    with pytest.raises(ValueError, match="schema_version"):
        canonical_event("cow", "WEIGHT_RECORDED", 1, {}, GENESIS, schema_version="v99")


@pytest.mark.parametrize("payload", [
    {"n": float("nan")}, {"n": float("inf")}, {"n": -float("inf")},
    {1: "coerced key"}, {"tuple": (1, 2)},
])
def test_non_json_or_non_finite_payloads_are_rejected_before_write(tmp_path, payload):
    store = Store(tmp_path / "invalid.sqlite3")
    store.create_animal("cow-1", "tag-1", "crypto-1")
    before = store.connection.execute("SELECT COUNT(*) FROM animal_events").fetchone()[0]

    with pytest.raises(ValueError):
        append_event(store.connection, "cow-1", "WEIGHT_RECORDED", payload, 1.0)

    assert store.connection.execute("SELECT COUNT(*) FROM animal_events").fetchone()[0] == before
    assert store.verify_animal_chain("cow-1")
    store.close()


@pytest.mark.parametrize("field,value", [
    ("event_type", "TRANSFER"),
    ("timestamp", 13.5),
    ("payload", '{"a":[true,null,1.25],"z":"different"}'),
    ("previous_hash", "f" * 64),
    ("hash", "f" * 64),
])
def test_each_hashed_field_is_checked_by_verifier(tmp_path, field, value):
    store = Store(tmp_path / f"tamper-{field}.sqlite3")
    store.create_animal("cow-1", "tag-1", "crypto-1")
    event = store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"weight": 10}, 12.5)
    store.connection.execute(f"UPDATE animal_events SET {field}=? WHERE event_id=?", (value, event.event_id))
    store.connection.commit()
    assert not store.verify_animal_chain("cow-1")
    store.close()


def test_animal_id_participates_in_digest_and_signature_does_not(tmp_path):
    store = Store(tmp_path / "animal-id.sqlite3")
    store.create_animal("cow-1", "tag-1", "crypto-1")
    store.connection.execute("INSERT INTO animals(animal_id,hardware_id,cryptographic_id,created_at) VALUES('cow-2','tag-2','crypto-2',1)")
    event = store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"weight": 10}, 12.5)
    store.connection.execute("UPDATE animal_events SET animal_id='cow-2' WHERE event_id=?", (event.event_id,))
    store.connection.commit()
    assert not store.verify_animal_chain("cow-2")
    store.connection.execute("UPDATE animal_events SET animal_id='cow-1',signature='unverified' WHERE event_id=?", (event.event_id,))
    store.connection.commit()
    assert store.verify_animal_chain("cow-1")
    store.connection.execute("UPDATE animal_events SET event_id=event_id+100 WHERE event_id=?", (event.event_id,))
    store.connection.commit()
    assert store.verify_animal_chain("cow-1")
    store.close()


def test_unknown_persisted_version_fails_closed(tmp_path):
    store = Store(tmp_path / "unknown-version.sqlite3")
    store.create_animal("cow-1", "tag-1", "crypto-1")
    store.connection.execute("UPDATE animal_events SET schema_version='v99'")
    store.connection.commit()
    assert not store.verify_animal_chain("cow-1")
    store.close()


def test_verifier_rejects_nonstandard_json_constants(tmp_path):
    store = Store(tmp_path / "invalid-json.sqlite3")
    store.create_animal("cow-1", "tag-1", "crypto-1")
    store.connection.execute("UPDATE animal_events SET payload=?", ('{"n":NaN}',))
    store.connection.commit()
    assert not store.verify_animal_chain("cow-1")
    store.close()


def test_verifier_detects_deleted_middle_event_but_local_chain_cannot_prove_tail_completeness(tmp_path):
    store = Store(tmp_path / "missing-events.sqlite3")
    store.create_animal("cow-1", "tag-1", "crypto-1")
    first = store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"n": 1}, 1.0)
    middle = store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"n": 2}, 2.0)
    tail = store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"n": 3}, 3.0)

    store.connection.execute("DELETE FROM animal_events WHERE event_id=?", (middle.event_id,))
    store.connection.commit()
    assert not store.verify_animal_chain("cow-1")

    store.connection.execute("DELETE FROM animal_events WHERE event_id=?", (tail.event_id,))
    store.connection.commit()
    assert store.verify_animal_chain("cow-1")
    assert first.hash != tail.hash
    store.close()


def test_verifier_rejects_reordered_events(tmp_path):
    store = Store(tmp_path / "reordered-events.sqlite3")
    store.create_animal("cow-1", "tag-1", "crypto-1")
    first = store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"n": 1}, 1.0)
    second = store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"n": 2}, 2.0)
    store.connection.execute("UPDATE animal_events SET event_id=1000 WHERE event_id=?", (first.event_id,))
    store.connection.execute("UPDATE animal_events SET event_id=? WHERE event_id=?", (first.event_id, second.event_id))
    store.connection.execute("UPDATE animal_events SET event_id=? WHERE event_id=1000", (second.event_id,))
    store.connection.commit()
    assert not store.verify_animal_chain("cow-1")
    store.close()


def test_event_order_uses_event_id_for_equal_and_out_of_order_timestamps(tmp_path):
    store = Store(tmp_path / "timestamp-order.sqlite3")
    store.create_animal("cow-1", "tag-1", "crypto-1")
    earlier_id = store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"n": 1}, 20.0)
    equal_time_id = store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"n": 2}, 20.0)
    out_of_order_id = store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"n": 3}, 10.0)

    rows = store.connection.execute(
        "SELECT event_id,timestamp,previous_hash,hash FROM animal_events "
        "WHERE animal_id='cow-1' ORDER BY event_id"
    ).fetchall()
    assert [row[0] for row in rows] == [1, earlier_id.event_id, equal_time_id.event_id, out_of_order_id.event_id]
    assert [row[1] for row in rows[1:]] == [20.0, 20.0, 10.0]
    assert [row[2] for row in rows[1:]] == [rows[0][3], rows[1][3], rows[2][3]]
    assert store.verify_animal_chain("cow-1")
    store.close()


def test_writer_refuses_to_extend_an_already_invalid_chain(tmp_path):
    store = Store(tmp_path / "invalid-head.sqlite3")
    store.create_animal("cow-1", "tag-1", "crypto-1")
    event = store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"n": 1}, 1.0)
    store.connection.execute(
        "UPDATE animal_events SET payload='{}' WHERE event_id=?", (event.event_id,)
    )
    store.connection.commit()
    before = store.connection.execute("SELECT COUNT(*) FROM animal_events").fetchone()[0]

    with pytest.raises(ValueError, match="invalid event chain"):
        store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"n": 2}, 2.0)

    assert store.connection.execute("SELECT COUNT(*) FROM animal_events").fetchone()[0] == before
    assert not store.connection.in_transaction
    assert not store.verify_animal_chain("cow-1")
    store.close()


def test_legacy_sqlite_hash_remains_verifiable_without_rehash(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE animals (animal_id TEXT PRIMARY KEY, hardware_id TEXT NOT NULL UNIQUE,
          cryptographic_id TEXT NOT NULL UNIQUE, created_at REAL NOT NULL);
        CREATE TABLE animal_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT,
          animal_id TEXT NOT NULL, event_type TEXT NOT NULL, timestamp REAL NOT NULL,
          payload TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL, signature TEXT);
    """)
    connection.execute("INSERT INTO animals VALUES(?,?,?,?)", ("cow-π", "tag-1", "crypto-1", 1))
    connection.execute(
        "INSERT INTO animal_events(animal_id,event_type,timestamp,payload,previous_hash,hash,signature) VALUES(?,?,?,?,?,?,NULL)",
        ("cow-π", "WEIGHT_RECORDED", 12.5,
         r'{"a":[true,null,1.25],"z":"quote:\"/snowman:☃"}',
         GENESIS, VECTOR_SHA256),
    )
    connection.commit()
    assert verify_event_chain(connection, "cow-π")
    connection.close()

    store = Store(path)
    row = store.connection.execute("SELECT hash,schema_version FROM animal_events").fetchone()
    assert row["hash"] == VECTOR_SHA256
    assert row["schema_version"] is None
    assert store.verify_animal_chain("cow-π")
    appended = store.append_animal_event("cow-π", "VACCINATION", {"vaccine": "v1"}, 13.0)
    assert appended.previous_hash == VECTOR_SHA256
    assert store.connection.execute(
        "SELECT schema_version FROM animal_events WHERE event_id=?", (appended.event_id,)
    ).fetchone()[0] == EVENT_CONTRACT_V1
    assert store.verify_animal_chain("cow-π")
    assert "schema_version" not in store.events()[0]
    store.close()
