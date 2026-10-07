"""SQLite nonce reservations shared by EVM targets using one signer.

The caller must hold a live publication processing claim. A reservation is
temporary until its token is recorded in a durable publication attempt; after
that, it is retained so a restart cannot allocate the same nonce again.
"""

from __future__ import annotations

import json
import math
import re
import secrets
import sqlite3
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sqlite_store import Store


_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z", re.ASCII)
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z", re.ASCII)
_MAX_NONCE = 2**63 - 1  # SQLite INTEGER is signed 64-bit.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS evm_nonce_reservations (
  network TEXT NOT NULL,
  sender TEXT NOT NULL,
  nonce INTEGER NOT NULL CHECK(nonce >= 0),
  publication_id TEXT NOT NULL REFERENCES publication_requests(publication_id),
  token TEXT NOT NULL UNIQUE,
  expires_at REAL NOT NULL,
  PRIMARY KEY(network,sender,nonce),
  UNIQUE(publication_id)
);
CREATE INDEX IF NOT EXISTS idx_evm_nonce_reservations_expiry
  ON evm_nonce_reservations(expires_at);
CREATE TABLE IF NOT EXISTS evm_nonce_submission_locks (
  network TEXT NOT NULL,
  sender TEXT NOT NULL,
  token TEXT NOT NULL,
  expires_at REAL NOT NULL,
  PRIMARY KEY(network,sender)
);
"""


class EVMNonceCoordinator:
    """Allocate distinct nonces across Store connections and process restarts."""

    def __init__(self, store: Store) -> None:
        self.store = store
        with store._lock:
            store.connection.executescript(_SCHEMA)
            store.connection.commit()

    def reserve(
        self,
        publication_id: str,
        network: str,
        sender: str,
        pending_nonce: int,
        *,
        nonce_scope: str | None = None,
        lease_seconds: float = 120.0,
    ) -> tuple[int, str]:
        """Reserve the smallest free nonce at or above the RPC pending nonce.

        A live processing claim is required. An already reserved publication
        receives its original nonce and token; recovery must use its durable
        signed attempt rather than silently assigning a replacement nonce.
        """
        if not isinstance(publication_id, str) or _IDENTIFIER.fullmatch(publication_id) is None:
            raise ValueError("publication_id must be a valid identifier")
        if not isinstance(network, str) or _IDENTIFIER.fullmatch(network) is None:
            raise ValueError("network must be a valid identifier")
        if nonce_scope is None:
            nonce_scope = network
        if not isinstance(nonce_scope, str) or _IDENTIFIER.fullmatch(nonce_scope) is None:
            raise ValueError("nonce_scope must be a valid identifier")
        if not isinstance(sender, str) or _ADDRESS.fullmatch(sender) is None:
            raise ValueError("sender must be a 20-byte EVM address")
        if type(pending_nonce) is not int or not 0 <= pending_nonce <= _MAX_NONCE:
            raise ValueError("pending_nonce must fit a non-negative SQLite integer")
        if (
            type(lease_seconds) not in (int, float)
            or not math.isfinite(lease_seconds)
            or not 1 <= lease_seconds <= 3600
        ):
            raise ValueError("lease_seconds must be between 1 and 3600")

        normalized_sender = sender.lower()
        now = time.time()
        with self.store._lock:
            con = self.store.connection
            con.execute("BEGIN IMMEDIATE")
            try:
                request = con.execute(
                    "SELECT network FROM publication_requests WHERE publication_id=?",
                    (publication_id,),
                ).fetchone()
                if request is None:
                    raise ValueError("publication request was not found")
                if request["network"] != network:
                    raise ValueError("nonce network does not match the publication target")
                if con.execute(
                    "SELECT 1 FROM publication_processing_claims "
                    "WHERE publication_id=? AND expires_at>?",
                    (publication_id, now),
                ).fetchone() is None:
                    raise RuntimeError("publication processing claim is required for nonce reservation")

                self._reap_unpersisted(con, now)
                existing = con.execute(
                    "SELECT network,sender,nonce,token FROM evm_nonce_reservations "
                    "WHERE publication_id=?",
                    (publication_id,),
                ).fetchone()
                if existing is not None:
                    if existing["network"] != nonce_scope or existing["sender"] != normalized_sender:
                        raise ValueError("publication already reserved with a different network or signer")
                    con.commit()
                    return int(existing["nonce"]), str(existing["token"])

                used = con.execute(
                    "SELECT nonce FROM evm_nonce_reservations "
                    "WHERE network=? AND sender=? AND nonce>=? ORDER BY nonce",
                    (nonce_scope, normalized_sender, pending_nonce),
                )
                nonce = pending_nonce
                for row in used:
                    reserved = int(row["nonce"])
                    if reserved > nonce:
                        break
                    if reserved == nonce:
                        if nonce == _MAX_NONCE:
                            raise OverflowError("no EVM nonce remains in SQLite integer range")
                        nonce += 1

                token = secrets.token_hex(16)
                con.execute(
                    "INSERT INTO evm_nonce_reservations"
                    "(network,sender,nonce,publication_id,token,expires_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (nonce_scope, normalized_sender, nonce, publication_id, token, now + lease_seconds),
                )
                con.commit()
                return nonce, token
            except Exception:
                con.rollback()
                raise

    def submit_in_nonce_order(
        self,
        publication_id: str,
        nonce: int,
        reservation_token: str,
        current_nonce: Callable[[], int],
        submit: Callable[[], object],
        *,
        lease_seconds: float = 130.0,
    ) -> object:
        """Serialize one sender's Arbitrum sends and require the current nonce.

        A short SQLite lease is shared across Store connections and processes.
        The RPC calls happen outside the database transaction while the lease
        prevents another RIOSE worker from overtaking this send.
        """
        if not isinstance(publication_id, str) or _IDENTIFIER.fullmatch(publication_id) is None:
            raise ValueError("publication_id must be a valid identifier")
        if type(nonce) is not int or not 0 <= nonce <= _MAX_NONCE:
            raise ValueError("nonce must fit a non-negative SQLite integer")
        if not isinstance(reservation_token, str) or re.fullmatch(r"[0-9a-f]{32}", reservation_token) is None:
            raise ValueError("nonce reservation token is invalid")
        if not callable(current_nonce) or not callable(submit):
            raise TypeError("nonce callbacks must be callable")
        if (type(lease_seconds) not in (int, float) or not math.isfinite(lease_seconds)
                or not 1 <= lease_seconds <= 3600):
            raise ValueError("submission lease must be between 1 and 3600 seconds")

        lock_token = secrets.token_hex(16)
        now = time.time()
        with self.store._lock:
            con = self.store.connection
            con.execute("BEGIN IMMEDIATE")
            try:
                reservation = con.execute(
                    "SELECT nonce,token,network,sender FROM evm_nonce_reservations WHERE publication_id=?",
                    (publication_id,),
                ).fetchone()
                if (reservation is None or int(reservation["nonce"]) != nonce
                        or reservation["token"] != reservation_token):
                    raise RuntimeError("EVM nonce reservation did not match the signed attempt")
                active = con.execute(
                    "SELECT token,expires_at FROM evm_nonce_submission_locks "
                    "WHERE network=? AND sender=?",
                    (reservation["network"], reservation["sender"]),
                ).fetchone()
                if active is not None and float(active["expires_at"]) > now:
                    raise RuntimeError("another Arbitrum sender submission is in progress")
                con.execute(
                    "DELETE FROM evm_nonce_submission_locks WHERE network=? AND sender=?",
                    (reservation["network"], reservation["sender"]),
                )
                con.execute(
                    "INSERT INTO evm_nonce_submission_locks(network,sender,token,expires_at) "
                    "VALUES(?,?,?,?)",
                    (reservation["network"], reservation["sender"], lock_token, now + lease_seconds),
                )
                con.commit()
            except Exception:
                con.rollback()
                raise
        try:
            observed_nonce = current_nonce()
            if observed_nonce != nonce:
                raise RuntimeError("EVM nonce is not current; wait for the lower nonce")
            with self.store._lock:
                con = self.store.connection
                con.execute("BEGIN IMMEDIATE")
                try:
                    lock = con.execute(
                        "SELECT expires_at FROM evm_nonce_submission_locks "
                        "WHERE network=? AND sender=? AND token=?",
                        (reservation["network"], reservation["sender"], lock_token),
                    ).fetchone()
                    if lock is None or float(lock["expires_at"]) <= time.time():
                        raise RuntimeError("Arbitrum sender submission lease expired before send")
                    con.execute(
                        "UPDATE evm_nonce_submission_locks SET expires_at=? "
                        "WHERE network=? AND sender=? AND token=?",
                        (time.time() + lease_seconds, reservation["network"],
                         reservation["sender"], lock_token),
                    )
                    con.commit()
                except Exception:
                    con.rollback()
                    raise
            return submit()
        finally:
            with self.store._lock:
                con = self.store.connection
                con.execute("BEGIN IMMEDIATE")
                try:
                    con.execute(
                        "DELETE FROM evm_nonce_submission_locks "
                        "WHERE network=? AND sender=? AND token=?",
                        (reservation["network"], reservation["sender"], lock_token),
                    )
                    con.commit()
                except Exception:
                    con.rollback()
                    raise

    @staticmethod
    def _reap_unpersisted(con: sqlite3.Connection, now: float) -> None:
        """Recycle only expired reservations with no live claim or attempt."""
        rows = con.execute(
            "SELECT network,sender,nonce,publication_id,token "
            "FROM evm_nonce_reservations WHERE expires_at<=?",
            (now,),
        ).fetchall()
        for row in rows:
            publication_id = str(row["publication_id"])
            if con.execute(
                "SELECT 1 FROM publication_processing_claims "
                "WHERE publication_id=? AND expires_at>?",
                (publication_id, now),
            ).fetchone() is not None:
                continue
            attempts = con.execute(
                "SELECT metadata_json FROM publication_attempts WHERE publication_id=?",
                (publication_id,),
            ).fetchall()
            if any(
                json.loads(attempt["metadata_json"]).get("nonce_reservation_token") == row["token"]
                for attempt in attempts
            ):
                continue
            con.execute(
                "DELETE FROM evm_nonce_reservations "
                "WHERE network=? AND sender=? AND nonce=? AND token=?",
                (row["network"], row["sender"], row["nonce"], row["token"]),
            )
