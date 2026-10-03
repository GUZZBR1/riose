"""Crash/restart reconciliation tests with injected offline lookup fixtures."""

from __future__ import annotations

import sqlite3
import socket

import pytest

from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.application.publication_recovery import (
    LookupNotFound,
    LookupUnavailable,
    NonAcceptanceEvidence,
    NonAcceptanceProofKind,
    ObservedConfirmed,
    ObservedSubmitted,
    ProvenNonAcceptance,
    PublicationRecoveryService,
    RecoveryDecision,
    RecoveryReason,
    RecoverySnapshot,
)
from riose.products.livestock_tracking.domain.contracts import EvidenceStatus
from riose.products.livestock_tracking.domain.publication import PublicationReason
from riose.products.livestock_tracking.domain.publication_state import (
    AttemptCondition,
    BeginAttempt,
    LifecycleState,
    PublicationPolicy,
    PublicationSnapshot,
    SubmissionAccepted,
    TransitionDecision,
    transition,
)
from riose.products.livestock_tracking.simulation.recovery import ScriptedRecoveryLookup


COMMITMENT = "a" * 64


def attempted_snapshot(*, evidence=EvidenceStatus.FUTURE, submitted=False):
    initial = PublicationSnapshot(COMMITMENT, "fake-chain", "offline")
    started = transition(
        initial,
        BeginAttempt("attempt-1", "fake-chain", "offline"),
        PublicationPolicy(),
        now=1,
    ).snapshot
    if not submitted:
        return started
    return transition(
        started,
        SubmissionAccepted(
            "attempt-1", "fake-chain", "offline", "ref-1", evidence
        ),
        PublicationPolicy(),
        now=2,
    ).snapshot


def observed_submitted(**overrides):
    values = {
        "attempt_id": "attempt-1",
        "commitment": COMMITMENT,
        "destination": "fake-chain",
        "network": "offline",
        "reference": "ref-1",
        "evidence_status": EvidenceStatus.SIMULATED,
    }
    values.update(overrides)
    return ObservedSubmitted(**values)


class AcceptOfflineProof:
    def verify(self, snapshot, evidence):
        return (
            snapshot.attempt_id == evidence.attempt_id
            and evidence.source == "offline-fixture"
            and evidence.evidence_reference == "preflight-1"
        )


def nonacceptance(*, attempt_id="attempt-1", evidence_status=EvidenceStatus.VALIDATED):
    return ProvenNonAcceptance(
        NonAcceptanceEvidence(
            attempt_id,
            NonAcceptanceProofKind.NOT_SENT,
            "offline-fixture",
            "preflight-1",
            evidence_status,
        )
    )


def test_crash_after_submit_resolves_submitted_without_resending():
    snapshot = RecoverySnapshot(attempted_snapshot(), query_budget=3)
    lookup = ScriptedRecoveryLookup([observed_submitted()])
    service = PublicationRecoveryService(lookup)

    result = service.reconcile(snapshot, now=100)

    assert result.decision is RecoveryDecision.RESOLVED_SUBMITTED
    assert result.snapshot.publication.lifecycle is LifecycleState.SUBMITTED
    assert result.snapshot.publication.reference == "ref-1"
    assert result.snapshot.publication.evidence_status is EvidenceStatus.SIMULATED
    assert result.snapshot.queries_used == 1
    assert result.snapshot.last_checked_at == 100
    assert len(lookup.lookups) == 1


def test_crash_after_submission_can_resolve_confirmation_explicitly():
    snapshot = RecoverySnapshot(attempted_snapshot(submitted=True))
    evidence = ObservedConfirmed(
        "attempt-1",
        COMMITMENT,
        "fake-chain",
        "offline",
        "ref-1",
        EvidenceStatus.SIMULATED,
    )
    result = PublicationRecoveryService(ScriptedRecoveryLookup([evidence])).reconcile(
        snapshot, now=120
    )
    assert result.decision is RecoveryDecision.RESOLVED_CONFIRMED
    assert result.snapshot.publication.lifecycle is LifecycleState.CONFIRMED
    assert result.snapshot.publication.reference == "ref-1"
    assert result.snapshot.publication.evidence_status is EvidenceStatus.SIMULATED


def test_not_found_is_wait_not_invalid_or_safe_to_retry():
    snapshot = RecoverySnapshot(attempted_snapshot(), query_budget=2)
    result = PublicationRecoveryService(ScriptedRecoveryLookup([LookupNotFound()])).reconcile(
        snapshot, now=50
    )
    assert result.decision is RecoveryDecision.WAIT
    assert result.reason is RecoveryReason.NOT_FOUND_IN_LOOKUP
    assert result.snapshot.publication == snapshot.publication
    assert result.snapshot.queries_used == 1


def test_unavailable_or_timeout_preserves_attempt_and_never_resends():
    snapshot = RecoverySnapshot(attempted_snapshot(), query_budget=2)
    result = PublicationRecoveryService(
        ScriptedRecoveryLookup([LookupUnavailable(PublicationReason.TIMEOUT)])
    ).reconcile(snapshot, now=51)
    assert result.decision is RecoveryDecision.UNAVAILABLE
    assert result.snapshot.publication == snapshot.publication
    assert result.snapshot.queries_used == 1


