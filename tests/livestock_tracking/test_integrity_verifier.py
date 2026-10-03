"""Adversarial read-only tests for the local/publication integrity verifier."""

from __future__ import annotations

from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.application.integrity_verifier import (
    IntegrityVerificationRequest,
    IntegrityVerifier,
    VerificationReason,
    VerificationStatus,
)
from riose.products.livestock_tracking.domain.contracts import EvidenceStatus
from riose.products.livestock_tracking.domain.identity import LocalChainEvidence
from riose.products.livestock_tracking.domain.publication import (
    ConfirmationResult,
    PublicationReason,
    PublicationStatus,
)
from riose.products.livestock_tracking.domain.receipt import PublicationReceipt, ReceiptStatus


def confirmed_observation(commitment: str, *, evidence=EvidenceStatus.ASSUMED, **overrides):
    values = {
        "status": PublicationStatus.CONFIRMED,
        "commitment": commitment,
        "destination": "solana-memo",
        "network": "solana-genesis-a1b2c3d4e5f6",
        "reference": "signature-1",
        "reason": None,
        "evidence_status": evidence,
    }
    values.update(overrides)
    return ConfirmationResult(**values)


def matching_receipt(commitment: str, *, status=ReceiptStatus.CONFIRMED, evidence=EvidenceStatus.ASSUMED, **overrides):
    values = {
        "receipt_id": "receipt-1",
        "version": 1,
        "commitment": commitment,
        "destination": "solana-memo",
        "network": "solana-genesis-a1b2c3d4e5f6",
        "status": status,
        "evidence_status": evidence,
        "source": "rpc-observation",
        "observed_at": 12.0,
        "reference": "signature-1",
    }
    values.update(overrides)
    return PublicationReceipt(**values)


def request(commitment: str) -> IntegrityVerificationRequest:
    return IntegrityVerificationRequest(
        commitment, "solana-memo", "solana-genesis-a1b2c3d4e5f6", "signature-1"
    )


def test_valid_local_chain_and_matching_external_receipt_stays_assumed(tmp_path):
    store = Store(tmp_path / "verify.sqlite3")
    store.create_animal("synthetic", "tag-1", "b" * 64)
    chain = store.event_chain_evidence("synthetic")
    assert chain is not None and chain.valid
    result = IntegrityVerifier().verify(
        request(chain.head_digest),
        local_chain=chain,
        receipt=matching_receipt(chain.head_digest),
        observation=confirmed_observation(chain.head_digest),
    )
    assert result.status is VerificationStatus.VALID
    assert result.reason is VerificationReason.CONSISTENT_OBSERVATION
    assert result.evidence_status is EvidenceStatus.ASSUMED
    assert not hasattr(result, "animal_id")
    store.close()


def test_tampered_local_chain_is_invalid_without_repair_or_write(tmp_path):
    store = Store(tmp_path / "verify.sqlite3")
    store.create_animal("synthetic", "tag-1", "b" * 64)
    store.connection.execute(
        "UPDATE animal_events SET payload='{}' WHERE animal_id='synthetic'"
    )
    store.connection.commit()
    before = store.connection.execute(
        "SELECT event_id,payload,hash FROM animal_events ORDER BY event_id"
    ).fetchall()
    changes = store.connection.total_changes
    chain = store.event_chain_evidence("synthetic")
    result = IntegrityVerifier().verify(
        request(chain.head_digest),
        local_chain=chain,
        receipt=matching_receipt(chain.head_digest),
        observation=confirmed_observation(chain.head_digest),
    )
    after = store.connection.execute(
        "SELECT event_id,payload,hash FROM animal_events ORDER BY event_id"
    ).fetchall()
    assert result.status is VerificationStatus.INVALID
    assert result.reason is VerificationReason.LOCAL_CHAIN_INVALID
    assert store.connection.total_changes == changes
    assert before == after
    store.close()


