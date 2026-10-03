"""Contract tests for chain-neutral commitment publication types."""

from __future__ import annotations

import pytest

from riose.products.livestock_tracking.domain.contracts import EvidenceStatus
from riose.products.livestock_tracking.domain.identity import BlockchainAdapter as LegacyIdentityAdapter
from riose.products.livestock_tracking.domain.privacy import build_public_envelope
from riose.products.livestock_tracking.domain.publication import (
    AdapterCapabilities,
    CommitmentPublicationRequest,
    ConfirmationResult,
    DISABLED_PUBLICATION_CAPABILITIES,
    PublicationPort,
    PublicationReason,
    PublicationStatus,
    SubmissionResult,
    publication_capabilities,
)
from riose.products.livestock_tracking.simulation.experimental import BlockchainAdapter as LegacySimulationAdapter


COMMITMENT = "a" * 64


class ContractFixture:
    capabilities = AdapterCapabilities(
        enabled=True,
        destinations=("solana-memo",),
        networks=("devnet",),
        query_supported=True,
        evidence_status=EvidenceStatus.SIMULATED,
    )

    def submit(self, request):
        return SubmissionResult(
            status=PublicationStatus.SUBMITTED,
            commitment=request.envelope.commitment,
            destination=request.destination,
            network=request.network,
            reference="fixture-ref-1",
            evidence_status=EvidenceStatus.SIMULATED,
        )

    def query(self, *, commitment, destination, network, reference):
        return ConfirmationResult(
            status=PublicationStatus.UNKNOWN,
            commitment=commitment,
            destination=destination,
            network=network,
            reference=reference,
            reason=PublicationReason.NOT_FOUND,
            evidence_status=EvidenceStatus.SIMULATED,
        )


def test_publication_request_is_minimal_and_explicitly_scoped():
    request = CommitmentPublicationRequest(
        envelope=build_public_envelope(COMMITMENT),
        destination="solana-memo",
        network="devnet",
        idempotency_reference="local-ref-123",
    )

    assert request.envelope.commitment == COMMITMENT
    assert request.destination == "solana-memo"
    assert request.network == "devnet"
    assert request.idempotency_reference == "local-ref-123"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"destination": "Solana"},
        {"network": "mainnet-beta/secret"},
        {"protocol_version": True},
        {"idempotency_reference": "owner@example.test"},
    ],
)
def test_request_rejects_invalid_scope_without_echoing_values(kwargs):
    values = {
        "envelope": build_public_envelope(COMMITMENT),
        "destination": "solana-memo",
        "network": "devnet",
        "protocol_version": 1,
        "idempotency_reference": None,
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        CommitmentPublicationRequest(**values)


def test_submission_reference_is_not_confirmation():
    result = SubmissionResult(
        status=PublicationStatus.SUBMITTED,
        commitment=COMMITMENT,
        destination="solana-memo",
        network="devnet",
        reference="signature-123",
        evidence_status=EvidenceStatus.SIMULATED,
    )

    assert result.status is PublicationStatus.SUBMITTED
    assert result.status is not PublicationStatus.CONFIRMED
    assert result.evidence_status is EvidenceStatus.SIMULATED
    with pytest.raises(ValueError, match="cannot report confirmation"):
        SubmissionResult(
            status=PublicationStatus.CONFIRMED,
            commitment=COMMITMENT,
            destination="solana-memo",
            network="devnet",
            reference="signature-123",
        )


@pytest.mark.parametrize(
    "status",
    [
        PublicationStatus.SUBMITTED,
        PublicationStatus.UNKNOWN,
        PublicationStatus.UNAVAILABLE,
        PublicationStatus.REJECTED,
    ],
)
def test_lookup_can_report_non_confirmation_without_claiming_invalid(status):
    result = ConfirmationResult(
        status=status,
        commitment=COMMITMENT,
        destination="solana-memo",
        network="devnet",
        reference="signature-123",
        reason=PublicationReason.TIMEOUT if status is PublicationStatus.UNAVAILABLE else None,
        evidence_status=EvidenceStatus.SIMULATED,
    )
    assert result.status is status


def test_confirmation_requires_correlated_opaque_identity_and_allowlisted_reason():
    with pytest.raises(ValueError):
        ConfirmationResult(
            status=PublicationStatus.CONFIRMED,
            commitment="b" * 64,
            destination="solana-memo",
            network="devnet",
            reference="",
        )
    with pytest.raises(ValueError):
        SubmissionResult(
            status=PublicationStatus.UNKNOWN,
            commitment=COMMITMENT,
            destination="solana-memo",
            network="devnet",
            reason="RPC error includes private key",
        )


def test_disabled_adapter_is_explicitly_future_and_has_no_support_claims():
    assert publication_capabilities(None) == DISABLED_PUBLICATION_CAPABILITIES
    assert DISABLED_PUBLICATION_CAPABILITIES.enabled is False
    assert DISABLED_PUBLICATION_CAPABILITIES.evidence_status is EvidenceStatus.FUTURE
    assert not DISABLED_PUBLICATION_CAPABILITIES.destinations
    assert not DISABLED_PUBLICATION_CAPABILITIES.networks


def test_canonical_port_is_single_chain_neutral_contract_and_old_imports_survive():
    assert hasattr(PublicationPort, "submit")
    assert hasattr(PublicationPort, "query")
    assert LegacyIdentityAdapter is not PublicationPort
    assert LegacySimulationAdapter is not PublicationPort

    capabilities = AdapterCapabilities(
        enabled=True,
        destinations=("solana-memo",),
        networks=("devnet",),
        query_supported=True,
        evidence_status=EvidenceStatus.SIMULATED,
    )
    assert capabilities.enabled


def test_local_fixture_obeys_submit_query_contract_without_external_io():
    fixture = ContractFixture()
    assert fixture.capabilities.enabled
    request = CommitmentPublicationRequest(
        envelope=build_public_envelope(COMMITMENT),
        destination="solana-memo",
        network="devnet",
    )
    submitted = fixture.submit(request)
    assert submitted.status is PublicationStatus.SUBMITTED
    observed = fixture.query(
        commitment=request.envelope.commitment,
        destination=request.destination,
        network=request.network,
        reference=submitted.reference,
    )
    assert observed.status is PublicationStatus.UNKNOWN
    assert observed.reason is PublicationReason.NOT_FOUND
    assert observed.evidence_status is EvidenceStatus.SIMULATED


def test_result_redaction_uses_enum_codes_instead_of_raw_errors():
    message = str(
        SubmissionResult(
            status=PublicationStatus.UNAVAILABLE,
            commitment=COMMITMENT,
            destination="solana-memo",
            network="devnet",
            reason=PublicationReason.SIGNER_UNAVAILABLE,
        )
    )
    assert "SIGNER_UNAVAILABLE" in message
    assert "private key" not in message
