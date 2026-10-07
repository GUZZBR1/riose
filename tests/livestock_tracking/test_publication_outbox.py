import sqlite3

import pytest

from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.adapters.persistence.publication_outbox import SQLitePublicationOutbox
from riose.products.livestock_tracking.domain.publication_state import PublicationState


def _store(path):
    store = Store(path)
    store.create_animal("cow-1", "tag-1", "crypto-1")
    event = store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"weight_kg": 421}, 10.0)
    return store, event


def test_queue_is_atomic_minimal_and_idempotent_across_restart(tmp_path):
    path = tmp_path / "publish.sqlite3"
    store, event = _store(path)
    outbox = SQLitePublicationOutbox(store)
    first = outbox.enqueue_event(event.event_id, destination="solana-memo", network="solana-devnet:genesis", now=12)
    again = outbox.enqueue_event(event.event_id, destination="solana-memo", network="solana-devnet:genesis", now=99)
    assert first["publication_id"] == again["publication_id"]
    assert first["subject_ref"] == again["subject_ref"]
    assert first["status"] == "QUEUED"
    assert outbox.verify_local_binding(first["publication_id"])
    assert len(outbox.list_pending()) == 1
    assert first["subject_ref"].encode() not in first["envelope"]
    store.close()

    reopened = Store(path)
    restarted = SQLitePublicationOutbox(reopened).get(first["publication_id"])
    assert restarted["subject_ref"] == first["subject_ref"]
    assert restarted["envelope"] == first["envelope"]
    reopened.close()


def test_queue_rolls_back_request_when_outbox_insert_fails(tmp_path):
    store, event = _store(tmp_path / "rollback.sqlite3")
    outbox = SQLitePublicationOutbox(store)
    store.connection.execute("CREATE TRIGGER reject_outbox BEFORE INSERT ON publication_outbox BEGIN SELECT RAISE(ABORT,'injected failure'); END")
    store.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        outbox.enqueue_event(event.event_id, destination="solana-memo", network="solana-devnet:genesis", now=12)
    assert store.connection.execute("SELECT COUNT(*) FROM publication_requests").fetchone()[0] == 0
    assert store.connection.execute("SELECT COUNT(*) FROM publication_outbox").fetchone()[0] == 0
    store.close()


def test_domain_event_and_publication_intent_commit_or_rollback_together(tmp_path):
    store = Store(tmp_path / "domain-atomic.sqlite3")
    store.create_animal("cow-1", "tag-1", "crypto-1")
    outbox = SQLitePublicationOutbox(store)
    before = store.connection.execute("SELECT COUNT(*) FROM animal_events").fetchone()[0]
    request = outbox.append_event_and_enqueue(
        "cow-1", "WEIGHT_RECORDED", {"weight_kg": 422}, destination="solana-memo",
        network="solana-devnet:genesis", idempotency_key="event-once", timestamp=20, now=21,
    )
    repeated = outbox.append_event_and_enqueue(
        "cow-1", "WEIGHT_RECORDED", {"weight_kg": 422}, destination="solana-memo",
        network="solana-devnet:genesis", idempotency_key="event-once", timestamp=20, now=99,
    )
    assert repeated["publication_id"] == request["publication_id"]
    assert store.connection.execute("SELECT COUNT(*) FROM animal_events").fetchone()[0] == before + 1
    assert store.connection.execute("SELECT COUNT(*) FROM publication_outbox").fetchone()[0] == 1
    with pytest.raises(ValueError, match="different publication request"):
        outbox.append_event_and_enqueue(
            "cow-1", "WEIGHT_RECORDED", {"weight_kg": 423}, destination="solana-memo",
            network="solana-devnet:genesis", idempotency_key="event-once", timestamp=20, now=22,
        )
    assert store.connection.execute("SELECT COUNT(*) FROM animal_events").fetchone()[0] == before + 1
    store.close()


def test_atomic_domain_write_rolls_back_when_publication_intent_cannot_persist(tmp_path):
    store = Store(tmp_path / "domain-rollback.sqlite3")
    store.create_animal("cow-1", "tag-1", "crypto-1")
    outbox = SQLitePublicationOutbox(store)
    before = store.connection.execute("SELECT COUNT(*) FROM animal_events").fetchone()[0]
    store.connection.execute("CREATE TRIGGER reject_outbox BEFORE INSERT ON publication_outbox BEGIN SELECT RAISE(ABORT,'injected failure'); END")
    store.connection.commit()
    with pytest.raises(sqlite3.IntegrityError):
        outbox.append_event_and_enqueue(
            "cow-1", "WEIGHT_RECORDED", {"weight_kg": 422}, destination="solana-memo",
            network="solana-devnet:genesis", idempotency_key="atomic-fail", timestamp=20, now=21,
        )
    assert store.connection.execute("SELECT COUNT(*) FROM animal_events").fetchone()[0] == before
    assert store.connection.execute("SELECT COUNT(*) FROM publication_requests").fetchone()[0] == 0
    assert store.connection.execute("SELECT COUNT(*) FROM publication_outbox").fetchone()[0] == 0
    store.close()


