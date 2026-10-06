"""Auditable animal event chain and future adapter interfaces."""

from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Protocol

from .contracts import EvidenceStatus


EVENT_TYPES = frozenset({
    "ANIMAL_CREATED", "OWNER_CHANGED", "WEIGHT_RECORDED", "VACCINATION",
    "HEALTH_EVENT", "TRANSFER", "SLAUGHTER", "VIRTUAL_FENCE_SIMULATED",
})
GENESIS_HASH = "0" * 64
EVENT_CONTRACT_V1 = "v1"


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


class EventSigner(Protocol):
    def sign(self, digest: bytes) -> bytes: ...


@dataclass(frozen=True, slots=True)
class AnimalEvent:
    event_id: int
    animal_id: str
    event_type: str
    timestamp: float
    payload: dict[str, Any]
    previous_hash: str
    hash: str
    signature: str | None = None


@dataclass(frozen=True, slots=True)
class LocalChainEvidence:
    """Local hash-chain verification summary; this is not a public attestation."""

    valid: bool
    head_digest: str | None
    event_count: int
    algorithm: str = "sha256"
    version: int = 1
    evidence_status: EvidenceStatus = EvidenceStatus.VALIDATED

    def __post_init__(self) -> None:
        if type(self.valid) is not bool:
            raise ValueError("valid must be a boolean")
        if self.head_digest is not None and (
            type(self.head_digest) is not str or _HASH_PATTERN.fullmatch(self.head_digest) is None
        ):
            raise ValueError("head_digest must be a lowercase SHA-256 digest")
        if type(self.event_count) is not int or self.event_count < 0:
            raise ValueError("event_count must be a non-negative integer")
        if type(self.algorithm) is not str or len(self.algorithm) > 32:
            raise ValueError("algorithm must be a bounded identifier")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be a positive integer")
        if not isinstance(self.evidence_status, EvidenceStatus):
            raise ValueError("evidence_status must be an EvidenceStatus")


def canonical_event(animal_id: str, event_type: str, timestamp: float,
                    payload: dict[str, Any], previous_hash: str,
                    *, schema_version: str = EVENT_CONTRACT_V1) -> bytes:
    _validate_contract_input(animal_id, event_type, timestamp, payload,
                             previous_hash, schema_version)
    document = {
        "animal_id": animal_id,
        "event_type": event_type,
        "timestamp": timestamp,
        "payload": payload,
        "previous_hash": previous_hash,
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def event_digest(animal_id: str, event_type: str, timestamp: float,
                 payload: dict[str, Any], previous_hash: str,
                 *, schema_version: str = EVENT_CONTRACT_V1) -> str:
    return hashlib.sha256(canonical_event(animal_id, event_type, timestamp,
                                          payload, previous_hash,
                                          schema_version=schema_version)).hexdigest()


def _validate_contract_input(animal_id: str, event_type: str, timestamp: float,
                             payload: dict[str, Any], previous_hash: str,
                             schema_version: str) -> None:
    if schema_version != EVENT_CONTRACT_V1:
        raise ValueError(f"unsupported event schema_version: {schema_version}")
    if not isinstance(animal_id, str) or not animal_id.strip():
        raise ValueError("animal_id must be a non-empty string")
    if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
        raise ValueError(f"unsupported event_type: {event_type}")
    if not _finite_number(timestamp):
        raise ValueError("timestamp must be a finite number")
    if not isinstance(previous_hash, str):
        raise ValueError("previous_hash must be a string")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    def validate_json(value: Any) -> None:
        if value is None or isinstance(value, (str, bool, int)):
            return
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("non-finite JSON number")
            return
        if isinstance(value, list):
            for item in value:
                validate_json(item)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError("JSON object keys must be strings")
                validate_json(item)
            return
        raise ValueError(f"unsupported JSON value: {type(value).__name__}")

    try:
        validate_json(payload)
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False, allow_nan=False)
    except (RecursionError, TypeError, ValueError) as exc:
        raise ValueError("payload must contain finite JSON-compatible values with string keys") from exc


