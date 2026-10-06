import base64

import pytest

from riose.products.livestock_tracking.adapters.solana_memo import (
    MEMO_PROGRAM_ID, SolanaMemoAdapter, SolanaMemoClient, SolanaMemoConfig, SolanaRpcError,
)
from riose.products.livestock_tracking.domain.commitment import create_commitment_v1, public_envelope
from riose.products.livestock_tracking.domain.publication import ChainAdapter

GENESIS = "GH7ome3EiwEr7tu9JuTh2dpYWBJK3z69Xm1ZE3MEE6JC"


def _b58encode(raw):
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    zeros = len(raw) - len(raw.lstrip(b"\0"))
    value = int.from_bytes(raw, "big")
    output = ""
    while value:
        value, rem = divmod(value, 58)
        output = alphabet[rem] + output
    return "1" * zeros + output


class FakeClient(SolanaMemoClient):
    def __init__(self, config, *, genesis=GENESIS, observed=None):
        super().__init__(config)
        from solders.hash import Hash
        self.genesis = genesis
        self.blockhash = str(Hash.default())
        self.observed = observed
        self.calls = []

    def rpc(self, method, params):
        self.calls.append((method, params))
        if method == "getGenesisHash":
            return self.genesis
        if method == "getLatestBlockhash":
            return {"value": {"blockhash": self.blockhash, "lastValidBlockHeight": 100}}
        if method == "getTransaction":
            return self.observed
        if method == "sendTransaction":
            from solders.transaction import VersionedTransaction
            return str(VersionedTransaction.from_bytes(base64.b64decode(params[0])).signatures[0])
        raise AssertionError(method)


def _envelope():
    return public_envelope(create_commitment_v1("ab" * 32, "cd" * 32))


def _signature():
    from solders.keypair import Keypair
    return str(Keypair().sign_message(b"test signature"))


def test_solders_builds_signed_v0_memo_using_versioned_message_bytes():
    from solders.keypair import Keypair
    from solders.message import to_bytes_versioned
    from solders.transaction import VersionedTransaction

    client = FakeClient(SolanaMemoConfig("https://rpc.example", GENESIS))
    keypair = Keypair()
    wire, signature, last_valid = client.prepare(_envelope(), keypair)
    tx = VersionedTransaction.from_bytes(wire)
    assert str(tx.signatures[0]) == signature
    assert bytes(tx.message) != to_bytes_versioned(tx.message)
    assert tx.signatures[0] == keypair.sign_message(to_bytes_versioned(tx.message))
    assert last_valid == 100
    assert len(wire) <= 1232


def test_cluster_genesis_mismatch_fails_before_blockhash_or_send():
    from solders.keypair import Keypair

    client = FakeClient(SolanaMemoConfig("https://rpc.example", GENESIS), genesis="11111111111111111111111111111111")
    with pytest.raises(SolanaRpcError, match="genesis hash"):
        client.prepare(_envelope(), Keypair())
    assert [name for name, _ in client.calls] == ["getGenesisHash"]


def test_confirmation_requires_successful_transaction_and_exact_public_memo():
    from solders.keypair import Keypair
    from riose.products.livestock_tracking.domain.privacy import serialize_public_envelope

    envelope = _envelope()
    expected = serialize_public_envelope(envelope)
    instruction = {"programId": MEMO_PROGRAM_ID, "data": _b58encode(expected)}
    result = {"slot": 9, "meta": {"err": None}, "transaction": {"message": {"instructions": [instruction]}}}
    client = FakeClient(SolanaMemoConfig("https://rpc.example", GENESIS), observed=result)
    signature = _signature()
    assert client.verify(signature, envelope) == (True, 9)
    failed = FakeClient(SolanaMemoConfig("https://rpc.example", GENESIS), observed={**result, "meta": {"err": {"InstructionError": [0, "failed"]}}})
    assert failed.verify(signature, envelope) == (False, 9)
    mismatch = FakeClient(SolanaMemoConfig("https://rpc.example", GENESIS), observed={**result, "transaction": {"message": {"instructions": [{"programId": MEMO_PROGRAM_ID, "data": _b58encode(b"wrong")}]}}})
    assert mismatch.verify(signature, envelope) == (False, 9)


def test_existing_solana_client_adapts_without_recomputing_commitment():
    from solders.keypair import Keypair

    envelope = _envelope()
    client = FakeClient(SolanaMemoConfig("https://rpc.example", GENESIS))
    adapter = SolanaMemoAdapter(client, Keypair())
    assert isinstance(adapter, ChainAdapter)
    prepared = adapter.prepare(envelope)
    assert prepared.transaction_id
    assert prepared.metadata == {"last_valid_block_height": 100}
    assert adapter.submit(prepared) == prepared.transaction_id
    assert client.calls[0][0] == "getGenesisHash"
    assert client.calls[1][0] == "getLatestBlockhash"
    assert adapter.healthcheck()


def test_missing_transaction_remains_unverified_and_url_must_be_explicit_https():
    with pytest.raises(ValueError):
        SolanaMemoConfig("http://rpc.example", GENESIS)
    with pytest.raises(ValueError, match="allowlisted"):
        SolanaMemoConfig("https://rpc.example", "11111111111111111111111111111111")
    client = FakeClient(SolanaMemoConfig("https://rpc.example", GENESIS), observed=None)
    assert client.verify(_signature(), _envelope()) == (None, None)


def test_rpc_transport_malformed_response_and_signer_failure_are_sanitized(tmp_path, monkeypatch):
    import urllib.error
    from riose.products.livestock_tracking.adapters import solana_memo

    client = SolanaMemoClient(SolanaMemoConfig("https://rpc.example", GENESIS))
    def unavailable(*_args, **_kwargs):
        raise urllib.error.URLError("private transport detail")
    monkeypatch.setattr(solana_memo.urllib.request, "urlopen", unavailable)
    with pytest.raises(SolanaRpcError, match="transport unavailable") as error:
        client.rpc("getGenesisHash", [])
    assert "private transport detail" not in str(error.value)

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def read(self, _limit): return b'{"jsonrpc":"2.0","id":999,"result":"wrong"}'
    monkeypatch.setattr(solana_memo.urllib.request, "urlopen", lambda *_a, **_k: Response())
    with pytest.raises(SolanaRpcError, match="request failed"):
        client.rpc("getGenesisHash", [])

    with pytest.raises(SolanaRpcError, match="invalid or unreadable"):
        solana_memo.load_keypair(str(tmp_path / "missing.json"))