def test_event_prefix_binding_survives_later_events_and_fails_on_tampering(tmp_path):
    store, event = _store(tmp_path / "prefix.sqlite3")
    outbox = SQLitePublicationOutbox(store)
    request = outbox.enqueue_event(event.event_id, destination="solana-memo", network="solana-devnet:genesis")
    store.append_animal_event("cow-1", "VACCINATION", {"vaccine": "v1"}, 11.0)
    assert outbox.verify_local_binding(request["publication_id"])
    store.connection.execute("UPDATE animal_events SET payload='{}' WHERE event_id=?", (event.event_id,))
    store.connection.commit()
    assert not outbox.verify_local_binding(request["publication_id"])
    store.close()


def test_signed_attempt_is_durable_and_cannot_be_duplicated(tmp_path):
    path = tmp_path / "attempt.sqlite3"
    store, event = _store(path)
    outbox = SQLitePublicationOutbox(store)
    request = outbox.enqueue_event(event.event_id, destination="solana-memo", network="solana-devnet:genesis")
    attempt = outbox.prepare_attempt(request["publication_id"], signature="1" * 64,
                                     signed_transaction=b"signed-wire", last_valid_block_height=500)
    assert attempt["signature"] == "1" * 64
    assert attempt["signed_transaction"] == b"signed-wire"
    with pytest.raises(ValueError, match="transition"):
        outbox.prepare_attempt(request["publication_id"], signature="1" * 64,
                               signed_transaction=b"second", last_valid_block_height=500)
    store.close()
    reopened = Store(path)
    retry = SQLitePublicationOutbox(reopened).latest_attempt(request["publication_id"])
    assert retry["signature"] == "1" * 64
    assert retry["signed_transaction"] == b"signed-wire"
    reopened.close()


def test_receipts_are_correlated_append_only_and_states_fail_closed(tmp_path):
    store, event = _store(tmp_path / "receipts.sqlite3")
    outbox = SQLitePublicationOutbox(store)
    request = outbox.enqueue_event(event.event_id, destination="solana-memo", network="solana-devnet:genesis")
    attempt = outbox.prepare_attempt(request["publication_id"], signature="1" * 64,
                                     signed_transaction=b"signed", last_valid_block_height=50)
    outbox.record_observation(request["publication_id"], attempt["attempt_id"], state=PublicationState.RPC_ACCEPTED,
                              now=19)
    outbox.record_observation(request["publication_id"], attempt["attempt_id"], state=PublicationState.UNKNOWN,
                              reason_code="RPC_UNAVAILABLE", now=20)
    outbox.record_observation(request["publication_id"], attempt["attempt_id"], state=PublicationState.CONFIRMED,
                              slot=42, now=21)
    outbox.record_observation(request["publication_id"], attempt["attempt_id"], state=PublicationState.VERIFIED,
                              slot=42, now=22)
    receipts = outbox.receipts(request["publication_id"])
    assert [row["state"] for row in receipts] == ["RPC_ACCEPTED", "UNKNOWN", "CONFIRMED", "VERIFIED"]
    assert {row["attempt_id"] for row in receipts} == {attempt["attempt_id"]}
    assert {row["signature"] for row in receipts} == {"1" * 64}
    assert {row["receipt_version"] for row in receipts} == {1}
    assert {row["adapter_id"] for row in receipts} == {"solana-memo"}
    assert {row["commitment"] for row in receipts} == {request["commitment"]}
    assert {row["network"] for row in receipts} == {request["network"]}
    assert {row["submitted_at"] for row in receipts} == {19.0}
    assert receipts[-1]["verified_at"] == 22.0
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.connection.execute("DELETE FROM publication_receipts")
    store.connection.rollback()
    with pytest.raises(ValueError, match="transition"):
        outbox.record_observation(request["publication_id"], attempt["attempt_id"], state=PublicationState.QUEUED)
    assert outbox.get(request["publication_id"])["status"] == "VERIFIED"
    store.close()


def test_invalid_event_and_network_inputs_are_rejected(tmp_path):
    store, event = _store(tmp_path / "invalid.sqlite3")
    outbox = SQLitePublicationOutbox(store)
    with pytest.raises(ValueError, match="network"):
        outbox.enqueue_event(event.event_id, destination="solana-memo", network="bad value")
    with pytest.raises(ValueError, match="event_id"):
        outbox.enqueue_event(0, destination="solana-memo", network="solana-devnet:genesis")
    store.close()
