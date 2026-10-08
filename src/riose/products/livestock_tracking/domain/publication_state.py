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
    PERMANENT_FAILURE = "PERMANENT_FAILURE"
    MANUAL_INTERVENTION = "MANUAL_INTERVENTION"


ALLOWED_TRANSITIONS = {
    PublicationState.QUEUED: {PublicationState.PREPARED, PublicationState.REJECTED, PublicationState.PERMANENT_FAILURE, PublicationState.MANUAL_INTERVENTION},
    PublicationState.PREPARED: {PublicationState.RPC_ACCEPTED, PublicationState.UNKNOWN, PublicationState.RETRYABLE, PublicationState.CONFIRMED, PublicationState.REJECTED, PublicationState.PERMANENT_FAILURE, PublicationState.MANUAL_INTERVENTION},
    PublicationState.RPC_ACCEPTED: {PublicationState.CONFIRMED, PublicationState.UNKNOWN, PublicationState.RETRYABLE, PublicationState.REJECTED, PublicationState.MANUAL_INTERVENTION},
    PublicationState.UNKNOWN: {PublicationState.RPC_ACCEPTED, PublicationState.CONFIRMED, PublicationState.RETRYABLE, PublicationState.REJECTED, PublicationState.MANUAL_INTERVENTION},
    PublicationState.RETRYABLE: {PublicationState.PREPARED, PublicationState.REJECTED, PublicationState.PERMANENT_FAILURE, PublicationState.MANUAL_INTERVENTION},
    PublicationState.CONFIRMED: {PublicationState.VERIFIED, PublicationState.UNKNOWN, PublicationState.MANUAL_INTERVENTION},
    PublicationState.VERIFIED: set(),
    PublicationState.REJECTED: set(),
    PublicationState.PERMANENT_FAILURE: set(),
    PublicationState.MANUAL_INTERVENTION: set(),
}


def require_transition(current: PublicationState, requested: PublicationState) -> None:
    if requested not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"invalid publication state transition: {current} -> {requested}")
