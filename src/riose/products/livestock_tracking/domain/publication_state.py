"""Explicit local publication lifecycle; statuses describe evidence, not truth."""

from __future__ import annotations

from enum import StrEnum


class PublicationState(StrEnum):
    QUEUED = "QUEUED"
    PREPARED = "PREPARED"
    RPC_ACCEPTED = "RPC_ACCEPTED"
    UNKNOWN = "UNKNOWN"
    RETRYABLE = "RETRYABLE"
    CONFIRMED = "CONFIRMED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


ALLOWED_TRANSITIONS = {
    PublicationState.QUEUED: {PublicationState.PREPARED, PublicationState.REJECTED},
    PublicationState.PREPARED: {PublicationState.RPC_ACCEPTED, PublicationState.UNKNOWN, PublicationState.RETRYABLE, PublicationState.CONFIRMED, PublicationState.REJECTED},
    PublicationState.RPC_ACCEPTED: {PublicationState.CONFIRMED, PublicationState.UNKNOWN, PublicationState.RETRYABLE, PublicationState.REJECTED},
    PublicationState.UNKNOWN: {PublicationState.CONFIRMED, PublicationState.RETRYABLE, PublicationState.REJECTED},
    PublicationState.RETRYABLE: {PublicationState.PREPARED, PublicationState.REJECTED},
    PublicationState.CONFIRMED: {PublicationState.VERIFIED, PublicationState.UNKNOWN},
    PublicationState.VERIFIED: set(),
    PublicationState.REJECTED: set(),
}


def require_transition(current: PublicationState, requested: PublicationState) -> None:
    if requested not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"invalid publication state transition: {current} -> {requested}")
