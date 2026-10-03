"""Deterministic state-transition matrix for commitment publication."""

from __future__ import annotations

import sqlite3
import socket

import pytest

from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.domain.contracts import EvidenceStatus
from riose.products.livestock_tracking.domain.publication_state import (
    AttemptCondition,
    BeginAttempt,
    ConfirmationObserved,
    LifecycleState,
    PreAcceptanceFailure,
    PublicationPolicy,
    PublicationSnapshot,
    RetryDue,
    SubmissionAccepted,
    SubmissionUnknown,
    TransitionDecision,
    TransitionReason,
    transition,
)


COMMITMENT = "a" * 64
POLICY = PublicationPolicy(max_attempts=3, retry_delay_s=30)


def initial() -> PublicationSnapshot:
    return PublicationSnapshot(COMMITMENT, "fake-chain", "offline")


def begin(snapshot: PublicationSnapshot | None = None, attempt_id="attempt-1"):
    snapshot = initial() if snapshot is None else snapshot
    return transition(
        snapshot,
        BeginAttempt(attempt_id, "fake-chain", "offline"),
        POLICY,
        now=10,
    )


def test_happy_path_separates_submit_from_confirmed_observation():
    started = begin()
    assert started.snapshot.attempt_condition is AttemptCondition.IN_FLIGHT
    assert started.snapshot.lifecycle is LifecycleState.QUEUED
    assert started.snapshot.attempt_count == 1

    submitted = transition(
        started.snapshot,
        SubmissionAccepted(
            "attempt-1", "fake-chain", "offline", "simulated-ref", EvidenceStatus.SIMULATED
        ),
        POLICY,
        now=11,
    )
    assert submitted.snapshot.lifecycle is LifecycleState.SUBMITTED
    assert submitted.snapshot.reference == "simulated-ref"
    assert submitted.snapshot.evidence_status is EvidenceStatus.SIMULATED
    assert submitted.snapshot.lifecycle is not LifecycleState.CONFIRMED

    confirmed = transition(
        submitted.snapshot,
        ConfirmationObserved(
            "attempt-1", "fake-chain", "offline", "simulated-ref", EvidenceStatus.SIMULATED
        ),
        POLICY,
        now=12,
    )
    assert confirmed.snapshot.lifecycle is LifecycleState.CONFIRMED
    assert confirmed.snapshot.attempt_condition is AttemptCondition.READY
    assert confirmed.snapshot.evidence_status is EvidenceStatus.SIMULATED


def test_retry_requires_proven_pre_acceptance_failure_deadline_and_budget():
    started = begin()
    failed = transition(
        started.snapshot,
        PreAcceptanceFailure("attempt-1", "fake-chain", "offline", retryable=True),
        POLICY,
        now=20,
    )
    assert failed.snapshot.attempt_condition is AttemptCondition.RETRY_WAIT
    assert failed.snapshot.retry_at == 50

    too_early = transition(
        failed.snapshot,
        RetryDue("attempt-1", "attempt-2", "fake-chain", "offline"),
        POLICY,
        now=49.9,
    )
    assert too_early.decision is TransitionDecision.NOOP
    assert too_early.reason is TransitionReason.WAITING_FOR_RETRY_DEADLINE
    assert too_early.snapshot is failed.snapshot

    ready = transition(
        failed.snapshot,
        RetryDue("attempt-1", "attempt-2", "fake-chain", "offline"),
        POLICY,
        now=50,
    )
    assert ready.snapshot.attempt_condition is AttemptCondition.READY
    assert ready.snapshot.attempt_id == "attempt-2"
    assert ready.snapshot.reference is None
    second = begin(ready.snapshot, "attempt-2")
    assert second.snapshot.attempt_count == 2


def test_permanent_failure_and_retry_budget_fail_closed():
    started = begin()
    permanent = transition(
        started.snapshot,
        PreAcceptanceFailure("attempt-1", "fake-chain", "offline", retryable=False),
        POLICY,
        now=20,
    )
    assert permanent.snapshot.attempt_condition is AttemptCondition.FAILED

    snapshot = PublicationSnapshot(
        COMMITMENT,
        "fake-chain",
        "offline",
        attempt_condition=AttemptCondition.IN_FLIGHT,
        attempt_id="attempt-3",
        attempt_count=3,
    )
    exhausted = transition(
        snapshot,
        PreAcceptanceFailure("attempt-3", "fake-chain", "offline", retryable=True),
        POLICY,
        now=20,
    )
    assert exhausted.snapshot.attempt_condition is AttemptCondition.FAILED
    assert exhausted.reason is TransitionReason.RETRY_BUDGET_EXHAUSTED
    assert transition(snapshot, BeginAttempt("attempt-4", "fake-chain", "offline"), POLICY, 20).decision is TransitionDecision.REJECTED


