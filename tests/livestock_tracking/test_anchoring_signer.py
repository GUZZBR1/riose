"""Signer-port tests; all signatures are synthetic and non-cryptographic."""

from __future__ import annotations

from dataclasses import fields

import pytest

from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.domain.anchoring_signer import (
    AnchorSigningRequest,
    AnchoringPurpose,
    FakeAnchoringSigner,
    FakeSignatureVerifier,
    SigningReason,
    SigningStatus,
    sign_anchor_transaction,
)
from riose.products.livestock_tracking.domain.contracts import EvidenceStatus


def request(
    message=b"synthetic-transaction-bytes",
    network="devnet",
    expected_public_key="synthetic-public-key-123",
    purpose=AnchoringPurpose.TRANSACTION,
):
    return AnchorSigningRequest(
        message=message,
        network=network,
        expected_public_key=expected_public_key,
        purpose=purpose,
    )


def test_fake_signer_returns_simulated_valid_signature_for_exact_message():
    signer = FakeAnchoringSigner()
    result = sign_anchor_transaction(request(), signer, FakeSignatureVerifier())
    assert result.status is SigningStatus.SIGNED
    assert result.public_key == request().expected_public_key
    assert result.evidence_status is EvidenceStatus.SIMULATED
    assert result.signature.startswith(b"SIMULATED:")
    assert len(signer.calls) == 1


def test_invalid_signature_and_mutated_message_are_rejected():
    signer = FakeAnchoringSigner()
    signature = signer.sign(request())

    class InvalidSigner:
        def sign(self, _request):
            return signature

    result = sign_anchor_transaction(
        request(b"mutated-transaction-bytes"), InvalidSigner(), FakeSignatureVerifier()
    )
    assert result.status is SigningStatus.REJECTED
    assert result.reason is SigningReason.SIGNATURE_INVALID
    assert result.signature is None

    changed_scope = sign_anchor_transaction(
        request(network="testnet"), InvalidSigner(), FakeSignatureVerifier()
    )
    assert changed_scope.status is SigningStatus.REJECTED
    assert changed_scope.reason is SigningReason.SIGNATURE_INVALID


def test_public_key_mismatch_is_rejected_before_signature_verification():
    signer = FakeAnchoringSigner(public_key="another-public-key-123")
    result = sign_anchor_transaction(request(), signer, FakeSignatureVerifier())
    assert result.status is SigningStatus.REJECTED
    assert result.reason is SigningReason.PUBLIC_KEY_MISMATCH
    assert result.public_key is None
    assert result.signature is None


def test_signer_unavailable_and_exception_are_redacted():
    unavailable = sign_anchor_transaction(
        request(), FakeAnchoringSigner(unavailable=True), FakeSignatureVerifier()
    )
    assert unavailable.status is SigningStatus.UNAVAILABLE
    assert unavailable.reason is SigningReason.SIGNER_UNAVAILABLE

    secret = "synthetic-private-seed"

    class BrokenSigner:
        def sign(self, _request):
            raise RuntimeError(secret)

    failed = sign_anchor_transaction(request(), BrokenSigner(), FakeSignatureVerifier())
    assert failed.status is SigningStatus.UNAVAILABLE
    assert failed.reason is SigningReason.SIGNER_UNAVAILABLE
    assert secret not in repr(failed)


def test_verifier_failure_is_unavailable_without_echoing_exception():
    secret = "synthetic-verifier-secret"

    class BrokenVerifier:
        def verify(self, _request, _result):
            raise RuntimeError(secret)

    result = sign_anchor_transaction(request(), FakeAnchoringSigner(), BrokenVerifier())
    assert result.status is SigningStatus.UNAVAILABLE
    assert result.reason is SigningReason.VERIFIER_UNAVAILABLE
    assert secret not in repr(result)


def test_request_has_no_private_key_or_seed_field_and_validates_message_scope():
    names = {field.name for field in fields(AnchorSigningRequest)}
    assert "private_key" not in names
    assert "seed" not in names
    assert "secret" not in names
    with pytest.raises(ValueError):
        AnchorSigningRequest(b"", "devnet", "synthetic-public-key-123", AnchoringPurpose.TRANSACTION)
    with pytest.raises(ValueError):
        AnchorSigningRequest(b"message", "mainnet-beta", "bad key with spaces", AnchoringPurpose.TRANSACTION)


def test_local_event_persistence_does_not_initialize_or_call_signer(tmp_path):
    signer = FakeAnchoringSigner()
    store = Store(tmp_path / "local-only.sqlite3")
    store.create_animal("synthetic-animal", "synthetic-tag", "d" * 64)
    assert store.verify_animal_chain("synthetic-animal")
    assert signer.calls == []
    store.close()
