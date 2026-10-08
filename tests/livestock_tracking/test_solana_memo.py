import base64
from dataclasses import replace
import json
import os
from pathlib import Path
import traceback

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
from riose.products.livestock_tracking.domain.privacy import (
    build_public_envelope,
    serialize_public_envelope,
)

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
    signature = _signature()
    result = {"slot": 9, "meta": {"err": None}, "transaction": {
        "signatures": [signature], "message": {"instructions": [instruction]},
    }}
    client = FakeClient(SolanaMemoConfig("https://rpc.example", GENESIS), observed=result)
    assert client.verify(signature, envelope) == (True, 9)
    failed = FakeClient(SolanaMemoConfig("https://rpc.example", GENESIS), observed={**result, "meta": {"err": {"InstructionError": [0, "failed"]}}})
    assert failed.verify(signature, envelope) == (False, 9)
    mismatch = FakeClient(SolanaMemoConfig("https://rpc.example", GENESIS), observed={**result, "transaction": {
        "signatures": [signature], "message": {"instructions": [{"programId": MEMO_PROGRAM_ID, "data": _b58encode(b"wrong")}]},
    }})
    with pytest.raises(SolanaRpcError, match="persisted Memo"):
        mismatch.verify(signature, envelope)
    missing = FakeClient(SolanaMemoConfig("https://rpc.example", GENESIS), observed={**result, "transaction": {
        "signatures": [signature], "message": {"instructions": []},
    }})
    with pytest.raises(SolanaRpcError, match="persisted Memo"):
        missing.verify(signature, envelope)


def test_solana_receipt_must_contain_the_requested_transaction_signature():
    result = {
        "slot": 9, "meta": {"err": None},
        "transaction": {
            "signatures": [_signature()],
            "message": {"instructions": [{
                "programId": MEMO_PROGRAM_ID,
                "data": _b58encode(serialize_public_envelope(_envelope())),
            }]},
        },
    }
    client = FakeClient(SolanaMemoConfig("https://rpc.example", GENESIS), observed=result)
    with pytest.raises(SolanaRpcError, match="invalid transaction"):
        client.verify(_signature(), _envelope())


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


def _write_synthetic_keypair(path: Path) -> tuple[Path, str]:
    from solders.keypair import Keypair

    keypair = Keypair()
    path.write_text(json.dumps(list(keypair.to_bytes())), encoding="utf-8")
    path.chmod(0o600)
    return path, str(keypair.pubkey())


def test_keypair_loader_accepts_valid_private_regular_file(tmp_path):
    from riose.products.livestock_tracking.adapters.solana_memo import load_keypair

    path, expected_pubkey = _write_synthetic_keypair(tmp_path / "synthetic-keypair.json")
    assert str(load_keypair(str(path)).pubkey()) == expected_pubkey


@pytest.mark.parametrize("mode", [0o640, 0o644, 0o660, 0o666, 0o622])
@pytest.mark.skipif(os.name != "posix", reason="POSIX file mode checks are platform-specific")
def test_keypair_loader_rejects_shared_or_writable_permissions(tmp_path, mode):
    from riose.products.livestock_tracking.adapters.solana_memo import load_keypair

    path, _ = _write_synthetic_keypair(tmp_path / "synthetic-keypair.json")
    path.chmod(mode)
    with pytest.raises(SolanaRpcError, match="invalid or unreadable"):
        load_keypair(str(path))


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink behavior is platform-specific")
@pytest.mark.parametrize("dangling", [False, True])
def test_keypair_loader_rejects_symlinks(tmp_path, dangling):
    from riose.products.livestock_tracking.adapters.solana_memo import load_keypair

    target = tmp_path / "target.json"
    if not dangling:
        _write_synthetic_keypair(target)
    path = tmp_path / "keypair-link.json"
    path.symlink_to(target)
    with pytest.raises(SolanaRpcError, match="invalid or unreadable"):
        load_keypair(str(path))


def test_keypair_loader_rejects_directory_and_fifo(tmp_path):
    from riose.products.livestock_tracking.adapters.solana_memo import load_keypair

    with pytest.raises(SolanaRpcError, match="invalid or unreadable"):
        load_keypair(str(tmp_path))
    if os.name == "posix" and hasattr(os, "mkfifo"):
        fifo = tmp_path / "keypair.fifo"
        os.mkfifo(fifo)
        with pytest.raises(SolanaRpcError, match="invalid or unreadable"):
            load_keypair(str(fifo))


@pytest.mark.parametrize("raw", [
    b"",
    b"not-json",
    b"[1, 2, 3",
    b"[] []",
    b"{\"keypair\": []}",
    b"{\"keypair\": [], \"keypair\": []}",
    b"[" + b"0," * 256 + b"0]",
    b"\xff\xfe",
])
def test_keypair_loader_rejects_empty_malformed_truncated_oversized_and_wrong_encodings(tmp_path, raw):
    from riose.products.livestock_tracking.adapters.solana_memo import load_keypair

    path = tmp_path / "bad-keypair.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    with pytest.raises(SolanaRpcError, match="invalid or unreadable"):
        load_keypair(str(path))


def test_keypair_loader_rejects_valid_prefix_with_trailing_content(tmp_path):
    from solders.keypair import Keypair
    from riose.products.livestock_tracking.adapters.solana_memo import load_keypair

    path = tmp_path / "trailing-keypair.json"
    path.write_text(json.dumps(list(Keypair().to_bytes())) + " garbage", encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(SolanaRpcError, match="invalid or unreadable"):
        load_keypair(str(path))


@pytest.mark.parametrize("length", [32, 63])
def test_keypair_loader_rejects_wrong_secret_key_lengths(tmp_path, length):
    from riose.products.livestock_tracking.adapters.solana_memo import load_keypair

    path = tmp_path / "wrong-length-keypair.json"
    path.write_text(json.dumps([0] * length), encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(SolanaRpcError, match="invalid or unreadable"):
        load_keypair(str(path))


def test_keypair_loader_rejects_invalid_input_without_exception_chain(tmp_path):
    from riose.products.livestock_tracking.adapters.solana_memo import load_keypair

    secret_like = b"private-material-must-not-survive-in-tracebacks"
    path = tmp_path / "invalid-keypair.json"
    path.write_bytes(secret_like)
    path.chmod(0o600)
    with pytest.raises(SolanaRpcError) as raised:
        load_keypair(str(path))
    rendered = "".join(traceback.format_exception(raised.value))
    assert secret_like.decode() not in rendered
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


@pytest.mark.skipif(os.name != "posix", reason="descriptor-pinned replacement requires POSIX symlinks")
def test_keypair_loader_reads_open_descriptor_if_path_is_replaced_after_open(tmp_path, monkeypatch):
    from riose.products.livestock_tracking.adapters import solana_memo

    path, expected_pubkey = _write_synthetic_keypair(tmp_path / "keypair.json")
    moved = tmp_path / "original.json"
    real_open = os.open

    def replace_path_after_open(open_path, flags):
        descriptor = real_open(open_path, flags)
        if Path(open_path) == path:
            os.replace(path, moved)
            path.symlink_to(moved)
        return descriptor

    monkeypatch.setattr(solana_memo.os, "open", replace_path_after_open)
    assert str(solana_memo.load_keypair(str(path)).pubkey()) == expected_pubkey
