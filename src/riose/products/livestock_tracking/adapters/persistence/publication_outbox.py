"""Durable, opt-in publication requests and attempt/receipt journal."""

from __future__ import annotations

import json
import math
import re
import secrets
import sqlite3
import time
from typing import TYPE_CHECKING, Any

from ...domain.commitment import create_commitment_v1, new_subject_ref, public_envelope
from ...domain.identity import GENESIS_HASH, EVENT_CONTRACT_V1, append_event, event_digest
from ...domain.privacy import serialize_public_envelope
from ...domain.publication_state import PublicationState, require_transition

if TYPE_CHECKING:
    from .sqlite_store import Store


_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z", re.ASCII)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_SIG = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,128}\Z", re.ASCII)
_RECEIPT_REASON = re.compile(r"[A-Z][A-Z0-9_]{0,47}\Z", re.ASCII)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS publication_requests (
  publication_id TEXT PRIMARY KEY,
  event_id INTEGER NOT NULL REFERENCES animal_events(event_id),
  destination TEXT NOT NULL,
  network TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  subject_ref TEXT NOT NULL CHECK(length(subject_ref)=64),
  source_digest TEXT NOT NULL CHECK(length(source_digest)=64),
  commitment TEXT NOT NULL CHECK(length(commitment)=64),
  envelope BLOB NOT NULL CHECK(length(envelope) BETWEEN 1 AND 512),
  status TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(event_id,destination,network)
);
CREATE TABLE IF NOT EXISTS publication_outbox (
  publication_id TEXT PRIMARY KEY REFERENCES publication_requests(publication_id),
  available_at REAL NOT NULL,
  completed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_publication_outbox_due
  ON publication_outbox(available_at,publication_id) WHERE completed_at IS NULL;
CREATE TABLE IF NOT EXISTS publication_attempts (
  attempt_id TEXT PRIMARY KEY,
  publication_id TEXT NOT NULL REFERENCES publication_requests(publication_id),
  attempt_number INTEGER NOT NULL,
  signature TEXT NOT NULL UNIQUE,
  signed_transaction BLOB NOT NULL CHECK(length(signed_transaction) BETWEEN 1 AND 1232),
  last_valid_block_height INTEGER NOT NULL CHECK(last_valid_block_height >= 0),
  status TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(publication_id,attempt_number)
);
CREATE TABLE IF NOT EXISTS publication_receipts (
  receipt_id TEXT PRIMARY KEY,
  publication_id TEXT NOT NULL REFERENCES publication_requests(publication_id),
  attempt_id TEXT NOT NULL REFERENCES publication_attempts(attempt_id),
  receipt_version INTEGER NOT NULL DEFAULT 1 CHECK(receipt_version=1),
  adapter_id TEXT NOT NULL DEFAULT 'solana-memo',
  adapter_version TEXT NOT NULL DEFAULT '1',
  commitment TEXT NOT NULL CHECK(length(commitment)=64),
  network TEXT NOT NULL,
  state TEXT NOT NULL,
  observed_at REAL NOT NULL,
  submitted_at REAL,
  verified_at REAL,
  signature TEXT NOT NULL,
  reason_code TEXT,
  slot INTEGER,
  evidence_status TEXT NOT NULL,
  UNIQUE(attempt_id,state,signature)
);
CREATE TRIGGER IF NOT EXISTS publication_receipts_no_update
  BEFORE UPDATE ON publication_receipts BEGIN SELECT RAISE(ABORT,'receipts are append-only'); END;
CREATE TRIGGER IF NOT EXISTS publication_receipts_no_delete
  BEFORE DELETE ON publication_receipts BEGIN SELECT RAISE(ABORT,'receipts are append-only'); END;
"""


class SQLitePublicationOutbox:
    """Publication persistence using the existing Store connection and lock."""

    def __init__(self, store: Store) -> None:
        self.store = store
        with store._lock:
            store.connection.executescript(_SCHEMA)
            store.connection.commit()

    def enqueue_event(
        self,
        event_id: int,
        *,
        destination: str,
        network: str,
        idempotency_key: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        _identifier(destination, "destination")
        _identifier(network, "network")
        created_at = time.time() if now is None else _timestamp(now, "now")
        if type(event_id) is not int or event_id < 1:
            raise ValueError("event_id must be a positive integer")
        if idempotency_key is not None:
            _identifier(idempotency_key, "idempotency_key")
        with self.store._lock:
            con = self.store.connection
            con.execute("BEGIN IMMEDIATE")
            try:
                existing = con.execute(
                    "SELECT * FROM publication_requests WHERE event_id=? AND destination=? AND network=?",
                    (event_id, destination, network),
                ).fetchone()
                if existing is not None:
                    con.commit()
                    return _request_dict(existing)
                event = _verified_event_prefix(con, event_id)
                subject_ref = new_subject_ref()
                commitment = create_commitment_v1(event["hash"], subject_ref)
                envelope = serialize_public_envelope(public_envelope(commitment))
                publication_id = secrets.token_hex(16)
                key = idempotency_key or f"event-{event_id}-{destination}-{network}"
                con.execute(
                    "INSERT INTO publication_requests(publication_id,event_id,destination,network,idempotency_key,subject_ref,source_digest,commitment,envelope,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (publication_id, event_id, destination, network, key, subject_ref,
                     event["hash"], commitment.digest, envelope, PublicationState.QUEUED.value, created_at),
                )
                con.execute(
                    "INSERT INTO publication_outbox(publication_id,available_at) VALUES(?,?)",
                    (publication_id, created_at),
                )
                con.commit()
            except Exception:
                con.rollback()
                raise
        return self.get(publication_id) or {}

    def append_event_and_enqueue(
        self,
        animal_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        destination: str,
        network: str,
        idempotency_key: str,
        timestamp: float | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Atomically append one Core event with its optional publication intent."""
        _identifier(destination, "destination")
        _identifier(network, "network")
        _identifier(idempotency_key, "idempotency_key")
        created_at = time.time() if now is None else _timestamp(now, "now")
        if timestamp is not None:
            timestamp = _timestamp(timestamp, "timestamp")
        if type(payload) is not dict:
            raise ValueError("payload must be a JSON object")
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        with self.store._lock:
            con = self.store.connection
            con.execute("BEGIN IMMEDIATE")
            try:
                existing = con.execute(
                    "SELECT r.*,e.animal_id,e.event_type,e.timestamp,e.payload AS event_payload "
                    "FROM publication_requests r JOIN animal_events e USING(event_id) WHERE r.idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    same_request = (
                        existing["destination"] == destination
                        and existing["network"] == network
                        and existing["animal_id"] == animal_id
                        and existing["event_type"] == event_type
                        and existing["event_payload"] == payload_json
                        and (timestamp is None or existing["timestamp"] == timestamp)
                    )
                    if not same_request:
                        raise ValueError("idempotency key already identifies a different publication request")
                    con.commit()
                    result = _request_dict(existing)
                    for private_field in ("animal_id", "event_type", "timestamp", "event_payload"):
                        result.pop(private_field, None)
                    return result
                event = append_event(
                    con, animal_id, event_type, payload,
                    created_at if timestamp is None else timestamp, commit=False,
                )
                verified_event = _verified_event_prefix(con, event.event_id)
                subject_ref = new_subject_ref()
                commitment = create_commitment_v1(verified_event["hash"], subject_ref)
                envelope = serialize_public_envelope(public_envelope(commitment))
                publication_id = secrets.token_hex(16)
                con.execute(
                    "INSERT INTO publication_requests(publication_id,event_id,destination,network,idempotency_key,subject_ref,source_digest,commitment,envelope,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (publication_id, event.event_id, destination, network, idempotency_key,
                     subject_ref, verified_event["hash"], commitment.digest, envelope,
                     PublicationState.QUEUED.value, created_at),
                )
                con.execute(
                    "INSERT INTO publication_outbox(publication_id,available_at) VALUES(?,?)",
                    (publication_id, created_at),
                )
                con.commit()
            except Exception:
                con.rollback()
                raise
        return self.get(publication_id) or {}

    def get(self, publication_id: str) -> dict[str, Any] | None:
        _identifier(publication_id, "publication_id")
        with self.store._lock:
            row = self.store.connection.execute(
                "SELECT r.*,o.available_at,o.completed_at FROM publication_requests r "
                "LEFT JOIN publication_outbox o USING(publication_id) WHERE publication_id=?",
                (publication_id,),
            ).fetchone()
        return _request_dict(row) if row is not None else None

    def list_pending(self, limit: int = 100) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self.store._lock:
            rows = self.store.connection.execute(
                "SELECT r.*,o.available_at,o.completed_at FROM publication_requests r "
                "JOIN publication_outbox o USING(publication_id) "
                "WHERE o.completed_at IS NULL ORDER BY o.available_at,r.publication_id LIMIT ?",
                (limit,),
            ).fetchall()
        return [_request_dict(row) for row in rows]

    def prepare_attempt(
        self,
        publication_id: str,
        *,
        signature: str,
        signed_transaction: bytes,
        last_valid_block_height: int,
        now: float | None = None,
    ) -> dict[str, Any]:
        _identifier(publication_id, "publication_id")
        if type(signature) is not str or _SIG.fullmatch(signature) is None or len(_decode_base58(signature)) != 64:
            raise ValueError("signature must be a base58 Solana signature")
        if type(signed_transaction) is not bytes or not 1 <= len(signed_transaction) <= 1232:
            raise ValueError("signed_transaction must be between 1 and 1232 bytes")
        if type(last_valid_block_height) is not int or last_valid_block_height < 0:
            raise ValueError("last_valid_block_height must be a non-negative integer")
        timestamp = time.time() if now is None else _timestamp(now, "now")
        attempt_id = secrets.token_hex(16)
        with self.store._lock:
            con = self.store.connection
            con.execute("BEGIN IMMEDIATE")
            try:
                request = con.execute(
                    "SELECT status,commitment,network FROM publication_requests WHERE publication_id=?", (publication_id,)
                ).fetchone()
                if request is None:
                    raise ValueError("publication request was not found")
                current = PublicationState(request["status"])
                require_transition(current, PublicationState.PREPARED)
                attempt_number = con.execute(
                    "SELECT COALESCE(MAX(attempt_number),0)+1 FROM publication_attempts WHERE publication_id=?",
                    (publication_id,),
                ).fetchone()[0]
                con.execute(
                    "INSERT INTO publication_attempts(attempt_id,publication_id,attempt_number,signature,signed_transaction,last_valid_block_height,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (attempt_id, publication_id, attempt_number, signature, signed_transaction,
                     last_valid_block_height, PublicationState.PREPARED.value, timestamp),
                )
                con.execute("UPDATE publication_requests SET status=? WHERE publication_id=?",
                            (PublicationState.PREPARED.value, publication_id))
                con.commit()
            except Exception:
                con.rollback()
                raise
        return self.attempt(attempt_id) or {}

    def attempt(self, attempt_id: str) -> dict[str, Any] | None:
        _identifier(attempt_id, "attempt_id")
        with self.store._lock:
            row = self.store.connection.execute(
                "SELECT * FROM publication_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def latest_attempt(self, publication_id: str) -> dict[str, Any] | None:
        _identifier(publication_id, "publication_id")
        with self.store._lock:
            row = self.store.connection.execute(
                "SELECT * FROM publication_attempts WHERE publication_id=? ORDER BY attempt_number DESC LIMIT 1",
                (publication_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def verify_local_binding(self, publication_id: str) -> bool:
        request = self.get(publication_id)
        if request is None:
            return False
        with self.store._lock:
            try:
                event = _verified_event_prefix(self.store.connection, request["event_id"])
                if event["hash"] != request["source_digest"]:
                    return False
                commitment = create_commitment_v1(event["hash"], request["subject_ref"])
                return (
                    commitment.digest == request["commitment"]
                    and serialize_public_envelope(public_envelope(commitment)) == request["envelope"]
                )
            except (TypeError, ValueError):
                return False

    def record_observation(
        self,
        publication_id: str,
        attempt_id: str,
        *,
        state: PublicationState,
        reason_code: str | None = None,
        slot: int | None = None,
        evidence_status: str = "ASSUMED",
        now: float | None = None,
    ) -> None:
        if not isinstance(state, PublicationState):
            raise ValueError("state must be a PublicationState")
        if reason_code is not None and (type(reason_code) is not str or _RECEIPT_REASON.fullmatch(reason_code) is None):
            raise ValueError("reason_code must be an allowlisted reason identifier")
        if slot is not None and (type(slot) is not int or slot < 0):
            raise ValueError("slot must be a non-negative integer")
        if evidence_status not in {"ASSUMED", "SIMULATED", "MOCKED", "VALIDATED", "UNKNOWN"}:
            raise ValueError("unsupported evidence_status")
        timestamp = time.time() if now is None else _timestamp(now, "now")
        receipt_id = secrets.token_hex(16)
        with self.store._lock:
            con = self.store.connection
            con.execute("BEGIN IMMEDIATE")
            try:
                request = con.execute(
                    "SELECT status,commitment,network FROM publication_requests WHERE publication_id=?", (publication_id,)
                ).fetchone()
                attempt = con.execute(
                    "SELECT signature FROM publication_attempts WHERE attempt_id=? AND publication_id=?",
                    (attempt_id, publication_id),
                ).fetchone()
                if request is None or attempt is None:
                    raise ValueError("publication attempt was not found")
                current = PublicationState(request["status"])
                require_transition(current, state)
                prior_submission = con.execute(
                    "SELECT MIN(observed_at) FROM publication_receipts WHERE publication_id=? AND state=?",
                    (publication_id, PublicationState.RPC_ACCEPTED.value),
                ).fetchone()[0]
                submitted_at = timestamp if state is PublicationState.RPC_ACCEPTED else prior_submission
                verified_at = timestamp if state is PublicationState.VERIFIED else None
                con.execute(
                    "INSERT INTO publication_receipts(receipt_id,publication_id,attempt_id,receipt_version,adapter_id,adapter_version,commitment,network,state,observed_at,submitted_at,verified_at,signature,reason_code,slot,evidence_status) "
                    "VALUES(?,?,?,1,'solana-memo','1',?,?,?,?,?,?,?,?,?,?)",
                    (receipt_id, publication_id, attempt_id, request["commitment"], request["network"],
                     state.value, timestamp, submitted_at, verified_at, attempt["signature"], reason_code, slot, evidence_status),
                )
                con.execute("UPDATE publication_requests SET status=? WHERE publication_id=?",
                            (state.value, publication_id))
                con.execute("UPDATE publication_attempts SET status=? WHERE attempt_id=?",
                            (state.value, attempt_id))
                if state in {PublicationState.VERIFIED, PublicationState.REJECTED}:
                    con.execute("UPDATE publication_outbox SET completed_at=? WHERE publication_id=?",
                                (timestamp, publication_id))
                con.commit()
            except Exception:
                con.rollback()
                raise

    def receipts(self, publication_id: str) -> list[dict[str, Any]]:
        _identifier(publication_id, "publication_id")
        with self.store._lock:
            rows = self.store.connection.execute(
                "SELECT receipt_id,publication_id,attempt_id,receipt_version,adapter_id,adapter_version,commitment,network,state,observed_at,submitted_at,verified_at,signature,reason_code,slot,evidence_status "
                "FROM publication_receipts WHERE publication_id=? ORDER BY observed_at,receipt_id",
                (publication_id,),
            ).fetchall()
        return [dict(row) for row in rows]


def _verified_event_prefix(con: sqlite3.Connection, event_id: int) -> dict[str, Any]:
    target = con.execute(
        "SELECT event_id,animal_id FROM animal_events WHERE event_id=?", (event_id,)
    ).fetchone()
    if target is None:
        raise ValueError("event was not found")
    rows = con.execute(
        "SELECT event_id,animal_id,event_type,timestamp,payload,previous_hash,hash,schema_version "
        "FROM animal_events WHERE animal_id=? AND event_id<=? ORDER BY event_id",
        (target["animal_id"], event_id),
    ).fetchall()
    previous = GENESIS_HASH
    selected: dict[str, Any] | None = None
    for row in rows:
        try:
            if row["schema_version"] not in (None, EVENT_CONTRACT_V1) or row["previous_hash"] != previous:
                raise ValueError
            payload = json.loads(row["payload"], parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            digest = event_digest(row["animal_id"], row["event_type"], row["timestamp"], payload, previous)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("event prefix failed local chain verification") from exc
        if digest != row["hash"]:
            raise ValueError("event prefix failed local chain verification")
        previous = digest
        if row["event_id"] == event_id:
            selected = dict(row)
    if selected is None:
        raise ValueError("event is not part of the verified prefix")
    return selected


def _request_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["envelope"] = bytes(result["envelope"])
    return result


def _identifier(value: str, name: str) -> None:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{name} must be a bounded technical identifier")


def _timestamp(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite timestamp")
    return float(value)


def _decode_base58(value: str) -> bytes:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = 0
    for char in value:
        if char not in alphabet:
            return b""
        number = number * 58 + alphabet.index(char)
    decoded = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\0" * (len(value) - len(value.lstrip("1"))) + decoded
