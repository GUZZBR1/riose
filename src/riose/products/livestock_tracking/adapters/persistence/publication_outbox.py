"""Opt-in local SQLite queue for minimized commitment publication tickets."""

from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sqlite_store import Store


MAX_OUTBOX_ENVELOPE_BYTES = 512
MAX_OUTBOX_LIST_LIMIT = 1000
_OPAQUE_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z", re.ASCII)

OUTBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS publication_outbox (
  ticket_id TEXT PRIMARY KEY,
  envelope_version INTEGER NOT NULL,
  envelope_bytes BLOB NOT NULL,
  available_at REAL NOT NULL,
  claim_token TEXT,
  claimed_at REAL,
  CHECK(envelope_version > 0),
  CHECK(length(envelope_bytes) BETWEEN 1 AND 512)
);
CREATE INDEX IF NOT EXISTS idx_publication_outbox_due
  ON publication_outbox(available_at, ticket_id) WHERE claim_token IS NULL;
"""


@dataclass(frozen=True, slots=True)
class OutboxEnvelope:
    """Bounded, versioned fixture bytes; no event or animal fields are accepted."""

    version: int
    data: bytes

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version < 1:
            raise ValueError("envelope version must be a positive integer")
        if type(self.data) is not bytes or not self.data:
            raise ValueError("envelope data must be non-empty bytes")
        if len(self.data) > MAX_OUTBOX_ENVELOPE_BYTES:
            raise ValueError("envelope data exceeds the size limit")


@dataclass(frozen=True, slots=True)
class OutboxTicket:
    ticket_id: str
    envelope: OutboxEnvelope
    available_at: float
    claim_token: str | None = None
    claimed_at: float | None = None


class SQLitePublicationOutbox:
    """Small opt-in repository using the Store's connection and lock."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def enqueue(
        self, ticket_id: str, envelope: OutboxEnvelope, available_at: float
    ) -> OutboxTicket:
        _validate_opaque_id(ticket_id, "ticket_id")
        if type(envelope) is not OutboxEnvelope:
            raise ValueError("envelope must be a versioned OutboxEnvelope")
        _validate_timestamp(available_at, "available_at")
        with self._store._lock:
            connection = self._store.connection
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO publication_outbox(ticket_id,envelope_version,envelope_bytes,available_at) VALUES(?,?,?,?)",
                    (ticket_id, envelope.version, envelope.data, float(available_at)),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return OutboxTicket(ticket_id, envelope, float(available_at))

    def get(self, ticket_id: str) -> OutboxTicket | None:
        _validate_opaque_id(ticket_id, "ticket_id")
        with self._store._lock:
            row = self._store.connection.execute(
                "SELECT ticket_id,envelope_version,envelope_bytes,available_at,claim_token,claimed_at "
                "FROM publication_outbox WHERE ticket_id=?",
                (ticket_id,),
            ).fetchone()
        return _ticket_from_row(row) if row is not None else None

    def list_pending(self, limit: int) -> list[OutboxTicket]:
        _validate_limit(limit)
        with self._store._lock:
            rows = self._store.connection.execute(
                "SELECT ticket_id,envelope_version,envelope_bytes,available_at,claim_token,claimed_at "
                "FROM publication_outbox WHERE claim_token IS NULL "
                "ORDER BY available_at,ticket_id LIMIT ?",
                (limit,),
            ).fetchall()
        return [_ticket_from_row(row) for row in rows]

    def claim_due(
        self, now: float, limit: int, claim_token: str
    ) -> list[OutboxTicket]:
        _validate_timestamp(now, "now")
        _validate_limit(limit)
        _validate_opaque_id(claim_token, "claim_token")
        with self._store._lock:
            connection = self._store.connection
            try:
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    "SELECT ticket_id,envelope_version,envelope_bytes,available_at,claim_token,claimed_at "
                    "FROM publication_outbox WHERE claim_token IS NULL AND available_at<=? "
                    "ORDER BY available_at,ticket_id LIMIT ?",
                    (float(now), limit),
                ).fetchall()
                claimed: list[OutboxTicket] = []
                for row in rows:
                    cursor = connection.execute(
                        "UPDATE publication_outbox SET claim_token=?,claimed_at=? "
                        "WHERE ticket_id=? AND claim_token IS NULL",
                        (claim_token, float(now), row["ticket_id"]),
                    )
                    if cursor.rowcount == 1:
                        claimed.append(
                            OutboxTicket(
                                ticket_id=row["ticket_id"],
                                envelope=OutboxEnvelope(row["envelope_version"], bytes(row["envelope_bytes"])),
                                available_at=row["available_at"],
                                claim_token=claim_token,
                                claimed_at=float(now),
                            )
                        )
                connection.commit()
                return claimed
            except Exception:
                connection.rollback()
                raise


def _ticket_from_row(row: sqlite3.Row) -> OutboxTicket:
    return OutboxTicket(
        ticket_id=row["ticket_id"],
        envelope=OutboxEnvelope(row["envelope_version"], bytes(row["envelope_bytes"])),
        available_at=row["available_at"],
        claim_token=row["claim_token"],
        claimed_at=row["claimed_at"],
    )


def _validate_opaque_id(value: str, name: str) -> None:
    if type(value) is not str or _OPAQUE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be an opaque technical identifier")


def _validate_timestamp(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite timestamp")


def _validate_limit(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= MAX_OUTBOX_LIST_LIMIT:
        raise ValueError("limit must be between 1 and 1000")
