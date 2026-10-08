import base64
from dataclasses import replace

import pytest

from riose.products.livestock_tracking.adapters.solana_memo import (
    MEMO_PROGRAM_ID, SolanaMemoAdapter, SolanaMemoClient, SolanaMemoConfig, SolanaRpcError,
)
from riose.products.livestock_tracking.domain.commitment import create_commitment_v1, public_envelope
from riose.products.livestock_tracking.domain.publication import ChainAdapter
from riose.products.livestock_tracking.domain.publication import PreparedPublication
from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.adapters.persistence.publication_outbox import SQLitePublicationOutbox
from riose.products.livestock_tracking.application.publication_dispatcher import PublicationDispatcher
from riose.products.livestock_tracking.domain.privacy import build_public_envelope

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
    with pytest.raises(SolanaRpcError, match="persisted Memo"):
        mismatch.verify(signature, envelope)
    missing = FakeClient(SolanaMemoConfig("https://rpc.example", GENESIS), observed={**result, "transaction": {"message": {"instructions": []}}})
    with pytest.raises(SolanaRpcError, match="persisted Memo"):
        missing.verify(signature, envelope)


@pytest.mark.parametrize("observed", [
    {},
    {"slot": 9, "meta": {"err": None}},
    {"slot": 9, "meta": {}, "transaction": {"message": {"instructions": []}}},
    {"slot": 9, "meta": {"err": None}, "transaction": {"message": {"instructions": {}}}},
    {"slot": 9, "meta": {"err": None}, "transaction": {"message": {"instructions": [{"programId": MEMO_PROGRAM_ID}]}}},
    {"slot": 9, "meta": {"err": None}, "transaction": {"message": {"instructions": [{"programId": MEMO_PROGRAM_ID, "data": "not base58!"}]}}},
])
def test_malformed_transaction_response_is_unknown_not_rejected(observed):
    client = FakeClient(SolanaMemoConfig("https://rpc.example", GENESIS), observed=observed)
    with pytest.raises(SolanaRpcError, match="RPC returned") as error:
        client.verify(_signature(), _envelope())
    assert "not base58!" not in str(error.value)


def test_existing_solana_client_adapts_without_recomputing_commitment():
    from solders.keypair import Keypair

    envelope = _envelope()
    client = FakeClient(SolanaMemoConfig("https://rpc.example", GENESIS))
    adapter = SolanaMemoAdapter(client, Keypair())
    assert isinstance(adapter, ChainAdapter)
    prepared = adapter.prepare(envelope)
    assert adapter.adapter_id == "solana-memo"
    adapter.validate_prepared(prepared, envelope)
    assert prepared.transaction_id
    assert prepared.metadata == {"last_valid_block_height": 100}
    assert adapter.submit(prepared) == prepared.transaction_id
    assert client.calls[0][0] == "getGenesisHash"
    assert client.calls[1][0] == "getLatestBlockhash"
    assert adapter.healthcheck()


def test_persisted_solana_attempt_rejects_changed_signature_wire_or_memo():
    from solders.hash import Hash
    from solders.instruction import Instruction
    from solders.keypair import Keypair
    from solders.message import MessageV0
    from solders.pubkey import Pubkey
    from solders.transaction import VersionedTransaction

    client = FakeClient(SolanaMemoConfig("https://rpc.example", GENESIS))
    signer = Keypair()
    adapter = SolanaMemoAdapter(client, signer)
    envelope = _envelope()
    prepared = adapter.prepare(envelope)
    adapter.validate_prepared(prepared, envelope)

    altered = [
        replace(prepared, transaction_id=_signature()),
        replace(prepared, payload=b"malformed"),
        replace(prepared, payload=prepared.payload + b"\0"),
        replace(prepared, metadata={"last_valid_block_height": -1}),
    ]
    wire = bytearray(prepared.payload)
    wire[1] ^= 1  # Signature no longer verifies against the persisted message.
    altered.append(replace(prepared, payload=bytes(wire)))
    for memo_data, program in [(b"wrong", MEMO_PROGRAM_ID),
                               (b"wrong", str(Pubkey.default()))]:
        msg = MessageV0.try_compile(
            signer.pubkey(), [Instruction(Pubkey.from_string(program), memo_data, [])],
            [], Hash.default(),
        )
        tx = VersionedTransaction(msg, [signer])
        altered.append(PreparedPublication(str(tx.signatures[0]), bytes(tx), prepared.metadata))
    memo = Instruction(Pubkey.from_string(MEMO_PROGRAM_ID), b"extra", [])
    msg = MessageV0.try_compile(signer.pubkey(), [memo, memo], [], Hash.default())
    tx = VersionedTransaction(msg, [signer])
    altered.append(PreparedPublication(str(tx.signatures[0]), bytes(tx), prepared.metadata))
    for attempt in altered:
        with pytest.raises(ValueError, match="prepared Solana"):
            adapter.validate_prepared(attempt, envelope)


