"""Opt-in durable receipt repository and privacy boundary tests."""

from __future__ import annotations

import sqlite3

import pytest

from riose.products.livestock_tracking.adapters.persistence import (
    ReceiptConflictError,
    Store,
)
from riose.products.livestock_tracking.domain.contracts import EvidenceStatus
from riose.products.livestock_tracking.domain.receipt import PublicationReceipt, ReceiptStatus


COMMITMENT = "a" * 64


def receipt(**overrides):
    values = {
        "receipt_id": "receipt-1",
        "version": 1,
        "commitment": COMMITMENT,
        "destination": "solana-memo",
        "network": "solana-devnet-a1b2c3d4",
        "status": ReceiptStatus.SUBMITTED,
        "evidence_status": EvidenceStatus.SIMULATED,
        "source": "offline-fixture",
        "observed_at": 12.5,
        "reference": "simulated-signature-1",
    }
    values.update(overrides)
    return PublicationReceipt(**values)


def test_receipts_are_opt_in_and_do_not_change_default_store_schema(tmp_path):
    store = Store(tmp_path / "default.sqlite3")
    assert store.publication_receipts is None
    tables = {
        row[0]
        for row in store.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "publication_receipts" not in tables
    store.close()


def test_receipt_persists_across_reopen_without_animal_payload(tmp_path):
    path = tmp_path / "receipt.sqlite3"
    first = Store(path, enable_publication_receipts=True)
    saved = first.publication_receipts.save(receipt())
    assert saved == receipt()
    first.close()

    reopened = Store(path, enable_publication_receipts=True)
    assert reopened.publication_receipts.get("receipt-1") == receipt()
    listed = reopened.publication_receipts.list_for_commitment(COMMITMENT)
    assert listed == [receipt()]
    columns = {
        row[1]
        for row in reopened.connection.execute("PRAGMA table_info(publication_receipts)")
    }
    assert "animal_id" not in columns and "payload" not in columns
    assert {"version", "source", "evidence_status"} <= columns
    reopened.close()


def test_same_receipt_is_idempotent_but_changed_content_cannot_overwrite(tmp_path):
    store = Store(tmp_path / "receipt.sqlite3", enable_publication_receipts=True)
    repository = store.publication_receipts
    assert repository.save(receipt()) == receipt()
    assert repository.save(receipt()) == receipt()
    with pytest.raises(ReceiptConflictError):
        repository.save(receipt(status=ReceiptStatus.CONFIRMED, observed_at=14.0))
    assert repository.get("receipt-1") == receipt()
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute(
            "UPDATE publication_receipts SET status='CONFIRMED' WHERE receipt_id='receipt-1'"
        )
    store.close()


def test_new_observation_appends_without_rewriting_the_prior_receipt(tmp_path):
    store = Store(tmp_path / "receipt.sqlite3", enable_publication_receipts=True)
    store.publication_receipts.save(receipt())
    confirmed = receipt(
        receipt_id="receipt-2",
        status=ReceiptStatus.CONFIRMED,
        source="solana-rpc",
        evidence_status=EvidenceStatus.ASSUMED,
        observed_at=15.0,
    )
    store.publication_receipts.save(confirmed)
    assert store.publication_receipts.get("receipt-1") == receipt()
    with pytest.raises(ValueError):
        store.publication_receipts.get("receipt id with spaces")
    assert store.publication_receipts.get("receipt-2") == confirmed
    assert len(store.publication_receipts.list_for_commitment(COMMITMENT)) == 2
    store.close()


def test_receipt_contract_preserves_status_and_provenance_distinctions():
    assert receipt().status is ReceiptStatus.SUBMITTED
    assert receipt(evidence_status=EvidenceStatus.SIMULATED).evidence_status is EvidenceStatus.SIMULATED
    with pytest.raises(ValueError):
        receipt(status=ReceiptStatus.CONFIRMED, reference=None)
    with pytest.raises(ValueError):
        receipt(destination="Solana with animal identifier")
    with pytest.raises(ValueError):
        receipt(evidence_status="VALIDATED")
    with pytest.raises(ValueError):
        receipt(commitment="bad")


def test_unavailable_unknown_and_invalid_remain_distinct(tmp_path):
    store = Store(tmp_path / "receipt.sqlite3", enable_publication_receipts=True)
    unknown = receipt(receipt_id="receipt-unknown", status=ReceiptStatus.UNKNOWN, reference=None)
    unavailable = receipt(
        receipt_id="receipt-unavailable",
        status=ReceiptStatus.UNAVAILABLE,
        evidence_status=EvidenceStatus.ASSUMED,
        source="solana-rpc",
        reference=None,
    )
    store.publication_receipts.save(unknown)
    store.publication_receipts.save(unavailable)
    assert store.publication_receipts.get(unknown.receipt_id).status is ReceiptStatus.UNKNOWN
    assert store.publication_receipts.get(unavailable.receipt_id).status is ReceiptStatus.UNAVAILABLE
    store.close()


def test_failed_insert_rolls_back_without_partial_receipt(tmp_path):
    store = Store(tmp_path / "receipt.sqlite3", enable_publication_receipts=True)
    store.connection.execute(
        "CREATE TRIGGER fail_publication_receipt BEFORE INSERT ON publication_receipts "
        "BEGIN SELECT RAISE(ABORT, 'fixture failure'); END"
    )
    with pytest.raises(ReceiptConflictError):
        store.publication_receipts.save(receipt())
    assert store.publication_receipts.get("receipt-1") is None
    store.close()


def test_receipt_write_does_not_mutate_the_animal_event_chain(tmp_path):
    store = Store(tmp_path / "receipt.sqlite3", enable_publication_receipts=True)
    store.create_animal("synthetic", "tag-syn", "b" * 64)
    before = store.connection.execute(
        "SELECT event_id,hash FROM animal_events ORDER BY event_id"
    ).fetchall()
    assert store.verify_animal_chain("synthetic")
    store.publication_receipts.save(receipt())
    after = store.connection.execute(
        "SELECT event_id,hash FROM animal_events ORDER BY event_id"
    ).fetchall()
    assert before == after
    assert store.verify_animal_chain("synthetic")
    store.close()
