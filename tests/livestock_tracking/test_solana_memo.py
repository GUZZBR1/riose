"""Offline contract tests for the opt-in Solana Memo adapter."""

from __future__ import annotations

import base64

import pytest
from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from riose.products.livestock_tracking.adapters.solana_memo import (
    MAX_RPC_RESPONSE_BYTES,
    HttpSolanaRpc,
    MEMO_PROGRAM_ID,
    SolanaMemoConfig,
    SolanaMemoPublicationAdapter,
)
from riose.products.livestock_tracking.domain.anchoring_signer import (
    AnchorSigningRequest,
    SigningResult,
    SigningStatus,
)
from riose.products.livestock_tracking.domain.contracts import EvidenceStatus
from riose.products.livestock_tracking.domain.privacy import (
    build_public_envelope,
    serialize_public_envelope,
)
from riose.products.livestock_tracking.domain.publication import (
    CommitmentPublicationRequest,
    PublicationStatus,
)


class StubSigner:
    def __init__(self) -> None:
        self.keypair = Keypair()
        self.requests: list[AnchorSigningRequest] = []

    def sign(self, request: AnchorSigningRequest) -> SigningResult:
        self.requests.append(request)
        return SigningResult(
            SigningStatus.SIGNED,
            public_key=str(self.keypair.pubkey()),
            signature=bytes(self.keypair.sign_message(request.message)),
            evidence_status=EvidenceStatus.VALIDATED,
        )


class StubVerifier:
    def verify(self, request: AnchorSigningRequest, result: SigningResult) -> bool:
        return Signature.from_bytes(result.signature).verify(
            Pubkey.from_string(result.public_key), request.message
        )


class FakeSolanaRpc:
    evidence_status = EvidenceStatus.SIMULATED

    def __init__(self, genesis_hash: str, *, confirmation_status: str = "confirmed") -> None:
        self.genesis_hash = genesis_hash
        self.confirmation_status = confirmation_status
        self.status_err_present = True
        self.meta_err_present = True
        self.calls: list[tuple[str, list[object]]] = []
        self.transaction = None
        self.reference = None

    def call(self, method: str, params: list[object]) -> object:
        self.calls.append((method, params))
        if method == "getGenesisHash":
            return self.genesis_hash
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": str(Hash.new_unique())}}
        if method == "sendTransaction":
            encoded, options = params
            assert options["encoding"] == "base64"
            raw = base64.b64decode(encoded)
            transaction = VersionedTransaction.from_bytes(raw)
            self.reference = str(transaction.signatures[0])
            message = transaction.message
            instruction = message.instructions[0]
            assert str(message.account_keys[instruction.program_id_index]) == MEMO_PROGRAM_ID
            self.transaction = {
                "transaction": [base64.b64encode(raw).decode("ascii"), "base64"],
                "meta": {"err": None} if self.meta_err_present else {},
            }
            return self.reference
        if method == "getTransaction":
            return self.transaction
        if method == "getSignatureStatuses":
            status = {"confirmationStatus": self.confirmation_status}
            if self.status_err_present:
                status["err"] = None
            return {"value": [status]}
        raise AssertionError(f"unexpected RPC method {method}")


def make_adapter(*, confirmation_status: str = "confirmed"):
    signer = StubSigner()
    genesis_hash = str(Hash.new_unique())
    rpc = FakeSolanaRpc(genesis_hash, confirmation_status=confirmation_status)
    config = SolanaMemoConfig(
        rpc_url="https://rpc.example.invalid",
        cluster="devnet",
        payer_public_key=str(signer.keypair.pubkey()),
        expected_genesis_hash=genesis_hash,
    )
    return SolanaMemoPublicationAdapter(config, signer, StubVerifier(), rpc), signer, rpc


