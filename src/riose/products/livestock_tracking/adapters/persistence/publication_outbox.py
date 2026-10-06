"""Durable, opt-in publication requests and attempt/receipt journal."""

from __future__ import annotations

import json
import hashlib
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
  chain TEXT NOT NULL,
  adapter_id TEXT NOT NULL,
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
CREATE TABLE IF NOT EXISTS publication_processing_claims (
  publication_id TEXT PRIMARY KEY REFERENCES publication_requests(publication_id),
  token TEXT NOT NULL,
  expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS publication_attempts (
  attempt_id TEXT PRIMARY KEY,
  publication_id TEXT NOT NULL REFERENCES publication_requests(publication_id),
  adapter_id TEXT NOT NULL,
  attempt_number INTEGER NOT NULL,
  transaction_id TEXT NOT NULL,
  payload BLOB NOT NULL CHECK(length(payload) BETWEEN 1 AND 1048576),
  metadata_json TEXT NOT NULL DEFAULT '{}',
  legacy_signature TEXT,
  legacy_signed_transaction BLOB,
  legacy_last_valid_block_height INTEGER,
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
  chain TEXT NOT NULL DEFAULT 'solana',
  commitment TEXT NOT NULL CHECK(length(commitment)=64),
  network TEXT NOT NULL,
  state TEXT NOT NULL,
  observed_at REAL NOT NULL,
  submitted_at REAL,
  confirmed_at REAL,
  verified_at REAL,
  transaction_id TEXT NOT NULL,
  legacy_signature TEXT,
  reason_code TEXT,
  slot INTEGER,
  block_ref TEXT,
  error TEXT,
  retry_metadata_json TEXT NOT NULL DEFAULT '{}',
  evidence_status TEXT NOT NULL,
  UNIQUE(attempt_id,state,transaction_id)
);
CREATE TRIGGER IF NOT EXISTS publication_receipts_no_update
  BEFORE UPDATE ON publication_receipts BEGIN SELECT RAISE(ABORT,'receipts are append-only'); END;
CREATE TRIGGER IF NOT EXISTS publication_receipts_no_delete
  BEFORE DELETE ON publication_receipts BEGIN SELECT RAISE(ABORT,'receipts are append-only'); END;
CREATE TABLE IF NOT EXISTS canonical_event_commitments (
  event_id INTEGER PRIMARY KEY REFERENCES animal_events(event_id),
  subject_ref TEXT NOT NULL CHECK(length(subject_ref)=64),
  source_digest TEXT NOT NULL CHECK(length(source_digest)=64),
  commitment TEXT NOT NULL UNIQUE CHECK(length(commitment)=64),
  envelope BLOB NOT NULL CHECK(length(envelope) BETWEEN 1 AND 512),
  created_at REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS canonical_event_commitments_no_update
  BEFORE UPDATE ON canonical_event_commitments BEGIN SELECT RAISE(ABORT,'canonical commitments are immutable'); END;
CREATE TRIGGER IF NOT EXISTS canonical_event_commitments_no_delete
  BEFORE DELETE ON canonical_event_commitments BEGIN SELECT RAISE(ABORT,'canonical commitments are immutable'); END;
"""

_GENERIC_ATTEMPTS_SCHEMA = """
CREATE TABLE publication_attempts (
  attempt_id TEXT PRIMARY KEY,
  publication_id TEXT NOT NULL REFERENCES publication_requests(publication_id),
  adapter_id TEXT NOT NULL,
  attempt_number INTEGER NOT NULL,
  transaction_id TEXT NOT NULL,
  payload BLOB NOT NULL CHECK(length(payload) BETWEEN 1 AND 1048576),
  metadata_json TEXT NOT NULL DEFAULT '{}',
  legacy_signature TEXT,
  legacy_signed_transaction BLOB,
  legacy_last_valid_block_height INTEGER,
  status TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(publication_id,attempt_number)
)
"""

_GENERIC_RECEIPTS_SCHEMA = """
CREATE TABLE publication_receipts (
  receipt_id TEXT PRIMARY KEY,
  publication_id TEXT NOT NULL REFERENCES publication_requests(publication_id),
  attempt_id TEXT NOT NULL REFERENCES publication_attempts(attempt_id),
  receipt_version INTEGER NOT NULL DEFAULT 1 CHECK(receipt_version=1),
  adapter_id TEXT NOT NULL,
  adapter_version TEXT NOT NULL DEFAULT '1',
  chain TEXT NOT NULL,
  commitment TEXT NOT NULL CHECK(length(commitment)=64),
  network TEXT NOT NULL,
  state TEXT NOT NULL,
  observed_at REAL NOT NULL,
  submitted_at REAL,
  confirmed_at REAL,
  verified_at REAL,
  transaction_id TEXT NOT NULL,
  legacy_signature TEXT,
  reason_code TEXT,
  slot INTEGER,
  block_ref TEXT,
  error TEXT,
  retry_metadata_json TEXT NOT NULL DEFAULT '{}',
  evidence_status TEXT NOT NULL,
  UNIQUE(attempt_id,state,transaction_id)
)
"""


class SQLitePublicationOutbox:
    """Publication persistence using the existing Store connection and lock."""

    def __init__(self, store: Store) -> None:
        self.store = store
        with store._lock:
            store.connection.executescript(_SCHEMA)
            self._upgrade_legacy_schema(store.connection)
            store.connection.commit()

    def claim_processing(self, publication_id: str, *, lease_seconds: float = 120.0) -> str | None:
        """Claim one target across Store connections; stale claims can be recovered."""
        _identifier(publication_id, "publication_id")
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 1 and 3600")
        token = secrets.token_hex(16)
        now = time.time()
        with self.store._lock:
            con = self.store.connection
            con.execute("BEGIN IMMEDIATE")
            try:
                if con.execute("SELECT 1 FROM publication_requests WHERE publication_id=?", (publication_id,)).fetchone() is None:
                    raise ValueError("publication request was not found")
                con.execute("DELETE FROM publication_processing_claims WHERE publication_id=? AND expires_at<=?", (publication_id, now))
                if con.execute("SELECT 1 FROM publication_processing_claims WHERE publication_id=?", (publication_id,)).fetchone():
                    con.commit()
                    return None
                con.execute("INSERT INTO publication_processing_claims VALUES(?,?,?)", (publication_id, token, now + lease_seconds))
                con.commit()
                return token
            except Exception:
                con.rollback()
                raise

    def release_processing(self, publication_id: str, token: str) -> None:
        _identifier(publication_id, "publication_id")
        _identifier(token, "token")
        with self.store._lock:
            self.store.connection.execute(
                "DELETE FROM publication_processing_claims WHERE publication_id=? AND token=?", (publication_id, token)
            )
            self.store.connection.commit()

    def renew_processing(self, publication_id: str, token: str, *, lease_seconds: float = 120.0) -> bool:
        """Extend only the live owner's claim; never revive an expired token."""
        _identifier(publication_id, "publication_id")
        _identifier(token, "token")
        now = time.time()
        with self.store._lock:
            con = self.store.connection
            con.execute("BEGIN IMMEDIATE")
            try:
                changed = con.execute(
                    "UPDATE publication_processing_claims SET expires_at=? "
                    "WHERE publication_id=? AND token=? AND expires_at>?",
                    (now + lease_seconds, publication_id, token, now),
                ).rowcount
                con.commit()
                return changed == 1
            except Exception:
                con.rollback()
                raise

    def owns_processing(self, publication_id: str, token: str) -> bool:
        _identifier(publication_id, "publication_id")
        _identifier(token, "token")
        with self.store._lock:
            row = self.store.connection.execute(
                "SELECT 1 FROM publication_processing_claims "
                "WHERE publication_id=? AND token=? AND expires_at>?",
                (publication_id, token, time.time()),
            ).fetchone()
        return row is not None

    @staticmethod
    def _require_live_claim(con: sqlite3.Connection, publication_id: str, token: str) -> None:
        _identifier(token, "claim_token")
        if con.execute(
            "SELECT 1 FROM publication_processing_claims "
            "WHERE publication_id=? AND token=? AND expires_at>?",
            (publication_id, token, time.time()),
        ).fetchone() is None:
            raise RuntimeError("publication processing claim was lost")

    @staticmethod
    def _upgrade_legacy_schema(con: sqlite3.Connection) -> None:
        """Add normalized target/receipt columns without rewriting old receipts."""
        con.commit()
        con.execute("PRAGMA foreign_keys=OFF")
        try:
            con.execute("BEGIN IMMEDIATE")
            request_columns = {row[1] for row in con.execute("PRAGMA table_info(publication_requests)")}
            if "chain" not in request_columns:
                con.execute("ALTER TABLE publication_requests ADD COLUMN chain TEXT NOT NULL DEFAULT 'unknown'")
            con.execute(
                "UPDATE publication_requests SET chain=CASE WHEN instr(destination,'-')>0 "
                "THEN substr(destination,1,instr(destination,'-')-1) ELSE destination END "
                "WHERE chain='unknown'"
            )
            request_columns = {row[1] for row in con.execute("PRAGMA table_info(publication_requests)")}
            if "adapter_id" not in request_columns:
                con.execute("ALTER TABLE publication_requests ADD COLUMN adapter_id TEXT NOT NULL DEFAULT ''")
            con.execute("UPDATE publication_requests SET adapter_id=destination WHERE adapter_id=''")
            receipt_columns = {row[1] for row in con.execute("PRAGMA table_info(publication_receipts)")}
            existing_receipt_columns = set(receipt_columns)
            additions = {
                "chain": "TEXT NOT NULL DEFAULT 'solana'",
                "transaction_id": "TEXT NOT NULL DEFAULT ''",
                "block_ref": "TEXT",
                "confirmed_at": "REAL",
                "error": "TEXT",
                "retry_metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            }
            for name, declaration in additions.items():
                if name not in receipt_columns:
                    con.execute(f"ALTER TABLE publication_receipts ADD COLUMN {name} {declaration}")
            attempt_columns = {row[1] for row in con.execute("PRAGMA table_info(publication_attempts)")}
            if "transaction_id" not in attempt_columns:
                SQLitePublicationOutbox._migrate_solana_attempts(con, existing_receipt_columns)
            violations = con.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise sqlite3.IntegrityError("publication schema migration left broken foreign keys")
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.execute("PRAGMA foreign_keys=ON")

    @staticmethod
    def _migrate_solana_attempts(
        con: sqlite3.Connection, existing_receipt_columns: set[str]
    ) -> None:
        """Preserve Solana attempts while moving storage to the generic columns."""
        attempt_count = con.execute("SELECT COUNT(*) FROM publication_attempts").fetchone()[0]
        receipt_count = con.execute("SELECT COUNT(*) FROM publication_receipts").fetchone()[0]
        orphan_attempt = con.execute(
            "SELECT 1 FROM publication_attempts a LEFT JOIN publication_requests r USING(publication_id) "
            "WHERE r.publication_id IS NULL LIMIT 1"
        ).fetchone()
        orphan_receipt = con.execute(
            "SELECT 1 FROM publication_receipts p "
            "LEFT JOIN publication_requests r USING(publication_id) "
            "LEFT JOIN publication_attempts a ON a.attempt_id=p.attempt_id "
            "AND a.publication_id=p.publication_id "
            "WHERE r.publication_id IS NULL OR a.attempt_id IS NULL LIMIT 1"
        ).fetchone()
        if orphan_attempt is not None or orphan_receipt is not None:
            raise sqlite3.IntegrityError("legacy publication journal contains orphaned attempts or receipts")
        con.execute("DROP TRIGGER IF EXISTS publication_receipts_no_update")
        con.execute("DROP TRIGGER IF EXISTS publication_receipts_no_delete")
        con.execute("ALTER TABLE publication_receipts RENAME TO publication_receipts_legacy_mvp1")
        con.execute("ALTER TABLE publication_attempts RENAME TO publication_attempts_legacy_mvp1")
        con.execute(_GENERIC_ATTEMPTS_SCHEMA)
        con.execute(_GENERIC_RECEIPTS_SCHEMA)
        for row in con.execute(
            "SELECT a.*,COALESCE(r.adapter_id,r.destination) AS adapter_id "
            "FROM publication_attempts_legacy_mvp1 a "
            "JOIN publication_requests r USING(publication_id)"
        ).fetchall():
            receipt_transaction_ids: list[str] = []
            if "transaction_id" in existing_receipt_columns:
                receipt_transaction_ids = [
                    item[0] for item in con.execute(
                        "SELECT DISTINCT transaction_id FROM publication_receipts_legacy_mvp1 "
                        "WHERE attempt_id=? AND transaction_id IS NOT NULL AND transaction_id<>''",
                        (row["attempt_id"],),
                    ).fetchall()
                ]
            if len(receipt_transaction_ids) > 1:
                raise sqlite3.IntegrityError("legacy attempt has conflicting normalized transaction identifiers")
            if receipt_transaction_ids and receipt_transaction_ids[0] != row["signature"]:
                raise sqlite3.IntegrityError(
                    "legacy receipt transaction identifier does not match its persisted Solana signature"
                )
            transaction_id = receipt_transaction_ids[0] if receipt_transaction_ids else row["signature"]
            metadata = json.dumps(
                {"last_valid_block_height": row["last_valid_block_height"]},
                sort_keys=True, separators=(",", ":"),
            )
            con.execute(
                "INSERT INTO publication_attempts(attempt_id,publication_id,adapter_id,attempt_number,transaction_id,payload,metadata_json,legacy_signature,legacy_signed_transaction,legacy_last_valid_block_height,status,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["attempt_id"], row["publication_id"], row["adapter_id"], row["attempt_number"],
                 transaction_id, row["signed_transaction"], metadata, row["signature"],
                 row["signed_transaction"], row["last_valid_block_height"], row["status"], row["created_at"]),
            )
        for row in con.execute(
            "SELECT p.*,r.chain AS request_chain FROM publication_receipts_legacy_mvp1 p "
            "JOIN publication_requests r USING(publication_id)"
        ).fetchall():
            transaction_id = (
                row["transaction_id"] if "transaction_id" in existing_receipt_columns
                and row["transaction_id"] else row["signature"]
            )
            confirmed_at = (
                row["confirmed_at"] if "confirmed_at" in existing_receipt_columns
                else (row["observed_at"] if row["state"] == PublicationState.CONFIRMED.value else None)
            )
            block_ref = (
                row["block_ref"] if "block_ref" in existing_receipt_columns and row["block_ref"] is not None
                else (str(row["slot"]) if row["slot"] is not None else None)
            )
            error = (
                row["error"] if "error" in existing_receipt_columns and row["error"] is not None
                else row["reason_code"]
            )
            retry_metadata_json = (
                row["retry_metadata_json"] if "retry_metadata_json" in existing_receipt_columns
                else "{}"
            )
            chain = (
                row["chain"] if "chain" in existing_receipt_columns and row["chain"]
                else row["request_chain"]
            )
            con.execute(
                "INSERT INTO publication_receipts(receipt_id,publication_id,attempt_id,receipt_version,adapter_id,adapter_version,chain,commitment,network,state,observed_at,submitted_at,confirmed_at,verified_at,transaction_id,legacy_signature,reason_code,slot,block_ref,error,retry_metadata_json,evidence_status) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["receipt_id"], row["publication_id"], row["attempt_id"], row["receipt_version"],
                 row["adapter_id"], row["adapter_version"], chain, row["commitment"], row["network"],
                 row["state"], row["observed_at"], row["submitted_at"], confirmed_at, row["verified_at"],
                 transaction_id, row["signature"], row["reason_code"], row["slot"],
                 block_ref, error, retry_metadata_json,
                 row["evidence_status"]),
            )
        if con.execute("SELECT COUNT(*) FROM publication_attempts").fetchone()[0] != attempt_count:
            raise sqlite3.IntegrityError("publication attempt migration changed the journal row count")
        if con.execute("SELECT COUNT(*) FROM publication_receipts").fetchone()[0] != receipt_count:
            raise sqlite3.IntegrityError("publication receipt migration changed the journal row count")
        con.execute("DROP TABLE publication_receipts_legacy_mvp1")
        con.execute("DROP TABLE publication_attempts_legacy_mvp1")
        con.execute("CREATE TRIGGER publication_receipts_no_update BEFORE UPDATE ON publication_receipts BEGIN SELECT RAISE(ABORT,'receipts are append-only'); END")
        con.execute("CREATE TRIGGER publication_receipts_no_delete BEFORE DELETE ON publication_receipts BEGIN SELECT RAISE(ABORT,'receipts are append-only'); END")

    def enqueue_event(
        self,
        event_id: int,
        *,
        destination: str,
        network: str,
        chain: str | None = None,
        idempotency_key: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        _identifier(destination, "destination")
        _identifier(network, "network")
        chain = _chain_for_destination(destination, chain)
        target_id = _target_id(chain, destination)
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
                    "SELECT * FROM publication_requests WHERE event_id=? AND network=? AND chain=? AND (adapter_id=? OR (adapter_id='' AND destination=?))",
                    (event_id, network, chain, destination, destination),
                ).fetchone()
                if existing is not None:
                    if existing["chain"] != chain:
                        raise ValueError("publication target already exists for a different chain")
                    con.commit()
                    return _request_dict(existing)
                event = _verified_event_prefix(con, event_id)
                canonical = _canonical_for_event(con, event, created_at)
                publication_id = secrets.token_hex(16)
                key = idempotency_key or f"event-{event_id}-{target_id}-{network}"
                con.execute(
                    "INSERT INTO publication_requests(publication_id,event_id,chain,adapter_id,destination,network,idempotency_key,subject_ref,source_digest,commitment,envelope,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (publication_id, event_id, chain, destination, target_id, network, key, canonical["subject_ref"],
                     event["hash"], canonical["commitment"], canonical["envelope"], PublicationState.QUEUED.value, created_at),
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
        chain: str | None = None,
        idempotency_key: str,
        timestamp: float | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Atomically append one Core event with its optional publication intent."""
        _identifier(destination, "destination")
        _identifier(network, "network")
        chain = _chain_for_destination(destination, chain)
        target_id = _target_id(chain, destination)
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
                        existing["chain"] == chain
                        and
                        (existing["adapter_id"] or existing["destination"]) == destination
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
                canonical = _canonical_for_event(con, verified_event, created_at)
                publication_id = secrets.token_hex(16)
                con.execute(
                    "INSERT INTO publication_requests(publication_id,event_id,chain,adapter_id,destination,network,idempotency_key,subject_ref,source_digest,commitment,envelope,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (publication_id, event.event_id, chain, destination, target_id, network, idempotency_key,
                     canonical["subject_ref"], verified_event["hash"], canonical["commitment"], canonical["envelope"],
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
        request = self.get(publication_id)
        if request is None:
            raise ValueError("publication request was not found")
        return self._prepare_attempt(
            publication_id,
            adapter_id=request["adapter_id"],
            transaction_id=signature,
            payload=signed_transaction,
            metadata={"last_valid_block_height": last_valid_block_height},
            legacy_signature=signature,
            legacy_signed_transaction=signed_transaction,
            legacy_last_valid_block_height=last_valid_block_height,
            now=now,
        )

    def prepare_publication_attempt(
        self,
        publication_id: str,
        *,
        adapter_id: str,
        transaction_id: str,
        payload: bytes,
        metadata: dict[str, Any] | None = None,
        claim_token: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Persist an adapter-neutral prepared payload before network submission."""
        return self._prepare_attempt(
            publication_id, adapter_id=adapter_id, transaction_id=transaction_id,
            payload=payload, metadata={} if metadata is None else metadata,
            claim_token=claim_token, now=now,
        )

    def _prepare_attempt(
        self,
        publication_id: str,
        *,
        adapter_id: str,
        transaction_id: str,
        payload: bytes,
        metadata: dict[str, Any],
        legacy_signature: str | None = None,
        legacy_signed_transaction: bytes | None = None,
        legacy_last_valid_block_height: int | None = None,
        claim_token: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        _identifier(publication_id, "publication_id")
        _identifier(adapter_id, "adapter_id")
        _identifier(transaction_id, "transaction_id")
        if type(payload) is not bytes or not 1 <= len(payload) <= 1_048_576:
            raise ValueError("payload must be between 1 byte and 1 MiB")
        if type(metadata) is not dict:
            raise ValueError("metadata must be an object")
        metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        timestamp = time.time() if now is None else _timestamp(now, "now")
        attempt_id = secrets.token_hex(16)
        with self.store._lock:
            con = self.store.connection
            con.execute("BEGIN IMMEDIATE")
            try:
                if claim_token is not None:
                    self._require_live_claim(con, publication_id, claim_token)
                request = con.execute(
                    "SELECT status,adapter_id,destination FROM publication_requests WHERE publication_id=?", (publication_id,)
                ).fetchone()
                if request is None:
                    raise ValueError("publication request was not found")
                target_adapter = request["adapter_id"] or request["destination"]
                if adapter_id != target_adapter:
                    raise ValueError("attempt adapter does not match the publication target")
                current = PublicationState(request["status"])
                require_transition(current, PublicationState.PREPARED)
                attempt_number = con.execute(
                    "SELECT COALESCE(MAX(attempt_number),0)+1 FROM publication_attempts WHERE publication_id=?",
                    (publication_id,),
                ).fetchone()[0]
                con.execute(
                    "INSERT INTO publication_attempts(attempt_id,publication_id,adapter_id,attempt_number,transaction_id,payload,metadata_json,legacy_signature,legacy_signed_transaction,legacy_last_valid_block_height,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (attempt_id, publication_id, adapter_id, attempt_number, transaction_id, payload, metadata_json,
                     legacy_signature, legacy_signed_transaction, legacy_last_valid_block_height,
                     PublicationState.PREPARED.value, timestamp),
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
        return _attempt_dict(row) if row is not None else None

    def latest_attempt(self, publication_id: str) -> dict[str, Any] | None:
        _identifier(publication_id, "publication_id")
        with self.store._lock:
            row = self.store.connection.execute(
                "SELECT * FROM publication_attempts WHERE publication_id=? ORDER BY attempt_number DESC LIMIT 1",
                (publication_id,),
            ).fetchone()
        return _attempt_dict(row) if row is not None else None

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
                request_valid = (
                    commitment.digest == request["commitment"]
                    and serialize_public_envelope(public_envelope(commitment)) == request["envelope"]
                )
                canonical = self.store.connection.execute(
                    "SELECT subject_ref,source_digest,commitment,envelope FROM canonical_event_commitments WHERE event_id=?",
                    (request["event_id"],),
                ).fetchone()
                if canonical is None:
                    return request_valid
                return request_valid and (
                    canonical["subject_ref"] == request["subject_ref"]
                    and canonical["source_digest"] == request["source_digest"]
                    and canonical["commitment"] == request["commitment"]
                    and bytes(canonical["envelope"]) == request["envelope"]
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
        transaction_id: str | None = None,
        adapter_id: str = "solana-memo",
        block_ref: str | None = None,
        error: str | None = None,
        retry_metadata: dict[str, Any] | None = None,
        evidence_status: str = "ASSUMED",
        claim_token: str | None = None,
        now: float | None = None,
    ) -> None:
        if not isinstance(state, PublicationState):
            raise ValueError("state must be a PublicationState")
        if reason_code is not None and (type(reason_code) is not str or _RECEIPT_REASON.fullmatch(reason_code) is None):
            raise ValueError("reason_code must be an allowlisted reason identifier")
        _identifier(adapter_id, "adapter_id")
        if transaction_id is not None:
            _identifier(transaction_id, "transaction_id")
        if block_ref is not None:
            _identifier(block_ref, "block_ref")
        if error is not None and (type(error) is not str or _RECEIPT_REASON.fullmatch(error) is None):
            raise ValueError("error must be a sanitized reason identifier")
        retry_metadata = {} if retry_metadata is None else retry_metadata
        if type(retry_metadata) is not dict:
            raise ValueError("retry_metadata must be an object")
        retry_metadata_json = json.dumps(retry_metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
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
                if claim_token is not None:
                    self._require_live_claim(con, publication_id, claim_token)
                request = con.execute(
                    "SELECT status,chain,adapter_id,destination,commitment,network FROM publication_requests WHERE publication_id=?", (publication_id,)
                ).fetchone()
                attempt = con.execute(
                    "SELECT adapter_id,transaction_id,legacy_signature FROM publication_attempts WHERE attempt_id=? AND publication_id=?",
                    (attempt_id, publication_id),
                ).fetchone()
                if request is None or attempt is None:
                    raise ValueError("publication attempt was not found")
                if adapter_id != (request["adapter_id"] or request["destination"]):
                    raise ValueError("receipt adapter does not match the publication target")
                if adapter_id != attempt["adapter_id"]:
                    raise ValueError("receipt adapter does not match the persisted attempt")
                latest_attempt = con.execute(
                    "SELECT attempt_id FROM publication_attempts WHERE publication_id=? "
                    "ORDER BY attempt_number DESC LIMIT 1",
                    (publication_id,),
                ).fetchone()
                if latest_attempt is None or latest_attempt["attempt_id"] != attempt_id:
                    raise ValueError("receipt attempt is no longer the active publication attempt")
                if transaction_id is not None and transaction_id != attempt["transaction_id"]:
                    raise ValueError("receipt transaction_id does not match the persisted attempt")
                current = PublicationState(request["status"])
                require_transition(current, state)
                prior_submission = con.execute(
                    "SELECT MIN(observed_at) FROM publication_receipts WHERE attempt_id=? AND state=?",
                    (attempt_id, PublicationState.RPC_ACCEPTED.value),
                ).fetchone()[0]
                submitted_at = timestamp if state is PublicationState.RPC_ACCEPTED else prior_submission
                prior_confirmation = con.execute(
                    "SELECT MIN(observed_at) FROM publication_receipts WHERE attempt_id=? AND state=?",
                    (attempt_id, PublicationState.CONFIRMED.value),
                ).fetchone()[0]
                confirmed_at = timestamp if state is PublicationState.CONFIRMED else prior_confirmation
                verified_at = timestamp if state is PublicationState.VERIFIED else None
                transaction_id = transaction_id or attempt["transaction_id"]
                block_ref = block_ref if block_ref is not None else (str(slot) if slot is not None else None)
                con.execute(
                    "INSERT INTO publication_receipts(receipt_id,publication_id,attempt_id,receipt_version,adapter_id,adapter_version,chain,commitment,network,state,observed_at,submitted_at,confirmed_at,verified_at,transaction_id,legacy_signature,reason_code,slot,block_ref,error,retry_metadata_json,evidence_status) "
                    "VALUES(?,?,?,1,?,'1',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (receipt_id, publication_id, attempt_id, adapter_id, request["chain"], request["commitment"], request["network"],
                     state.value, timestamp, submitted_at, confirmed_at, verified_at, transaction_id, attempt["legacy_signature"], reason_code,
                     slot, block_ref, error or reason_code, retry_metadata_json, evidence_status),
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
                "SELECT receipt_id,publication_id,attempt_id,receipt_version,adapter_id,adapter_version,chain,commitment,network,state,observed_at,submitted_at,confirmed_at,verified_at,legacy_signature,transaction_id,reason_code,slot,block_ref,error,retry_metadata_json,evidence_status "
                "FROM publication_receipts WHERE publication_id=? ORDER BY observed_at,receipt_id",
                (publication_id,),
            ).fetchall()
        result = [dict(row) for row in rows]
        for receipt in result:
            receipt["signature"] = receipt.pop("legacy_signature")
            if not receipt["transaction_id"]:
                receipt["transaction_id"] = receipt["signature"]
            if receipt["block_ref"] is None and receipt["slot"] is not None:
                receipt["block_ref"] = str(receipt["slot"])
            if receipt["confirmed_at"] is None and receipt["state"] == PublicationState.CONFIRMED.value:
                receipt["confirmed_at"] = receipt["observed_at"]
        return result


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
    result["target_id"] = result["destination"]
    if not result.get("adapter_id"):
        result["adapter_id"] = result["destination"]
    result["destination"] = result["adapter_id"]
    return result


def _attempt_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["payload"] = bytes(result["payload"])
    result["metadata"] = json.loads(result.pop("metadata_json"))
    result["signature"] = result["legacy_signature"]
    result["signed_transaction"] = result["legacy_signed_transaction"]
    result["last_valid_block_height"] = result["legacy_last_valid_block_height"]
    return result


def _chain_for_destination(destination: str, chain: str | None) -> str:
    if chain is not None:
        _identifier(chain, "chain")
        return chain
    return destination.split("-", 1)[0]


def _target_id(chain: str, destination: str) -> str:
    raw = f"{len(chain)}:{chain}{destination}".encode("utf-8")
    return "target-" + hashlib.sha256(raw).hexdigest()


def _canonical_for_event(
    con: sqlite3.Connection, event: dict[str, Any], created_at: float
) -> dict[str, Any]:
    """Reuse one locally bound commitment across every target of an event.

    Existing rows are adopted only when their binding is internally consistent
    and unambiguous. Conflicting legacy target commitments fail closed rather
    than rewriting append-only receipts or asserting they are equivalent.
    """
    event_id = event["event_id"]
    row = con.execute(
        "SELECT * FROM canonical_event_commitments WHERE event_id=?", (event_id,)
    ).fetchone()
    if row is not None:
        canonical = dict(row)
        try:
            binding = create_commitment_v1(event["hash"], canonical["subject_ref"])
            expected_envelope = serialize_public_envelope(public_envelope(binding))
        except (TypeError, ValueError) as exc:
            raise ValueError("canonical event commitment failed local binding verification") from exc
        if (canonical["source_digest"] != event["hash"]
                or canonical["commitment"] != binding.digest
                or bytes(canonical["envelope"]) != expected_envelope):
            raise ValueError("canonical event commitment failed local binding verification")
        prior = con.execute(
            "SELECT DISTINCT subject_ref,source_digest,commitment,envelope FROM publication_requests WHERE event_id=?",
            (event_id,),
        ).fetchall()
        if any(
            item["subject_ref"] != canonical["subject_ref"]
            or item["source_digest"] != canonical["source_digest"]
            or item["commitment"] != canonical["commitment"]
            or bytes(item["envelope"]) != bytes(canonical["envelope"])
            for item in prior
        ):
            raise ValueError("publication target binding conflicts with the canonical event commitment")
        return canonical
    prior = con.execute(
        "SELECT DISTINCT subject_ref,source_digest,commitment,envelope FROM publication_requests WHERE event_id=?",
        (event_id,),
    ).fetchall()
    if len(prior) > 1:
        raise ValueError("legacy publication targets have conflicting commitments; refusing to add a multichain target")
    if prior:
        legacy = dict(prior[0])
        if legacy["source_digest"] != event["hash"]:
            raise ValueError("legacy publication commitment does not match the verified event")
        commitment = create_commitment_v1(event["hash"], legacy["subject_ref"])
        envelope = serialize_public_envelope(public_envelope(commitment))
        if commitment.digest != legacy["commitment"] or envelope != bytes(legacy["envelope"]):
            raise ValueError("legacy publication commitment binding failed verification")
        values = (legacy["subject_ref"], event["hash"], commitment.digest, envelope)
    else:
        subject_ref = new_subject_ref()
        commitment = create_commitment_v1(event["hash"], subject_ref)
        values = (subject_ref, event["hash"], commitment.digest,
                  serialize_public_envelope(public_envelope(commitment)))
    con.execute(
        "INSERT INTO canonical_event_commitments(event_id,subject_ref,source_digest,commitment,envelope,created_at) VALUES(?,?,?,?,?,?)",
        (event_id, *values, created_at),
    )
    result = con.execute(
        "SELECT * FROM canonical_event_commitments WHERE event_id=?", (event_id,)
    ).fetchone()
    return dict(result)


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
