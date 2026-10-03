"""Opt-in append-only SQLite storage for minimized publication receipts."""

from __future__ import annotations

import re
import sqlite3
from typing import TYPE_CHECKING

from ...domain.contracts import EvidenceStatus
from ...domain.receipt import PublicationReceipt, ReceiptStatus

if TYPE_CHECKING:
    from .sqlite_store import Store

RECEIPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS publication_receipts (
  receipt_id TEXT PRIMARY KEY,
  version INTEGER NOT NULL CHECK(version > 0),
  commitment TEXT NOT NULL,
  destination TEXT NOT NULL,
  network TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('SUBMITTED','CONFIRMED','REJECTED','UNKNOWN','UNAVAILABLE')),
  evidence_status TEXT NOT NULL CHECK(evidence_status IN ('VALIDATED','SIMULATED','ASSUMED','EXPERIMENTAL','FUTURE')),
  source TEXT NOT NULL,
  observed_at REAL NOT NULL,
  reference TEXT
);
CREATE INDEX IF NOT EXISTS idx_publication_receipts_commitment
  ON publication_receipts(commitment, observed_at, receipt_id);
CREATE TRIGGER IF NOT EXISTS trg_publication_receipts_no_update
  BEFORE UPDATE ON publication_receipts BEGIN
  SELECT RAISE(ABORT, 'publication receipts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_publication_receipts_no_delete
  BEFORE DELETE ON publication_receipts BEGIN
  SELECT RAISE(ABORT, 'publication receipts are append-only');
END;
"""
_OPAQUE_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z", re.ASCII)


class ReceiptConflictError(ValueError):
    """A receipt id already has different immutable content."""


class SQLitePublicationReceiptRepository:
    """Append-only repository using the Store connection and transaction lock."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def save(self, receipt: PublicationReceipt) -> PublicationReceipt:
        if type(receipt) is not PublicationReceipt:
            raise ValueError("receipt must be a PublicationReceipt")
        values = _receipt_values(receipt)
        with self._store._lock:
            connection = self._store.connection
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT receipt_id,version,commitment,destination,network,status,evidence_status,source,observed_at,reference "
                    "FROM publication_receipts WHERE receipt_id=?",
                    (receipt.receipt_id,),
                ).fetchone()
                if existing is not None:
                    saved = _receipt_from_row(existing)
                    if saved != receipt:
                        raise ReceiptConflictError("receipt id already has different immutable content")
                    connection.commit()
                    return saved
                connection.execute(
                    "INSERT INTO publication_receipts(receipt_id,version,commitment,destination,network,status,evidence_status,source,observed_at,reference) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    values,
                )
                connection.commit()
            except ReceiptConflictError:
                connection.rollback()
                raise
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise ReceiptConflictError("receipt conflicts with existing immutable data") from exc
            except Exception:
                connection.rollback()
                raise
        return receipt

    def get(self, receipt_id: str) -> PublicationReceipt | None:
        _validate_lookup_id(receipt_id)
        with self._store._lock:
            row = self._store.connection.execute(
                "SELECT receipt_id,version,commitment,destination,network,status,evidence_status,source,observed_at,reference "
                "FROM publication_receipts WHERE receipt_id=?",
                (receipt_id,),
            ).fetchone()
        return _receipt_from_row(row) if row is not None else None

    def list_for_commitment(self, commitment: str, *, limit: int = 100) -> list[PublicationReceipt]:
        if type(commitment) is not str or len(commitment) != 64 or any(c not in "0123456789abcdef" for c in commitment):
            raise ValueError("commitment must be a lowercase SHA-256 digest")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._store._lock:
            rows = self._store.connection.execute(
                "SELECT receipt_id,version,commitment,destination,network,status,evidence_status,source,observed_at,reference "
                "FROM publication_receipts WHERE commitment=? ORDER BY observed_at,receipt_id LIMIT ?",
                (commitment, limit),
            ).fetchall()
        return [_receipt_from_row(row) for row in rows]


def _receipt_values(receipt: PublicationReceipt) -> tuple[object, ...]:
    return (
        receipt.receipt_id,
        receipt.version,
        receipt.commitment,
        receipt.destination,
        receipt.network,
        receipt.status.value,
        receipt.evidence_status.value,
        receipt.source,
        float(receipt.observed_at),
        receipt.reference,
    )


def _receipt_from_row(row: sqlite3.Row) -> PublicationReceipt:
    return PublicationReceipt(
        receipt_id=row["receipt_id"],
        version=row["version"],
        commitment=row["commitment"],
        destination=row["destination"],
        network=row["network"],
        status=ReceiptStatus(row["status"]),
        evidence_status=EvidenceStatus(row["evidence_status"]),
        source=row["source"],
        observed_at=row["observed_at"],
        reference=row["reference"],
    )


def _validate_lookup_id(receipt_id: str) -> None:
    if type(receipt_id) is not str or _OPAQUE_ID_PATTERN.fullmatch(receipt_id) is None:
        raise ValueError("receipt_id must be an opaque technical identifier")