def test_config_requires_explicit_rpc_cluster_and_safe_endpoint_shape():
    with pytest.raises(ValueError):
        SolanaMemoConfig("", "devnet", "payer", str(Hash.new_unique()))
    with pytest.raises(ValueError):
        SolanaMemoConfig(
            "https://user:pass@rpc.example", "devnet", "payer", str(Hash.new_unique())
        )
    genesis_hash = str(Hash.new_unique())
    config = SolanaMemoConfig("https://rpc.example", "devnet", "payer", genesis_hash)
    assert config.network.startswith("solana-genesis-")


def test_submit_compiles_and_signs_only_the_guarded_public_envelope():
    adapter, signer, rpc = make_adapter()
    request = CommitmentPublicationRequest(
        build_public_envelope("a" * 64), "solana-memo", adapter.capabilities.networks[0]
    )
    result = adapter.submit(request)
    assert result.status is PublicationStatus.SUBMITTED
    assert result.evidence_status is EvidenceStatus.SIMULATED
    assert result.reference == rpc.reference
    assert len(signer.requests) == 1
    assert signer.requests[0].network == adapter.capabilities.networks[0]
    assert b"animal" not in signer.requests[0].message
    assert [method for method, _ in rpc.calls] == [
        "getGenesisHash", "getLatestBlockhash", "sendTransaction"
    ]


@pytest.mark.parametrize(
    ("observed", "expected"),
    [
        ("processed", PublicationStatus.SUBMITTED),
        ("confirmed", PublicationStatus.CONFIRMED),
        ("finalized", PublicationStatus.CONFIRMED),
    ],
)
def test_query_correlates_memo_and_keeps_pending_distinct(observed, expected):
    adapter, _, rpc = make_adapter(confirmation_status=observed)
    request = CommitmentPublicationRequest(
        build_public_envelope("a" * 64), "solana-memo", adapter.capabilities.networks[0]
    )
    submitted = adapter.submit(request)
    result = adapter.query(
        commitment="a" * 64,
        destination="solana-memo",
        network=adapter.capabilities.networks[0],
        reference=submitted.reference,
    )
    assert result.status is expected
    assert result.evidence_status is EvidenceStatus.SIMULATED
    assert [method for method, _ in rpc.calls][-3:] == [
        "getGenesisHash", "getTransaction", "getSignatureStatuses"
    ]


def test_query_rejects_a_memo_for_a_different_commitment():
    adapter, _, _ = make_adapter()
    request = CommitmentPublicationRequest(
        build_public_envelope("a" * 64), "solana-memo", adapter.capabilities.networks[0]
    )
    submitted = adapter.submit(request)
    result = adapter.query(
        commitment="b" * 64,
        destination="solana-memo",
        network=adapter.capabilities.networks[0],
        reference=submitted.reference,
    )
    assert result.status is PublicationStatus.REJECTED


def test_query_rejects_a_forged_rpc_transaction_with_the_same_reference():
    from solders.instruction import Instruction
    from solders.message import MessageV0

    adapter, signer, rpc = make_adapter()
    request = CommitmentPublicationRequest(
        build_public_envelope("a" * 64), "solana-memo", adapter.capabilities.networks[0]
    )
    submitted = adapter.submit(request)
    original = VersionedTransaction.from_bytes(
        base64.b64decode(rpc.transaction["transaction"][0])
    )
    altered = MessageV0.try_compile(
        payer=signer.keypair.pubkey(),
        instructions=[Instruction(Pubkey.from_string(MEMO_PROGRAM_ID), b"forged", [])],
        address_lookup_table_accounts=[],
        recent_blockhash=original.message.recent_blockhash,
    )
    forged = VersionedTransaction.populate(
        altered, [Signature.from_string(submitted.reference)]
    )
    rpc.transaction["transaction"] = [base64.b64encode(bytes(forged)).decode("ascii"), "base64"]
    result = adapter.query(
        commitment="a" * 64,
        destination="solana-memo",
        network=adapter.capabilities.networks[0],
        reference=submitted.reference,
    )
    assert result.status is PublicationStatus.REJECTED


