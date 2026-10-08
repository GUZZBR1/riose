import sqlite3

import pytest

from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.adapters.persistence.publication_outbox import SQLitePublicationOutbox
from riose.products.livestock_tracking.domain.commitment import create_commitment_v1, public_envelope
from riose.products.livestock_tracking.domain.privacy import serialize_public_envelope
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
    assert again["duplicate_suppressed"] is True
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


def test_one_event_commitment_is_reused_for_multiple_chain_targets(tmp_path):
    store, event = _store(tmp_path / "multi-target.sqlite3")
    outbox = SQLitePublicationOutbox(store)
    solana = outbox.enqueue_event(event.event_id, destination="solana-memo", network="solana-devnet:test")
    base = outbox.enqueue_event(
        event.event_id, chain="base", destination="evm-rpc", network="testnet"
    )
    arbitrum = outbox.enqueue_event(
        event.event_id, chain="arbitrum", destination="evm-rpc", network="testnet"
    )

    assert solana["chain"] == "solana"
    assert base["chain"] == "base"
    assert arbitrum["chain"] == "arbitrum"
    assert base["destination"] == arbitrum["destination"] == "evm-rpc"
    assert base["network"] == arbitrum["network"] == "testnet"
    assert base["target_id"] != arbitrum["target_id"]
    assert base["publication_id"] != arbitrum["publication_id"]
    colon_a = outbox.enqueue_event(
        event.event_id, chain="a-b", destination="c", network="same"
    )
    colon_b = outbox.enqueue_event(
        event.event_id, chain="a", destination="b-c", network="same"
    )
    long_target = outbox.enqueue_event(
        event.event_id, chain="chain", destination="x" * 128, network="same"
    )
    assert colon_a["target_id"] != colon_b["target_id"]
    assert colon_a["idempotency_key"] != colon_b["idempotency_key"]
    assert len(long_target["target_id"]) == 71
    assert solana["commitment"] == base["commitment"]
    assert base["commitment"] == arbitrum["commitment"]
    assert solana["subject_ref"] == base["subject_ref"]
    assert solana["envelope"] == base["envelope"]
    assert store.connection.execute(
        "SELECT COUNT(*) FROM canonical_event_commitments WHERE event_id=?", (event.event_id,)
    ).fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.connection.execute(
            "UPDATE canonical_event_commitments SET commitment=? WHERE event_id=?",
            ("ef" * 32, event.event_id),
        )
    store.connection.rollback()
    assert len(outbox.list_pending()) == 6
    assert {row["status"] for row in outbox.list_pending()} == {"QUEUED"}
    store.close()


def test_legacy_receipt_cannot_migrate_against_another_publications_attempt():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
      CREATE TABLE publication_requests (
        publication_id TEXT PRIMARY KEY,destination TEXT NOT NULL,adapter_id TEXT NOT NULL,
        chain TEXT NOT NULL);
      CREATE TABLE publication_attempts (
        attempt_id TEXT PRIMARY KEY,publication_id TEXT NOT NULL,attempt_number INTEGER NOT NULL,
        signature TEXT NOT NULL,signed_transaction BLOB NOT NULL,last_valid_block_height INTEGER NOT NULL,
        status TEXT NOT NULL,created_at REAL NOT NULL);
      CREATE TABLE publication_receipts (
        receipt_id TEXT PRIMARY KEY,publication_id TEXT NOT NULL,attempt_id TEXT NOT NULL);
      INSERT INTO publication_requests VALUES('pub-a','solana-memo','solana-memo','solana');
      INSERT INTO publication_requests VALUES('pub-b','solana-memo','solana-memo','solana');
      INSERT INTO publication_attempts VALUES('attempt-b','pub-b',1,'sig',x'01',1,'PREPARED',1.0);
      INSERT INTO publication_receipts VALUES('receipt-a','pub-a','attempt-b');
    """)

    with pytest.raises(sqlite3.IntegrityError, match="orphaned attempts or receipts"):
        SQLitePublicationOutbox._migrate_solana_attempts(con, set())

    assert con.execute("SELECT COUNT(*) FROM publication_attempts").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM publication_receipts").fetchone()[0] == 1
    con.close()


def test_legacy_normalized_transaction_id_must_match_solana_signature():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
      CREATE TABLE publication_requests (
        publication_id TEXT PRIMARY KEY,destination TEXT NOT NULL,adapter_id TEXT NOT NULL,
        chain TEXT NOT NULL);
      CREATE TABLE publication_attempts (
        attempt_id TEXT PRIMARY KEY,publication_id TEXT NOT NULL,attempt_number INTEGER NOT NULL,
        signature TEXT NOT NULL,signed_transaction BLOB NOT NULL,last_valid_block_height INTEGER NOT NULL,
        status TEXT NOT NULL,created_at REAL NOT NULL);
      CREATE TABLE publication_receipts (
        receipt_id TEXT PRIMARY KEY,publication_id TEXT NOT NULL,attempt_id TEXT NOT NULL,
        transaction_id TEXT NOT NULL);
      INSERT INTO publication_requests VALUES('pub','solana-memo','solana-memo','solana');
      INSERT INTO publication_attempts VALUES('attempt','pub',1,'signature-a',x'01',1,'PREPARED',1.0);
      INSERT INTO publication_receipts VALUES('receipt','pub','attempt','signature-b');
    """)

    con.execute("BEGIN IMMEDIATE")
    with pytest.raises(sqlite3.IntegrityError, match="does not match its persisted Solana signature"):
        SQLitePublicationOutbox._migrate_solana_attempts(con, {"transaction_id"})
    con.rollback()

    assert con.execute("SELECT COUNT(*) FROM publication_attempts").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM publication_receipts").fetchone()[0] == 1
    con.close()


