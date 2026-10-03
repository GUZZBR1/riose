"""Volatile, thread-safe registry fake for publication idempotency tests."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from ..application.idempotent_publisher import (
    IdempotencyConflict,
    RegistryResult,
    RegistryStatus,
)
from ..domain.publication import ConfirmationResult, PublicationStatus, SubmissionResult


@dataclass(slots=True)
class _Entry:
    fingerprint: str
    status: RegistryStatus
    reference: str | None = None


class MemoryPublicationAttemptRegistry:
    """Atomic in-process fake. State is volatile and is not crash durable."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, _Entry] = {}

    def reserve(self, key: str, fingerprint: str) -> RegistryResult:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._entries[key] = _Entry(fingerprint, RegistryStatus.UNKNOWN)
                return RegistryResult(RegistryStatus.NEW)
            _check_fingerprint(entry, fingerprint)
            return RegistryResult(entry.status, entry.reference)

    def get(self, key: str, fingerprint: str) -> RegistryResult:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return RegistryResult(RegistryStatus.UNKNOWN)
            _check_fingerprint(entry, fingerprint)
            return RegistryResult(entry.status, entry.reference)

    def record_submission(
        self, key: str, fingerprint: str, result: SubmissionResult
    ) -> None:
        with self._lock:
            entry = self._require(key, fingerprint)
            if result.status is PublicationStatus.SUBMITTED and result.reference is not None:
                entry.status = RegistryStatus.EXISTING_SUBMITTED
                entry.reference = result.reference
            else:
                entry.status = RegistryStatus.UNKNOWN
                entry.reference = None

    def record_unknown(self, key: str, fingerprint: str) -> None:
        with self._lock:
            entry = self._require(key, fingerprint)
            entry.status = RegistryStatus.UNKNOWN
            entry.reference = None

    def record_confirmation(
        self, key: str, fingerprint: str, result: ConfirmationResult
    ) -> None:
        with self._lock:
            entry = self._require(key, fingerprint)
            if (
                entry.status is RegistryStatus.EXISTING_SUBMITTED
                and entry.reference == result.reference
                and result.status is PublicationStatus.CONFIRMED
            ):
                entry.status = RegistryStatus.EXISTING_CONFIRMED

    def _require(self, key: str, fingerprint: str) -> _Entry:
        entry = self._entries.get(key)
        if entry is None:
            raise ValueError("attempt was not reserved")
        _check_fingerprint(entry, fingerprint)
        return entry


def _check_fingerprint(entry: _Entry, fingerprint: str) -> None:
    if entry.fingerprint != fingerprint:
        raise IdempotencyConflict("publication key conflicts with existing intent")
