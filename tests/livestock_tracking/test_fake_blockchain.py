"""Offline contract tests for the simulated publication adapter."""

from __future__ import annotations

import socket

import pytest

from riose.products.livestock_tracking.domain.contracts import EvidenceStatus
from riose.products.livestock_tracking.domain.privacy import build_public_envelope
from riose.products.livestock_tracking.domain.publication import (
    CommitmentPublicationRequest,
    PublicationReason,
    PublicationStatus,
)
from riose.products.livestock_tracking.simulation.blockchain import (
    FakeBlockchainAdapter,
    FakeSubmitOutcome,
)


COMMITMENT = "a" * 64


def request(commitment: str = COMMITMENT) -> CommitmentPublicationRequest:
    return CommitmentPublicationRequest(
        envelope=build_public_envelope(commitment),
        destination="fake-chain",
        network="offline",
    )


@pytest.mark.parametrize(
    ("outcome", "status", "reason"),
    [
        (FakeSubmitOutcome.SUBMITTED, PublicationStatus.SUBMITTED, None),
        (FakeSubmitOutcome.CONFIRMED, PublicationStatus.SUBMITTED, None),
        (
            FakeSubmitOutcome.REJECTED,
            PublicationStatus.REJECTED,
            PublicationReason.DESTINATION_REJECTED,
        ),
        (
            FakeSubmitOutcome.UNAVAILABLE,
            PublicationStatus.UNAVAILABLE,
            PublicationReason.DESTINATION_UNAVAILABLE,
        ),
        (FakeSubmitOutcome.TIMEOUT, PublicationStatus.UNKNOWN, PublicationReason.TIMEOUT),
        (FakeSubmitOutcome.UNKNOWN, PublicationStatus.UNKNOWN, PublicationReason.UNKNOWN),
    ],
)
def test_scripted_submit_outcomes_are_typed_and_simulated(outcome, status, reason):
    adapter = FakeBlockchainAdapter([outcome])

    result = adapter.submit(request())

    assert result.status is status
    assert result.reason is reason
    assert result.evidence_status is EvidenceStatus.SIMULATED
    assert adapter.capabilities.evidence_status is EvidenceStatus.SIMULATED
    if status is PublicationStatus.SUBMITTED:
        assert result.reference == "simulated-0001"


def test_confirmation_is_only_visible_after_explicit_query():
    adapter = FakeBlockchainAdapter([FakeSubmitOutcome.CONFIRMED])
    submitted = adapter.submit(request())

    assert submitted.status is PublicationStatus.SUBMITTED
    observed = adapter.query(
        commitment=COMMITMENT,
        destination="fake-chain",
        network="offline",
        reference=submitted.reference,
    )
    assert observed.status is PublicationStatus.CONFIRMED
    assert observed.evidence_status is EvidenceStatus.SIMULATED


def test_pending_and_unknown_lookup_never_become_confirmation_or_invalid():
    adapter = FakeBlockchainAdapter([FakeSubmitOutcome.SUBMITTED])
    submitted = adapter.submit(request())
    pending = adapter.query(
        commitment=COMMITMENT,
        destination="fake-chain",
        network="offline",
        reference=submitted.reference,
    )
    missing = adapter.query(
        commitment=COMMITMENT,
        destination="fake-chain",
        network="offline",
        reference="unknown-ref",
    )
    assert pending.status is PublicationStatus.UNKNOWN
    assert missing.status is PublicationStatus.UNKNOWN
    assert pending.reason is PublicationReason.NOT_FOUND
    assert missing.reason is PublicationReason.NOT_FOUND


def test_mismatch_is_rejected_and_record_contains_only_minimized_fields():
    adapter = FakeBlockchainAdapter([FakeSubmitOutcome.CONFIRMED])
    submitted = adapter.submit(request())
    mismatch = adapter.query(
        commitment="b" * 64,
        destination="fake-chain",
        network="offline",
        reference=submitted.reference,
    )

    assert mismatch.status is PublicationStatus.REJECTED
    assert mismatch.reason is PublicationReason.OBSERVATION_MISMATCH
    assert adapter.records[0].commitment == COMMITMENT
    assert not hasattr(adapter.records[0], "payload")
    assert not hasattr(adapter.records[0], "envelope")


def test_fake_does_not_retain_arbitrary_payload_or_accept_unprotected_request():
    adapter = FakeBlockchainAdapter([FakeSubmitOutcome.SUBMITTED])
    secret = "synthetic-seed-for-test-only"
    with pytest.raises(ValueError) as error:
        adapter.submit({"payload": secret})  # type: ignore[arg-type]
    assert secret not in str(error.value)
    assert not adapter.records


def test_fake_is_volatile_and_reproducible_after_restart():
    first = FakeBlockchainAdapter([FakeSubmitOutcome.SUBMITTED])
    first_result = first.submit(request())
    restarted = FakeBlockchainAdapter([])
    assert first_result.reference == "simulated-0001"
    assert not restarted.records
    assert restarted.query(
        commitment=COMMITMENT,
        destination="fake-chain",
        network="offline",
        reference=first_result.reference,
    ).status is PublicationStatus.UNKNOWN


def test_fake_never_uses_network(monkeypatch):
    def fail_if_network(*_args, **_kwargs):
        raise AssertionError("fake adapter attempted network access")

    monkeypatch.setattr(socket, "socket", fail_if_network)
    adapter = FakeBlockchainAdapter([FakeSubmitOutcome.CONFIRMED])
    result = adapter.submit(request())
    assert adapter.query(
        commitment=COMMITMENT,
        destination="fake-chain",
        network="offline",
        reference=result.reference,
    ).status is PublicationStatus.CONFIRMED


def test_script_exhaustion_fails_closed():
    adapter = FakeBlockchainAdapter([])
    assert adapter.submit(request()).status is PublicationStatus.UNKNOWN
