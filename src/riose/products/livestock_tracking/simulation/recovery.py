"""Scripted offline lookup port for publication recovery tests and demos."""

from __future__ import annotations

from collections.abc import Iterable

from ..application.publication_recovery import (
    LookupNotFound,
    LookupUnavailable,
    ObservedConfirmed,
    ObservedSubmitted,
    ProvenNonAcceptance,
    PublicationRecoveryPort,
    RecoveryObservation,
)
from ..domain.publication_state import PublicationSnapshot


class ScriptedRecoveryLookup(PublicationRecoveryPort):
    """Return fixture observations in order and record only lookup scope."""

    def __init__(self, outcomes: Iterable[RecoveryObservation]) -> None:
        self._outcomes = tuple(outcomes)
        allowed = (
            LookupNotFound,
            LookupUnavailable,
            ObservedSubmitted,
            ObservedConfirmed,
            ProvenNonAcceptance,
        )
        if any(not isinstance(item, allowed) for item in self._outcomes):
            raise ValueError("recovery outcomes must be typed fixtures")
        self._next = 0
        self.lookups: list[tuple[str, str, str, str | None]] = []

    def lookup(self, snapshot: PublicationSnapshot) -> RecoveryObservation:
        self.lookups.append(
            (
                snapshot.commitment,
                snapshot.destination,
                snapshot.network,
                snapshot.reference,
            )
        )
        if self._next >= len(self._outcomes):
            return LookupUnavailable()
        result = self._outcomes[self._next]
        self._next += 1
        return result