def test_prepared_solana_attempt_recovers_after_restart_without_repreparing(tmp_path):
    from solders.keypair import Keypair

    db_path = tmp_path / "solana-recovery.sqlite3"
    store = Store(db_path)
    store.create_animal("private-cow", "private-tag", "private-secret")
    event = store.append_animal_event("private-cow", "WEIGHT_RECORDED", {"weight": 425}, 1)
    outbox = SQLitePublicationOutbox(store)
    config = SolanaMemoConfig("https://rpc.example", GENESIS)
    request = outbox.enqueue_event(
        event.event_id, destination="solana-memo", chain="solana",
        network=config.network_id,
    )
    signer = Keypair()
    initial_client = FakeClient(config)
    initial_adapter = SolanaMemoAdapter(initial_client, signer)
    envelope = build_public_envelope(request["commitment"])
    prepared = initial_adapter.prepare(envelope)
    attempt = outbox.prepare_publication_attempt(
        request["publication_id"], adapter_id=initial_adapter.adapter_id,
        transaction_id=prepared.transaction_id, payload=prepared.payload,
        metadata=prepared.metadata,
    )
    assert outbox.get(request["publication_id"])["status"] == "PREPARED"
    saved_wire = attempt["payload"]
    store.close()

    reopened = Store(db_path)
    try:
        recovered_outbox = SQLitePublicationOutbox(reopened)
        recovery_client = FakeClient(config, observed=None)
        adapter = SolanaMemoAdapter(recovery_client, signer)
        result = PublicationDispatcher(recovered_outbox, [adapter]).reconcile(
            request["publication_id"],
        )
        sent = [params for method, params in recovery_client.calls if method == "sendTransaction"]
        assert result["status"] == "RPC_ACCEPTED"
        assert recovered_outbox.latest_attempt(request["publication_id"])["payload"] == saved_wire
        assert len(sent) == 1
        assert base64.b64decode(sent[0][0]) == saved_wire
        assert not any(method == "getLatestBlockhash" for method, _ in recovery_client.calls)
        assert recovered_outbox.latest_attempt(request["publication_id"])["attempt_id"] == attempt["attempt_id"]
    finally:
        reopened.close()


def test_solana_adapter_submit_checks_cluster_before_network_send():
    from solders.keypair import Keypair

    client = FakeClient(
        SolanaMemoConfig("https://rpc.example", GENESIS),
        genesis="11111111111111111111111111111111",
    )
    adapter = SolanaMemoAdapter(client, Keypair())
    prepared = PreparedPublication(_signature(), b"signed", {"last_valid_block_height": 100})
    with pytest.raises(SolanaRpcError, match="genesis hash"):
        adapter.submit(prepared)
    assert [method for method, _ in client.calls] == ["getGenesisHash"]


def test_missing_transaction_remains_unverified_and_url_must_be_explicit_https():
    with pytest.raises(ValueError):
        SolanaMemoConfig("http://rpc.example", GENESIS)
    with pytest.raises(ValueError, match="allowlisted"):
        SolanaMemoConfig("https://rpc.example", "11111111111111111111111111111111")
    with pytest.raises(ValueError, match="allowlisted"):
        SolanaMemoConfig("https://api.mainnet.solana.com", "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d")
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


def test_keypair_loader_rejects_nonregular_and_trailing_data(tmp_path):
    import json
    import os
    from solders.keypair import Keypair
    from riose.products.livestock_tracking.adapters.solana_memo import load_keypair

    key_path = tmp_path / "keypair.json"
    key_path.write_text(json.dumps(list(bytes(Keypair()))) + " []", encoding="utf-8")
    if os.name == "posix":
        key_path.chmod(0o600)
    with pytest.raises(SolanaRpcError, match="invalid or unreadable"):
        load_keypair(str(key_path))

    with pytest.raises(SolanaRpcError, match="invalid or unreadable"):
        load_keypair(str(tmp_path))


def test_keypair_loader_rejects_shared_permissions_and_symlinks(tmp_path):
    import json
    import os
    from solders.keypair import Keypair
    from riose.products.livestock_tracking.adapters.solana_memo import load_keypair

    generated = Keypair()
    key_path = tmp_path / "keypair.json"
    key_path.write_text(json.dumps(list(bytes(generated))), encoding="utf-8")

    if os.name == "posix":
        key_path.chmod(0o644)
        with pytest.raises(SolanaRpcError, match="invalid or unreadable"):
            load_keypair(str(key_path))
        key_path.chmod(0o600)

    assert load_keypair(str(key_path)).pubkey() == generated.pubkey()

    if hasattr(os, "O_NOFOLLOW"):
        link_path = tmp_path / "keypair-link.json"
        link_path.symlink_to(key_path)
        with pytest.raises(SolanaRpcError, match="invalid or unreadable"):
            load_keypair(str(link_path))