def make_cryptographic_id() -> str:
    """Opaque random identity; signing/key custody is a future interface."""
    return secrets.token_hex(32)


def append_event(connection: sqlite3.Connection, animal_id: str,
                 event_type: str, payload: dict[str, Any],
                 timestamp: float | None = None, *, commit: bool = True) -> AnimalEvent:
    if not isinstance(animal_id, str) or not animal_id.strip():
        raise ValueError("animal_id must be a non-empty string")
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unsupported event_type: {event_type}")
    timestamp = time.time() if timestamp is None else timestamp
    if not _finite_number(timestamp):
        raise ValueError("timestamp must be a finite number")
    timestamp = float(timestamp)
    _validate_contract_input(animal_id, event_type, timestamp, payload,
                             GENESIS_HASH, EVENT_CONTRACT_V1)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False)
    owns_transaction = not connection.in_transaction
    if owns_transaction:
        # Reserve SQLite's single-writer lock before reading the chain head.
        # WAL and a process-local RLock alone cannot make read -> hash -> write atomic.
        connection.execute("BEGIN IMMEDIATE")
    try:
        if not verify_event_chain(connection, animal_id):
            raise ValueError("cannot append to an invalid event chain")
        row = connection.execute(
            "SELECT hash FROM animal_events WHERE animal_id=? ORDER BY event_id DESC LIMIT 1",
            (animal_id,),
        ).fetchone()
        previous_hash = row[0] if row else GENESIS_HASH
        digest = event_digest(animal_id, event_type, timestamp, payload, previous_hash)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(animal_events)")}
        if "schema_version" in columns:
            cursor = connection.execute(
                "INSERT INTO animal_events(animal_id,event_type,timestamp,payload,previous_hash,hash,signature,schema_version) VALUES(?,?,?,?,?,?,NULL,?)",
                (animal_id, event_type, timestamp, encoded, previous_hash, digest, EVENT_CONTRACT_V1),
            )
        else:
            cursor = connection.execute(
                "INSERT INTO animal_events(animal_id,event_type,timestamp,payload,previous_hash,hash,signature) VALUES(?,?,?,?,?,?,NULL)",
                (animal_id, event_type, timestamp, encoded, previous_hash, digest),
            )
    except Exception:
        if owns_transaction:
            connection.rollback()
        raise
    if commit:
        connection.commit()
    return AnimalEvent(cursor.lastrowid, animal_id, event_type, timestamp,
                       payload, previous_hash, digest)


def verify_event_chain(connection: sqlite3.Connection, animal_id: str) -> bool:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(animal_events)")}
    version_sql = ",schema_version" if "schema_version" in columns else ",NULL"
    rows = connection.execute(
        "SELECT animal_id,event_type,timestamp,payload,previous_hash,hash" + version_sql +
        " FROM animal_events WHERE animal_id=? ORDER BY event_id", (animal_id,),
    )
    previous_hash = GENESIS_HASH
    for event_animal, event_type, timestamp, payload_json, stored_previous, stored_hash, schema_version in rows:
        try:
            if schema_version not in (None, EVENT_CONTRACT_V1):
                return False
            payload = json.loads(payload_json, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            if not isinstance(payload, dict):
                return False
            if stored_previous != previous_hash:
                return False
            calculated = event_digest(event_animal, event_type, timestamp, payload,
                                      previous_hash, schema_version=EVENT_CONTRACT_V1)
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
        if calculated != stored_hash:
            return False
        previous_hash = stored_hash
    return True


def event_chain_evidence(
    connection: sqlite3.Connection, animal_id: str
) -> LocalChainEvidence | None:
    """Return a PII-free summary of a local event chain, without a trust claim."""
    rows = connection.execute(
        "SELECT hash FROM animal_events WHERE animal_id=? ORDER BY event_id", (animal_id,)
    ).fetchall()
    if not rows:
        return None
    return LocalChainEvidence(
        valid=verify_event_chain(connection, animal_id),
        head_digest=str(rows[-1][0]),
        event_count=len(rows),
    )