def test_target_failure_does_not_invalidate_event_or_other_target(tmp_path):
    store, event = _store(tmp_path / "isolated-targets.sqlite3")
    outbox = SQLitePublicationOutbox(store)
    failed = outbox.enqueue_event(event.event_id, destination="solana-memo", network="solana-devnet:test")
    pending = outbox.enqueue_event(
        event.event_id, chain="base", destination="base-rpc", network="base-sepolia"
    )
    attempt = outbox.prepare_attempt(
        failed["publication_id"], signature="1" * 64,
        signed_transaction=b"prepared", last_valid_block_height=5,
    )
    outbox.record_observation(
        failed["publication_id"], attempt["attempt_id"], state=PublicationState.REJECTED,
        reason_code="RPC_REJECTED", error="RPC_REJECTED", retry_metadata={"attempt": 1},
        evidence_status="ASSUMED",
    )

    assert outbox.get(failed["publication_id"])["status"] == "REJECTED"
    assert outbox.get(pending["publication_id"])["status"] == "QUEUED"
    assert outbox.verify_local_binding(failed["publication_id"])
    receipt = outbox.receipts(failed["publication_id"])[0]
    assert receipt["chain"] == "solana"
    assert receipt["transaction_id"] == "1" * 64
    assert receipt["error"] == "RPC_REJECTED"
    assert receipt["retry_metadata_json"] == '{"attempt":1}'
    assert store.verify_animal_chain("cow-1")
    store.close()


def test_generic_attempt_and_receipt_reuse_one_outbox_without_solana_fields(tmp_path):
    store, event = _store(tmp_path / "generic-target.sqlite3")
    outbox = SQLitePublicationOutbox(store)
    request = outbox.enqueue_event(
        event.event_id, chain="base", destination="evm-rpc", network="base-sepolia"
    )
    attempt = outbox.prepare_publication_attempt(
        request["publication_id"], adapter_id="evm-rpc", transaction_id="0x" + "ab" * 32,
        payload=b"x" * 4096, metadata={"nonce": 7}, now=20,
    )
    assert attempt["transaction_id"] == "0x" + "ab" * 32
    assert attempt["payload"] == b"x" * 4096
    assert attempt["metadata"] == {"nonce": 7}
    assert attempt["signature"] is None
    outbox.record_observation(
        request["publication_id"], attempt["attempt_id"], state=PublicationState.RPC_ACCEPTED,
        adapter_id="evm-rpc", now=20.5,
    )
    outbox.record_observation(
        request["publication_id"], attempt["attempt_id"], state=PublicationState.RETRYABLE,
        adapter_id="evm-rpc", reason_code="NONCE_EXPIRED", retry_metadata={"safe_to_retry": True}, now=21,
    )
    retry = outbox.prepare_publication_attempt(
        request["publication_id"], adapter_id="evm-rpc", transaction_id="0x" + "cd" * 32,
        payload=b"y" * 4096, metadata={"nonce": 8}, now=22,
    )
    assert retry["attempt_number"] == 2
    with pytest.raises(ValueError, match="no longer the active publication attempt"):
        outbox.record_observation(
            request["publication_id"], attempt["attempt_id"], state=PublicationState.REJECTED,
            adapter_id="evm-rpc", reason_code="LATE_FAILURE", now=22.5,
        )
    assert outbox.get(request["publication_id"])["status"] == "PREPARED"
    outbox.record_observation(
        request["publication_id"], retry["attempt_id"], state=PublicationState.RPC_ACCEPTED,
        adapter_id="evm-rpc", now=23,
    )
    outbox.record_observation(
        request["publication_id"], retry["attempt_id"], state=PublicationState.CONFIRMED,
        adapter_id="evm-rpc", block_ref="84532", now=24,
    )
    receipt = outbox.receipts(request["publication_id"])[-1]
    assert receipt["chain"] == "base"
    assert receipt["adapter_id"] == "evm-rpc"
    assert receipt["transaction_id"] == retry["transaction_id"]
    assert receipt["signature"] is None
    assert receipt["block_ref"] == "84532"
    assert receipt["submitted_at"] == 23.0
    assert receipt["confirmed_at"] == 24.0
    assert outbox.receipts(request["publication_id"])[0]["submitted_at"] == 20.5
    assert len(outbox.receipts(request["publication_id"])) == 4
    store.close()


