"""Stable publication keys and local duplicate-submit behavior."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from riose.products.livestock_tracking.application.idempotent_publisher import (
    IdempotencyConflict,
    IdempotentPublisher,
    RegistryStatus,
    derive_publication_key,
    publication_fingerprint,
)
from riose.products.livestock_tracking.domain.contracts import EvidenceStatus
from riose.products.livestock_tracking.domain.privacy import build_public_envelope
from riose.products.livestock_tracking.domain.publication import (
    CommitmentPublicationRequest,
    PublicationStatus,
)
from riose.products.livestock_tracking.simulation.blockchain import (
    FakeBlockchainAdapter,
    FakeSubmitOutcome,
)
from riose.products.livestock_tracking.simulation.idempotency import (
    MemoryPublicationAttemptRegistry,
)


def request(
    *,
    digest="a" * 64,
    destination="fake-chain",
    network="offline",
    protocol_version=1,
):
    return CommitmentPublicationRequest(
        envelope=build_public_envelope(digest),
        destination=destination,
        network=network,
        protocol_version=protocol_version,
    )


def test_key_is_stable_and_matches_golden_vector():
    key = derive_publication_key(request())
    assert key == derive_publication_key(request())
    assert key == "7fbff3e6a804389fd9861bd37ab53970d5faa81e6cde78d136886a5e3eae6c05"


@pytest.mark.parametrize(
    "changed",
    [
        request(digest="b" * 64),
        request(destination="other-chain"),
        request(network="testnet"),
        request(protocol_version=2),
    ],
)
def test_key_separates_commitment_destination_network_and_protocol(changed):
    assert derive_publication_key(changed) != derive_publication_key(request())


def test_purpose_is_part_of_key_and_invalid_purpose_is_rejected():
    assert derive_publication_key(request(), purpose="commitment-anchor") != derive_publication_key(
        request(), purpose="audit-anchor"
    )
    with pytest.raises(ValueError):
        derive_publication_key(request(), purpose="Animal 123")


def test_fingerprint_is_stable_and_contains_only_minimized_scope():
    assert publication_fingerprint(request()) == publication_fingerprint(request())
    assert publication_fingerprint(request()) != publication_fingerprint(request(digest="b" * 64))


def test_first_submit_then_repeated_submitted_or_confirmed_never_resends():
    adapter = FakeBlockchainAdapter([FakeSubmitOutcome.CONFIRMED])
    registry = MemoryPublicationAttemptRegistry()
    publisher = IdempotentPublisher(adapter, registry)
    request_value = request()

    first = publisher.submit(request_value)
    assert first.status is RegistryStatus.NEW
    assert first.submission.status is PublicationStatus.SUBMITTED
    assert first.submission.evidence_status is EvidenceStatus.SIMULATED
    assert len(adapter.records) == 1

    repeated = publisher.submit(request_value)
    assert repeated.status is RegistryStatus.EXISTING_SUBMITTED
    assert repeated.reference == first.reference
    assert repeated.submission is None
    assert len(adapter.records) == 1

    confirmation = publisher.query(request_value, first.reference)
    assert confirmation.status is PublicationStatus.CONFIRMED
    confirmed_repeat = publisher.submit(request_value)
    assert confirmed_repeat.status is RegistryStatus.EXISTING_CONFIRMED
    assert confirmed_repeat.reference == first.reference
    assert len(adapter.records) == 1


@pytest.mark.parametrize(
    "outcome",
    [FakeSubmitOutcome.TIMEOUT, FakeSubmitOutcome.UNKNOWN, FakeSubmitOutcome.UNAVAILABLE],
)
def test_unknown_or_unavailable_registry_result_blocks_automatic_resend(outcome):
    adapter = FakeBlockchainAdapter([outcome, FakeSubmitOutcome.SUBMITTED])
    publisher = IdempotentPublisher(adapter, MemoryPublicationAttemptRegistry())
    first = publisher.submit(request())
    second = publisher.submit(request())
    assert first.status is RegistryStatus.NEW
    assert second.status is RegistryStatus.UNKNOWN
    assert second.submission is None
    assert len(adapter.records) == 1


def test_key_fingerprint_conflict_fails_without_overwrite_or_resend():
    adapter = FakeBlockchainAdapter([FakeSubmitOutcome.SUBMITTED])
    publisher = IdempotentPublisher(adapter, MemoryPublicationAttemptRegistry())
    original = request()
    publisher.submit(original)
    # Keep key scope fixed while constructing an altered protocol fingerprint.
    changed = CommitmentPublicationRequest(
        envelope=build_public_envelope(original.envelope.commitment),
        destination=original.destination,
        network=original.network,
        protocol_version=original.protocol_version,
    )
    # A direct registry conflict verifies no overwrite even if a caller bypasses
    # the normal pure key/fingerprint derivation path.
    from riose.products.livestock_tracking.application.idempotent_publisher import (
        publication_fingerprint,
    )

    registry = MemoryPublicationAttemptRegistry()
    key = derive_publication_key(original)
    registry.reserve(key, "f" * 64)
    with pytest.raises(IdempotencyConflict):
        registry.reserve(key, publication_fingerprint(changed))
    assert len(adapter.records) == 1


def test_concurrent_registry_reservation_allows_only_one_new_submit_slot():
    registry = MemoryPublicationAttemptRegistry()
    key = derive_publication_key(request())
    fingerprint = publication_fingerprint(request())
    barrier = Barrier(2)

    def reserve():
        barrier.wait()
        return registry.reserve(key, fingerprint).status

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: reserve(), range(2)))
    assert results.count(RegistryStatus.NEW) == 1
    assert results.count(RegistryStatus.UNKNOWN) == 1


def test_registry_fake_is_volatile_and_unknown_after_restart():
    key = derive_publication_key(request())
    fingerprint = publication_fingerprint(request())
    first = MemoryPublicationAttemptRegistry()
    assert first.reserve(key, fingerprint).status is RegistryStatus.NEW
    restarted = MemoryPublicationAttemptRegistry()
    assert restarted.get(key, fingerprint).status is RegistryStatus.UNKNOWN


def test_query_without_registered_intent_does_not_create_or_confirm_registry_state():
    adapter = FakeBlockchainAdapter([FakeSubmitOutcome.CONFIRMED])
    outside_submission = adapter.submit(request())
    registry = MemoryPublicationAttemptRegistry()
    publisher = IdempotentPublisher(adapter, registry)

    observed = publisher.query(request(), outside_submission.reference)

    assert observed.status is PublicationStatus.CONFIRMED
    assert registry.get(
        derive_publication_key(request()), publication_fingerprint(request())
    ).status is RegistryStatus.UNKNOWN


def test_exception_from_adapter_is_redacted_and_blocks_resend():
    secret = "synthetic-private-seed"

    class BrokenAdapter(FakeBlockchainAdapter):
        def submit(self, request):
            raise RuntimeError(secret)

    adapter = BrokenAdapter([])
    publisher = IdempotentPublisher(adapter, MemoryPublicationAttemptRegistry())
    first = publisher.submit(request())
    second = publisher.submit(request())
    assert first.status is RegistryStatus.UNKNOWN
    assert secret not in repr(first)
    assert second.status is RegistryStatus.UNKNOWN