@pytest.mark.parametrize(
    "observation",
    [
        observed_submitted(commitment="b" * 64),
        observed_submitted(destination="other-chain"),
        observed_submitted(network="testnet"),
        observed_submitted(reference="different-ref"),
        observed_submitted(attempt_id="stale-attempt"),
    ],
)
def test_mismatched_lookup_is_invalid_without_overwriting_attempt(observation):
    publication = attempted_snapshot(submitted=True) if observation.reference == "different-ref" else attempted_snapshot()
    snapshot = RecoverySnapshot(publication)
    result = PublicationRecoveryService(ScriptedRecoveryLookup([observation])).reconcile(
        snapshot, now=60
    )
    assert result.decision is RecoveryDecision.INVALID
    assert result.reason is RecoveryReason.CORRELATION_MISMATCH
    assert result.snapshot.publication == snapshot.publication
    assert result.snapshot.queries_used == 1


def test_not_found_never_proves_non_acceptance_but_explicit_proof_can_allow_retry():
    snapshot = RecoverySnapshot(attempted_snapshot(), max_attempts=3)
    not_found = PublicationRecoveryService(ScriptedRecoveryLookup([LookupNotFound()])).reconcile(
        snapshot, now=70
    )
    assert not_found.decision is RecoveryDecision.WAIT

    proof = nonacceptance()
    waiting = PublicationRecoveryService(
        ScriptedRecoveryLookup([proof]), AcceptOfflineProof()
    ).reconcile(
        snapshot, now=71
    )
    assert waiting.decision is RecoveryDecision.WAIT
    assert waiting.reason is RecoveryReason.RETRY_NOT_AUTHORIZED

    safe = PublicationRecoveryService(
        ScriptedRecoveryLookup([proof]), AcceptOfflineProof()
    ).reconcile(snapshot, now=72, authorize_retry=True)
    assert safe.decision is RecoveryDecision.SAFE_TO_RETRY
    assert safe.reason is RecoveryReason.NON_ACCEPTANCE_PROVEN
    assert safe.snapshot.publication.attempt_condition is AttemptCondition.READY
    assert safe.snapshot.publication.attempt_id == snapshot.publication.attempt_id
    next_attempt = transition(
        safe.snapshot.publication,
        BeginAttempt("attempt-2", "fake-chain", "offline"),
        PublicationPolicy(),
        now=73,
    )
    assert next_attempt.decision is TransitionDecision.APPLIED
    assert next_attempt.snapshot.attempt_count == 2


def test_known_submission_cannot_be_reclassified_as_not_accepted():
    snapshot = RecoverySnapshot(attempted_snapshot(submitted=True))
    proof = nonacceptance()
    result = PublicationRecoveryService(ScriptedRecoveryLookup([proof])).reconcile(
        snapshot, now=73
    )
    assert result.decision is RecoveryDecision.INVALID
    assert result.reason is RecoveryReason.CORRELATION_MISMATCH
    assert result.snapshot.publication == snapshot.publication


def test_stale_pending_observation_does_not_downgrade_confirmation():
    confirmed = PublicationSnapshot(
        commitment=COMMITMENT,
        destination="fake-chain",
        network="offline",
        lifecycle=LifecycleState.CONFIRMED,
        attempt_condition=AttemptCondition.READY,
        attempt_id="attempt-1",
        attempt_count=1,
        reference="ref-1",
        evidence_status=EvidenceStatus.SIMULATED,
    )
    snapshot = RecoverySnapshot(confirmed)
    result = PublicationRecoveryService(ScriptedRecoveryLookup([observed_submitted()])).reconcile(
        snapshot, now=74
    )
    assert result.decision is RecoveryDecision.RESOLVED_CONFIRMED
    assert result.snapshot.publication.lifecycle is LifecycleState.CONFIRMED


def test_nonacceptance_requires_matching_attempt_and_available_attempt_budget():
    snapshot = RecoverySnapshot(attempted_snapshot(), max_attempts=1)
    wrong_attempt = nonacceptance(attempt_id="old-attempt")
    invalid = PublicationRecoveryService(
        ScriptedRecoveryLookup([wrong_attempt]), AcceptOfflineProof()
    ).reconcile(
        snapshot, now=80
    )
    assert invalid.decision is RecoveryDecision.INVALID

    proof = nonacceptance()
    exhausted = PublicationRecoveryService(
        ScriptedRecoveryLookup([proof]), AcceptOfflineProof()
    ).reconcile(
        snapshot, now=81, authorize_retry=True
    )
    assert exhausted.decision is RecoveryDecision.WAIT
    assert exhausted.reason is RecoveryReason.ATTEMPT_BUDGET_EXHAUSTED


def test_query_budget_stops_reconciliation_without_calling_lookup():
    snapshot = RecoverySnapshot(attempted_snapshot(), queries_used=2, query_budget=2)
    lookup = ScriptedRecoveryLookup([LookupNotFound()])
    result = PublicationRecoveryService(lookup).reconcile(snapshot, now=90)
    assert result.decision is RecoveryDecision.UNAVAILABLE
    assert result.reason is RecoveryReason.QUERY_BUDGET_EXHAUSTED
    assert result.snapshot is snapshot
    assert not lookup.lookups