def test_legacy_publication_schema_upgrades_without_rewriting_receipts(tmp_path):
    store, event = _store(tmp_path / "legacy.sqlite3")
    commitment = create_commitment_v1(event.hash, "cd" * 32)
    envelope = serialize_public_envelope(public_envelope(commitment))
    con = store.connection
    con.executescript("""
      CREATE TABLE publication_requests (
        publication_id TEXT PRIMARY KEY,event_id INTEGER NOT NULL,destination TEXT NOT NULL,
        network TEXT NOT NULL,idempotency_key TEXT NOT NULL,subject_ref TEXT NOT NULL,
        source_digest TEXT NOT NULL,commitment TEXT NOT NULL,envelope BLOB NOT NULL,
        status TEXT NOT NULL,created_at REAL NOT NULL);
      CREATE TABLE publication_outbox (
        publication_id TEXT PRIMARY KEY,available_at REAL NOT NULL,completed_at REAL);
      CREATE TABLE publication_attempts (
        attempt_id TEXT PRIMARY KEY,publication_id TEXT NOT NULL,attempt_number INTEGER NOT NULL,
        signature TEXT NOT NULL,signed_transaction BLOB NOT NULL,last_valid_block_height INTEGER NOT NULL,
        status TEXT NOT NULL,created_at REAL NOT NULL);
      CREATE TABLE publication_receipts (
        receipt_id TEXT PRIMARY KEY,publication_id TEXT NOT NULL,attempt_id TEXT NOT NULL,
        receipt_version INTEGER NOT NULL,adapter_id TEXT NOT NULL,adapter_version TEXT NOT NULL,
        commitment TEXT NOT NULL,network TEXT NOT NULL,state TEXT NOT NULL,observed_at REAL NOT NULL,
        submitted_at REAL,verified_at REAL,signature TEXT NOT NULL,reason_code TEXT,slot INTEGER,
        evidence_status TEXT NOT NULL);
      CREATE TRIGGER publication_receipts_no_update BEFORE UPDATE ON publication_receipts
        BEGIN SELECT RAISE(ABORT,'receipts are append-only'); END;
      CREATE TRIGGER publication_receipts_no_delete BEFORE DELETE ON publication_receipts
        BEGIN SELECT RAISE(ABORT,'receipts are append-only'); END;
    """)
    con.execute(
        "INSERT INTO publication_requests VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("legacy-pub", event.event_id, "solana-memo", "solana-devnet:test", "legacy-key",
         "cd" * 32, event.hash, commitment.digest, envelope, "QUEUED", 12.0),
    )
    con.execute("INSERT INTO publication_outbox VALUES('legacy-pub',12.0,NULL)")
    con.execute(
        "INSERT INTO publication_attempts VALUES(?,?,?,?,?,?,?,?)",
        ("legacy-attempt", "legacy-pub", 1, "1" * 64, b"legacy-payload", 50,
         "RPC_ACCEPTED", 13.0),
    )
    con.execute(
        "INSERT INTO publication_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("legacy-receipt", "legacy-pub", "legacy-attempt", 1, "solana-memo", "1",
         commitment.digest, "solana-devnet:test", "RPC_ACCEPTED", 13.0, 13.0, None,
         "1" * 64, None, None, "ASSUMED"),
    )
    con.commit()

    outbox = SQLitePublicationOutbox(store)
    request = outbox.get("legacy-pub")
    receipt = outbox.receipts("legacy-pub")[0]
    assert request["chain"] == "solana"
    assert request["commitment"] == commitment.digest
    assert receipt["transaction_id"] == "1" * 64
    assert receipt["chain"] == "solana"
    attempt = outbox.latest_attempt("legacy-pub")
    assert attempt["adapter_id"] == "solana-memo"
    assert attempt["transaction_id"] == "1" * 64
    assert attempt["metadata"] == {"last_valid_block_height": 50}
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute("UPDATE publication_receipts SET state='VERIFIED'")
    con.rollback()
    store.close()