@pytest.mark.parametrize("missing", ["meta_err", "status_err"])
def test_partial_rpc_success_response_never_promotes_to_confirmed(missing):
    adapter, _, rpc = make_adapter(confirmation_status="confirmed")
    request = CommitmentPublicationRequest(
        build_public_envelope("a" * 64), "solana-memo", adapter.capabilities.networks[0]
    )
    submitted = adapter.submit(request)
    if missing == "meta_err":
        rpc.transaction["meta"] = {}
    else:
        rpc.status_err_present = False
    result = adapter.query(
        commitment="a" * 64,
        destination="solana-memo",
        network=adapter.capabilities.networks[0],
        reference=submitted.reference,
    )
    assert result.status is PublicationStatus.UNAVAILABLE


def test_rpc_genesis_hash_must_match_the_explicit_network_configuration():
    adapter, signer, rpc = make_adapter()
    rpc.genesis_hash = str(Hash.new_unique())
    request = CommitmentPublicationRequest(
        build_public_envelope("a" * 64), "solana-memo", adapter.capabilities.networks[0]
    )
    result = adapter.submit(request)
    assert result.status is PublicationStatus.REJECTED
    assert [method for method, _ in rpc.calls] == ["getGenesisHash"]


def test_query_rejects_a_valid_transaction_from_a_different_configured_payer():
    adapter, _, rpc = make_adapter()
    request = CommitmentPublicationRequest(
        build_public_envelope("a" * 64), "solana-memo", adapter.capabilities.networks[0]
    )
    submitted = adapter.submit(request)
    outsider = Keypair()
    message = MessageV0.try_compile(
        payer=outsider.pubkey(),
        instructions=[
            Instruction(
                Pubkey.from_string(MEMO_PROGRAM_ID),
                serialize_public_envelope(request.envelope),
                [],
            )
        ],
        address_lookup_table_accounts=[],
        recent_blockhash=Hash.new_unique(),
    )
    transaction = VersionedTransaction(message, [outsider])
    rpc.transaction = {
        "transaction": [base64.b64encode(bytes(transaction)).decode("ascii"), "base64"],
        "meta": {"err": None},
    }
    rpc.reference = str(transaction.signatures[0])
    result = adapter.query(
        commitment="a" * 64,
        destination="solana-memo",
        network=adapter.capabilities.networks[0],
        reference=rpc.reference,
    )
    assert result.status is PublicationStatus.REJECTED
    assert submitted.reference != rpc.reference


def test_query_rejects_malformed_commitment_and_signature_before_rpc():
    adapter, _, rpc = make_adapter()
    with pytest.raises(ValueError):
        adapter.query(
            commitment="bad",
            destination="solana-memo",
            network=adapter.capabilities.networks[0],
            reference="1" * 88,
        )
    with pytest.raises(ValueError):
        adapter.query(
            commitment="a" * 64,
            destination="solana-memo",
            network=adapter.capabilities.networks[0],
            reference="0" * 88,
        )
    assert not rpc.calls


def test_http_rpc_rejects_wrong_request_id(monkeypatch):
    import io
    import json
    import urllib.request

    def wrong_id(*_args, **_kwargs):
        return io.BytesIO(json.dumps({"jsonrpc": "2.0", "id": 99, "result": "x"}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", wrong_id)
    with pytest.raises(ValueError):
        HttpSolanaRpc("https://rpc.example").call("getGenesisHash", [])


def test_http_rpc_caps_response_body(monkeypatch):
    import io
    import urllib.request

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(b"x" * (MAX_RPC_RESPONSE_BYTES + 1)),
    )
    with pytest.raises(ValueError, match="size limit"):
        HttpSolanaRpc("https://rpc.example").call("getGenesisHash", [])


def test_adapter_is_explicit_opt_in_and_has_no_default_mainnet_capability():
    adapter, _, _ = make_adapter()
    assert adapter.capabilities.enabled
    assert adapter.capabilities.destinations == ("solana-memo",)
    assert adapter.capabilities.networks[0].startswith("solana-genesis-")
    assert adapter.capabilities.evidence_status is EvidenceStatus.FUTURE