def test_reusing_a_stale_snapshot_cannot_bypass_the_service_query_budget():
    snapshot = RecoverySnapshot(attempted_snapshot(), query_budget=2)
    lookup = ScriptedRecoveryLookup([LookupNotFound(), LookupNotFound()])
    service = PublicationRecoveryService(lookup)
    first = service.reconcile(snapshot, now=92)
    assert first.snapshot.queries_used == 1
    stale = service.reconcile(snapshot, now=93)
    assert stale.decision is RecoveryDecision.UNAVAILABLE
    assert stale.reason is RecoveryReason.STALE_RECOVERY_SNAPSHOT
    assert len(lookup.lookups) == 1


def test_unverified_nonacceptance_cannot_authorize_a_retry():
    snapshot = RecoverySnapshot(attempted_snapshot())
    result = PublicationRecoveryService(
        ScriptedRecoveryLookup([nonacceptance()])
    ).reconcile(snapshot, now=94, authorize_retry=True)
    assert result.decision is RecoveryDecision.INVALID


def test_simulated_nonacceptance_cannot_authorize_a_live_retry():
    snapshot = RecoverySnapshot(attempted_snapshot())
    result = PublicationRecoveryService(
        ScriptedRecoveryLookup(
            [nonacceptance(evidence_status=EvidenceStatus.SIMULATED)],
        ),
        AcceptOfflineProof(),
    ).reconcile(snapshot, now=95, authorize_retry=True)
    assert result.decision is RecoveryDecision.INVALID
    assert result.reason is RecoveryReason.EVIDENCE_PROVENANCE_MISMATCH
    assert result.snapshot.publication.attempt_condition is AttemptCondition.IN_FLIGHT


def test_general_state_machine_cannot_release_an_interrupted_attempt_for_retry():
    interrupted = attempted_snapshot()
    result = transition(
        interrupted,
        BeginAttempt("attempt-2", "fake-chain", "offline"),
        PublicationPolicy(),
        now=96,
    )
    assert result.decision is TransitionDecision.REJECTED
    assert result.snapshot == interrupted


def test_invalid_observation_does_not_upgrade_simulated_evidence():
    snapshot = RecoverySnapshot(
        attempted_snapshot(evidence=EvidenceStatus.SIMULATED, submitted=True)
    )
    observed = ObservedConfirmed(
        "attempt-1",
        COMMITMENT,
        "fake-chain",
        "offline",
        "ref-1",
        EvidenceStatus.VALIDATED,
    )
    result = PublicationRecoveryService(ScriptedRecoveryLookup([observed])).reconcile(
        snapshot, now=91
    )
    assert result.decision is RecoveryDecision.INVALID
    assert result.reason is RecoveryReason.EVIDENCE_PROVENANCE_MISMATCH
    assert result.snapshot.publication == snapshot.publication


def test_lookup_exception_is_redacted_and_counted_as_unavailable():
    secret = "synthetic-rpc-private-key"

    class BrokenLookup:
        def lookup(self, _snapshot):
            raise RuntimeError(secret)

    snapshot = RecoverySnapshot(attempted_snapshot())
    result = PublicationRecoveryService(BrokenLookup()).reconcile(snapshot, now=99)
    assert result.decision is RecoveryDecision.UNAVAILABLE
    assert result.reason is RecoveryReason.LOOKUP_FAILED
    assert secret not in repr(result)
    assert result.snapshot.queries_used == 1


def test_reconciliation_is_read_only_offline_and_does_not_change_event_chain(tmp_path, monkeypatch):
    store = Store(tmp_path / "recovery.sqlite3")
    store.create_animal("synthetic-animal", "synthetic-tag", "c" * 64)
    before = store.connection.execute("SELECT hash FROM animal_events ORDER BY event_id").fetchall()

    def unexpected(*_args, **_kwargs):
        raise AssertionError("recovery fixture attempted network or database creation")

    monkeypatch.setattr(socket, "socket", unexpected)
    monkeypatch.setattr(sqlite3, "connect", unexpected)
    result = PublicationRecoveryService(ScriptedRecoveryLookup([LookupNotFound()])).reconcile(
        RecoverySnapshot(attempted_snapshot()), now=100
    )

    after = store.connection.execute("SELECT hash FROM animal_events ORDER BY event_id").fetchall()
    assert result.decision is RecoveryDecision.WAIT
    assert before == after
    assert store.verify_animal_chain("synthetic-animal")
    store.close()


def test_invalid_time_is_rejected_without_lookup():
    lookup = ScriptedRecoveryLookup([LookupNotFound()])
    snapshot = RecoverySnapshot(attempted_snapshot())
    result = PublicationRecoveryService(lookup).reconcile(snapshot, now=float("nan"))
    assert result.decision is RecoveryDecision.INVALID
    assert result.snapshot is snapshot
    assert not lookup.lookups