def test_interrupted_chain_backfill_is_repaired_on_reopen(tmp_path):
    con = sqlite3.connect(tmp_path / "partial-migration.sqlite3")
    con.row_factory = sqlite3.Row
    con.executescript("""
      CREATE TABLE publication_requests (
        publication_id TEXT PRIMARY KEY,destination TEXT NOT NULL,
        chain TEXT NOT NULL DEFAULT 'unknown');
      CREATE TABLE publication_attempts (
        attempt_id TEXT PRIMARY KEY,publication_id TEXT NOT NULL,attempt_number INTEGER NOT NULL,
        signature TEXT NOT NULL,signed_transaction BLOB NOT NULL,last_valid_block_height INTEGER NOT NULL,
        status TEXT NOT NULL,created_at REAL NOT NULL);
      CREATE TABLE publication_receipts (
        receipt_id TEXT PRIMARY KEY,publication_id TEXT NOT NULL,attempt_id TEXT NOT NULL,
        receipt_version INTEGER NOT NULL,adapter_id TEXT NOT NULL,adapter_version TEXT NOT NULL,
        commitment TEXT NOT NULL,network TEXT NOT NULL,state TEXT NOT NULL,observed_at REAL NOT NULL,
        submitted_at REAL,verified_at REAL,signature TEXT NOT NULL,reason_code TEXT,slot INTEGER,
        evidence_status TEXT NOT NULL);
      INSERT INTO publication_requests VALUES('legacy-pub','solana-memo','unknown');
    """)
    con.commit()

    SQLitePublicationOutbox._upgrade_legacy_schema(con)

    assert con.execute(
        "SELECT chain FROM publication_requests WHERE publication_id='legacy-pub'"
    ).fetchone()["chain"] == "solana"
    con.close()


def test_failed_migration_lock_restores_foreign_keys_on_shared_connection(tmp_path):
    path = tmp_path / "migration-lock.sqlite3"
    holder = sqlite3.connect(path)
    contender = sqlite3.connect(path, timeout=0.01)
    contender.row_factory = sqlite3.Row
    contender.execute("PRAGMA foreign_keys=ON")
    holder.execute("BEGIN IMMEDIATE")

    with pytest.raises(sqlite3.OperationalError, match="locked"):
        SQLitePublicationOutbox._upgrade_legacy_schema(contender)

    assert contender.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    holder.rollback()
    contender.close()
    holder.close()


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


def test_receipt_cannot_claim_another_attempt_transaction_or_adapter(tmp_path):
    store, event = _store(tmp_path / "receipt-correlation.sqlite3")
    outbox = SQLitePublicationOutbox(store)
    request = outbox.enqueue_event(event.event_id, destination="solana-memo", network="solana-devnet:genesis")
    attempt = outbox.prepare_attempt(
        request["publication_id"], signature="1" * 64,
        signed_transaction=b"signed", last_valid_block_height=5,
    )
    with pytest.raises(ValueError, match="transaction_id"):
        outbox.record_observation(
            request["publication_id"], attempt["attempt_id"], state=PublicationState.RPC_ACCEPTED,
            transaction_id="2" * 64,
        )
    with pytest.raises(ValueError, match="adapter"):
        outbox.record_observation(
            request["publication_id"], attempt["attempt_id"], state=PublicationState.RPC_ACCEPTED,
            adapter_id="base-rpc",
        )
    assert outbox.receipts(request["publication_id"]) == []
    assert outbox.get(request["publication_id"])["status"] == "PREPARED"
    store.close()


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
    assert receipts[2]["confirmed_at"] == 21.0
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