def test_timeout_keeps_unknown_and_never_allows_blind_retry():
    started = begin()
    unknown = transition(
        started.snapshot,
        SubmissionUnknown("attempt-1", "fake-chain", "offline"),
        POLICY,
        now=30,
    )
    assert unknown.snapshot.lifecycle is LifecycleState.QUEUED
    assert unknown.snapshot.attempt_condition is AttemptCondition.UNKNOWN
    blind_retry = transition(
        unknown.snapshot,
        RetryDue("attempt-1", "attempt-2", "fake-chain", "offline"),
        POLICY,
        now=1000,
    )
    assert blind_retry.decision is TransitionDecision.REJECTED
    assert blind_retry.snapshot is unknown.snapshot


def test_query_timeout_preserves_known_submission_and_reference():
    started = begin()
    submitted = transition(
        started.snapshot,
        SubmissionAccepted(
            "attempt-1", "fake-chain", "offline", "ref-1", EvidenceStatus.SIMULATED
        ),
        POLICY,
        now=11,
    )
    unknown = transition(
        submitted.snapshot,
        SubmissionUnknown("attempt-1", "fake-chain", "offline"),
        POLICY,
        now=20,
    )
    assert unknown.snapshot.lifecycle is LifecycleState.SUBMITTED
    assert unknown.snapshot.attempt_condition is AttemptCondition.UNKNOWN
    assert unknown.snapshot.reference == "ref-1"

    stale_acceptance = transition(
        unknown.snapshot,
        SubmissionAccepted(
            "attempt-1", "fake-chain", "offline", "other-ref", EvidenceStatus.SIMULATED
        ),
        POLICY,
        now=21,
    )
    assert stale_acceptance.decision is TransitionDecision.REJECTED
    assert stale_acceptance.reason is TransitionReason.STALE_ATTEMPT


@pytest.mark.parametrize(
    "signal",
    [
        SubmissionAccepted("old-attempt", "fake-chain", "offline", "ref", EvidenceStatus.SIMULATED),
        SubmissionAccepted("attempt-1", "other-chain", "offline", "ref", EvidenceStatus.SIMULATED),
        ConfirmationObserved("attempt-1", "fake-chain", "offline", "wrong-ref", EvidenceStatus.SIMULATED),
    ],
)
def test_stale_attempt_scope_or_reference_cannot_change_snapshot(signal):
    current = begin().snapshot
    if isinstance(signal, ConfirmationObserved):
        current = transition(
            current,
            SubmissionAccepted(
                "attempt-1", "fake-chain", "offline", "ref", EvidenceStatus.SIMULATED
            ),
            POLICY,
            now=11,
        ).snapshot
    result = transition(current, signal, POLICY, now=12)
    assert result.decision is TransitionDecision.REJECTED
    assert result.snapshot is current
    assert result.reason in {TransitionReason.STALE_ATTEMPT, TransitionReason.SCOPE_MISMATCH}


def test_confirmation_in_queue_and_duplicate_signals_are_safe():
    queued = initial()
    rejected = transition(
        queued,
        ConfirmationObserved("attempt-1", "fake-chain", "offline", "ref", EvidenceStatus.SIMULATED),
        POLICY,
        now=1,
    )
    assert rejected.decision is TransitionDecision.REJECTED
    assert rejected.snapshot is queued

    submitted = transition(
        begin().snapshot,
        SubmissionAccepted(
            "attempt-1", "fake-chain", "offline", "ref", EvidenceStatus.SIMULATED
        ),
        POLICY,
        now=11,
    )
    duplicate = transition(
        submitted.snapshot,
        SubmissionAccepted(
            "attempt-1", "fake-chain", "offline", "ref", EvidenceStatus.SIMULATED
        ),
        POLICY,
        now=12,
    )
    assert duplicate.decision is TransitionDecision.NOOP
    assert duplicate.snapshot is submitted.snapshot


def test_invalid_inputs_are_rejected_without_echoing_values():
    current = begin().snapshot
    result = transition(current, object(), POLICY, now=1)
    assert result.decision is TransitionDecision.REJECTED
    assert result.reason is TransitionReason.INVALID_SIGNAL
    invalid_time = transition(current, SubmissionUnknown("attempt-1", "fake-chain", "offline"), POLICY, float("nan"))
    assert invalid_time.snapshot is current
    assert invalid_time.reason is TransitionReason.INVALID_SIGNAL


def test_state_policy_has_no_network_or_database_side_effects(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.sqlite3")
    store.create_animal("synthetic-animal", "synthetic-tag", "b" * 64)
    before = store.connection.execute("SELECT hash FROM animal_events ORDER BY event_id").fetchall()

    def unexpected(*_args, **_kwargs):
        raise AssertionError("pure state policy attempted I/O")

    monkeypatch.setattr(socket, "socket", unexpected)
    monkeypatch.setattr(sqlite3, "connect", unexpected)
    for _ in range(2):
        assert begin().snapshot == begin().snapshot

    after = store.connection.execute("SELECT hash FROM animal_events ORDER BY event_id").fetchall()
    assert before == after
    assert store.verify_animal_chain("synthetic-animal")
    store.close()


def test_policy_validation_rejects_invalid_retry_budget_and_delay():
    with pytest.raises(ValueError):
        PublicationPolicy(max_attempts=True)
    with pytest.raises(ValueError):
        PublicationPolicy(retry_delay_s=float("inf"))