def test_local_commitment_and_receipt_mismatches_are_invalid():
    digest = "a" * 64
    chain = LocalChainEvidence(True, "b" * 64, 1)
    result = IntegrityVerifier().verify(
        request(digest),
        local_chain=chain,
        receipt=matching_receipt(digest),
        observation=confirmed_observation(digest),
    )
    assert result.status is VerificationStatus.INVALID
    assert result.reason is VerificationReason.LOCAL_COMMITMENT_MISMATCH

    chain = LocalChainEvidence(True, digest, 1)
    result = IntegrityVerifier().verify(
        request(digest),
        local_chain=chain,
        receipt=matching_receipt("c" * 64),
        observation=confirmed_observation(digest),
    )
    assert result.status is VerificationStatus.INVALID
    assert result.reason is VerificationReason.RECEIPT_MISMATCH


def test_absent_receipt_and_rpc_unavailable_are_unavailable_not_invalid():
    digest = "a" * 64
    chain = LocalChainEvidence(True, digest, 1)
    verifier = IntegrityVerifier()
    absent = verifier.verify(
        request(digest), local_chain=chain, receipt=None, observation=None
    )
    assert absent.status is VerificationStatus.UNAVAILABLE
    assert absent.reason is VerificationReason.RECEIPT_MISSING

    unavailable = ConfirmationResult(
        PublicationStatus.UNAVAILABLE,
        digest,
        "solana-memo",
        "solana-genesis-a1b2c3d4e5f6",
        "signature-1",
        reason=PublicationReason.DESTINATION_UNAVAILABLE,
        evidence_status=EvidenceStatus.ASSUMED,
    )
    result = verifier.verify(
        request(digest),
        local_chain=chain,
        receipt=matching_receipt(digest, status=ReceiptStatus.SUBMITTED),
        observation=unavailable,
    )
    assert result.status is VerificationStatus.UNAVAILABLE
    assert result.reason is VerificationReason.SOURCE_UNAVAILABLE


def test_simulated_receipt_never_becomes_valid_public_anchor():
    digest = "a" * 64
    result = IntegrityVerifier().verify(
        request(digest),
        local_chain=LocalChainEvidence(True, digest, 1, evidence_status=EvidenceStatus.SIMULATED),
        receipt=matching_receipt(digest, evidence=EvidenceStatus.SIMULATED),
        observation=confirmed_observation(digest, evidence=EvidenceStatus.SIMULATED),
    )
    assert result.status is VerificationStatus.UNAVAILABLE
    assert result.reason is VerificationReason.SIMULATED_ONLY
    assert result.evidence_status is EvidenceStatus.SIMULATED


def test_future_or_experimental_sources_cannot_be_reported_as_valid():
    digest = "a" * 64
    verifier = IntegrityVerifier()
    for receipt_evidence, observation_evidence in (
        (EvidenceStatus.FUTURE, EvidenceStatus.ASSUMED),
        (EvidenceStatus.ASSUMED, EvidenceStatus.EXPERIMENTAL),
    ):
        result = verifier.verify(
            request(digest),
            local_chain=LocalChainEvidence(True, digest, 1),
            receipt=matching_receipt(digest, evidence=receipt_evidence),
            observation=confirmed_observation(digest, evidence=observation_evidence),
        )
        assert result.status is VerificationStatus.UNAVAILABLE
        assert result.reason is VerificationReason.SOURCE_UNAVAILABLE


def test_unknown_algorithm_or_version_is_never_assumed_to_be_sha256():
    digest = "a" * 64
    result = IntegrityVerifier().verify(
        request(digest),
        local_chain=LocalChainEvidence(True, digest, 1, algorithm="sha3-256"),
        receipt=matching_receipt(digest),
        observation=confirmed_observation(digest),
    )
    assert result.status is VerificationStatus.UNAVAILABLE
    assert result.reason is VerificationReason.UNSUPPORTED_VERSION
