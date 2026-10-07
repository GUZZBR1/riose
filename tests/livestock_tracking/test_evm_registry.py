"""Offline EVM adapter checks using real EIP-1559 signatures and fake RPC evidence."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
import urllib.error
import pytest

from eth_account import Account
from eth_account.typed_transactions import TypedTransaction
from eth_utils import keccak
from hexbytes import HexBytes

from riose.products.livestock_tracking.adapters.evm_config import EVMNetworkConfig
from riose.products.livestock_tracking.adapters.evm_registry import (
    EVMJsonRpcClient, EVMRegistryAdapter, EVMRpcError, encode_registry_commitment,
)
from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.adapters.persistence.evm_nonce import EVMNonceCoordinator
from riose.products.livestock_tracking.adapters.persistence.publication_outbox import SQLitePublicationOutbox
from riose.products.livestock_tracking.application.publication_dispatcher import PublicationDispatcher
from riose.products.livestock_tracking.domain.privacy import (
    build_public_envelope, serialize_public_envelope,
)
from riose.products.livestock_tracking.domain.publication import ChainReceipt, PreparedPublication
from riose.products.livestock_tracking.cli import main


def _config(sender: str, *, chain_id: int = 31337, address: str = "0x" + "1" * 40):
    return EVMNetworkConfig(
        chain="evm", chain_id=chain_id, expected_genesis_hash="0x" + "3" * 64,
        rpc_url="http://127.0.0.1:8545",
        contract_address=address, expected_code_hash="0x" + keccak(b"registry").hex(),
        publisher_address=sender, confirmations=1, gas_limit=150_000,
        max_fee_per_gas_wei=2_000_000_000, max_priority_fee_per_gas_wei=1_000_000_000,
    )


class FakeRPC:
    def __init__(self, config):
        self.config = config
        self.sends = []
        self.absent = True
        self.fail_send = False
        self.confirm_sends = False
        self.transaction = None
        self.transaction_hash = None

    def ensure_expected_deployment(self):
        return None

    def rpc(self, method, params):
        if method == "eth_getTransactionCount":
            return "0x0"
        if method == "eth_sendRawTransaction":
            if self.fail_send:
                raise EVMRpcError("simulated RPC transport unavailable")
            wire = bytes.fromhex(params[0][2:])
            self.sends.append(wire)
            self.transaction = TypedTransaction.from_bytes(HexBytes(wire)).as_dict()
            self.transaction["from"] = Account.recover_transaction(wire)
            self.transaction_hash = "0x" + keccak(wire).hex()
            return self.transaction_hash
        if method == "eth_estimateGas":
            return "0x5208"
        if method == "eth_getTransactionReceipt":
            if self.confirm_sends and params[0] == self.transaction_hash:
                block_hash = "0x" + "a" * 64
                tx = self.transaction
                tx_to = "0x" + bytes(tx["to"]).hex()
                tx_input = "0x" + bytes(tx["data"]).hex()
                topic0 = "0x" + keccak(text="CommitmentRegistered(bytes32,address)").hex()
                return {
                    "blockNumber": "0x1", "blockHash": block_hash, "status": "0x1",
                    "transactionHash": self.transaction_hash, "to": tx_to,
                    "from": tx["from"], "logs": [{
                        "address": self.config.contract_address,
                        "transactionHash": self.transaction_hash, "blockHash": block_hash,
                        "blockNumber": "0x1", "removed": False,
                        "topics": [topic0, "0x" + bytes(tx["data"])[4:].hex(),
                                   "0x" + ("0" * 24) + tx["from"][2:].lower()],
                        "data": "0x",
                    }],
                }
            return None
        if method == "eth_blockNumber" and self.confirm_sends:
            return "0x1"
        if method == "eth_getBlockByNumber" and self.confirm_sends:
            return {"hash": "0x" + "a" * 64, "timestamp": "0x2"}
        if method == "eth_getTransactionByHash" and self.confirm_sends:
            tx = self.transaction
            return {
                "hash": self.transaction_hash, "blockHash": "0x" + "a" * 64,
                "blockNumber": "0x1", "to": "0x" + bytes(tx["to"]).hex(),
                "from": tx["from"], "input": "0x" + bytes(tx["data"]).hex(),
            }
        raise AssertionError(method)


@pytest.fixture
def prepared_target(tmp_path):
    store = Store(tmp_path / "evm.sqlite3")
    store.create_animal("private-cow", "private-tag", "private-secret")
    event = store.append_animal_event("private-cow", "WEIGHT_RECORDED", {"weight": 425}, 1)
    signer = Account.create()
    config = _config(signer.address)
    outbox = SQLitePublicationOutbox(store)
    request = outbox.enqueue_event(
        event.event_id, destination="evm-registry",
        chain=config.chain, network=config.network_id,
    )
    client = FakeRPC(config)
    adapter = EVMRegistryAdapter(
        config, client=client, signer=signer,
        nonce_coordinator=EVMNonceCoordinator(store),
        publication_id=request["publication_id"],
    )
    yield store, outbox, request, adapter, client
    store.close()


def test_evm_serialization_is_canonical_bytes32_and_private_fields_stay_local(prepared_target):
    _, outbox, request, adapter, client = prepared_target
    envelope = build_public_envelope(request["commitment"])
    assert encode_registry_commitment(envelope) == bytes.fromhex(request["commitment"])
    solana_target = outbox.enqueue_event(
        request["event_id"], destination="solana-memo", chain="solana", network="solana-local",
    )
    assert solana_target["commitment"] == request["commitment"]
    assert json.loads(serialize_public_envelope(envelope))["commitment"] == request["commitment"]
    result = PublicationDispatcher(outbox, [adapter]).process(request["publication_id"])
    assert result["status"] == "RPC_ACCEPTED"
    attempt = outbox.latest_attempt(request["publication_id"])
    assert attempt["payload"] == client.sends[0]
    assert attempt["transaction_id"] == "0x" + keccak(attempt["payload"]).hex()
    adapter.validate_prepared(
        PreparedPublication(attempt["transaction_id"], attempt["payload"], attempt["metadata"]),
        envelope,
    )
    assert b"private-cow" not in attempt["payload"]
    assert b"private-tag" not in attempt["payload"]
    assert b"private-secret" not in attempt["payload"]
    assert outbox.get(request["publication_id"])["commitment"] == request["commitment"]


@pytest.mark.parametrize("failed_targets", [
    (), ("solana",), ("base",), ("arbitrum",),
    ("solana", "base"), ("solana", "arbitrum"), ("base", "arbitrum"),
    ("solana", "base", "arbitrum"),
])
def test_one_event_fans_out_to_three_independent_targets(tmp_path, failed_targets):
    failure_set = set(failed_targets)
    class MockSolana:
        adapter_id = "solana-memo"
        chain = "solana"
        network = "solana-local"

        def healthcheck(self):
            return True

        def prepare(self, envelope):
            self.commitment = envelope.commitment
            return PreparedPublication("mock-solana-1", envelope.commitment.encode(), {})

        def validate_prepared(self, prepared, envelope):
            assert prepared.payload == envelope.commitment.encode()

        def submit(self, prepared):
            if "solana" in failure_set:
                raise RuntimeError("simulated Solana transport unavailable")
            return prepared.transaction_id

        def get_receipt(self, transaction_id, _envelope):
            if "solana" in failure_set:
                return None
            return ChainReceipt(
                chain=self.chain, network=self.network, transaction_id=transaction_id,
                status="CONFIRMED", block_ref="mock-slot-1", evidence_status="MOCKED",
            )

        def verify(self, _envelope, _receipt):
            return True

    store = Store(tmp_path / "three-targets.sqlite3")
    try:
        store.create_animal("private-cow", "private-tag", "private-secret")
        event = store.append_animal_event("private-cow", "WEIGHT_RECORDED", {"weight": 425}, 1)
        signer = Account.create()
        base_config = replace(
            _config(signer.address), chain="base-sepolia", chain_id=84532,
            rpc_url="https://sepolia.base.org",
        )
        arbitrum_config = replace(
            _config(signer.address), chain="arbitrum-sepolia", chain_id=421614,
            rpc_url="https://sepolia-rollup.arbitrum.io/rpc",
        )
        outbox = SQLitePublicationOutbox(store)
        configs = {"base": base_config, "arbitrum": arbitrum_config}
        requests = {
            "solana": outbox.enqueue_event(
                event.event_id, destination="solana-memo", chain="solana", network="solana-local",
            ),
        }
        for key, config in configs.items():
            requests[key] = outbox.enqueue_event(
                event.event_id, destination="evm-registry", chain=config.chain,
                network=config.network_id,
            )

        solana = MockSolana()
        coordinator = EVMNonceCoordinator(store)
        evm_adapters = {}
        clients = {}
        for key, config in configs.items():
            client = FakeRPC(config)
            client.fail_send = key in failure_set
            client.confirm_sends = True
            clients[key] = client
            evm_adapters[key] = EVMRegistryAdapter(
                config, client=client, signer=signer, nonce_coordinator=coordinator,
                publication_id=requests[key]["publication_id"],
            )
        dispatcher = PublicationDispatcher(outbox, [solana, *evm_adapters.values()])
        for key in ("solana", "base", "arbitrum"):
            dispatcher.process(requests[key]["publication_id"])

        commitments = {request["commitment"] for request in requests.values()}
        assert len(commitments) == 1
        assert solana.commitment == requests["solana"]["commitment"]
        expected = {
            key: "UNKNOWN" if key in failure_set else "VERIFIED"
            for key in ("solana", "base", "arbitrum")
        }
        assert {
            key: outbox.get(request["publication_id"])["status"]
            for key, request in requests.items()
        } == expected
        assert all(outbox.get(request["publication_id"])["event_id"] == event.event_id
                   for request in requests.values())
        successful_receipts = [
            outbox.receipts(request["publication_id"])
            for key, request in requests.items()
            if key not in failure_set
        ]
        assert all(any(receipt["state"] == "CONFIRMED" for receipt in receipts)
                   for receipts in successful_receipts)
        assert len({receipts[-1]["transaction_id"] for receipts in successful_receipts}) == len(successful_receipts)
        assert all(b"private-tag" not in client.sends[0] and b"private-secret" not in client.sends[0]
                   for key, client in clients.items() if key not in failure_set)
    finally:
        store.close()


def test_wrong_commitment_or_target_rejects_persisted_signed_wire(prepared_target):
    _, outbox, request, adapter, _ = prepared_target
    PublicationDispatcher(outbox, [adapter]).process(request["publication_id"])
    attempt = outbox.latest_attempt(request["publication_id"])
    prepared = PreparedPublication(attempt["transaction_id"], attempt["payload"], attempt["metadata"])
    with pytest.raises(ValueError, match="prepared EVM transaction"):
        adapter.validate_prepared(prepared, build_public_envelope("0" * 64))
    changed = PreparedPublication("0x" + "0" * 64, prepared.payload, prepared.metadata)
    with pytest.raises(ValueError, match="prepared EVM transaction"):
        adapter.validate_prepared(changed, build_public_envelope(request["commitment"]))
    other = EVMRegistryAdapter(_config(adapter.config.publisher_address, chain_id=31338), client=adapter.client)
    with pytest.raises(ValueError, match="prepared EVM transaction"):
        other.validate_prepared(prepared, build_public_envelope(request["commitment"]))
    other_contract = EVMRegistryAdapter(
        _config(adapter.config.publisher_address, address="0x" + "2" * 40),
        client=adapter.client,
    )
    with pytest.raises(ValueError, match="prepared EVM transaction"):
        other_contract.validate_prepared(prepared, build_public_envelope(request["commitment"]))


def test_missing_receipt_and_restart_only_replay_same_wire(prepared_target):
    store, outbox, request, adapter, client = prepared_target
    dispatcher = PublicationDispatcher(outbox, [adapter])
    dispatcher.process(request["publication_id"])
    first = outbox.latest_attempt(request["publication_id"])
    store.close()
    reopened = Store(store.path)
    restarted_outbox = SQLitePublicationOutbox(reopened)
    restarted_adapter = EVMRegistryAdapter(adapter.config, client=client, publication_id=request["publication_id"])
    restarted = PublicationDispatcher(restarted_outbox, [restarted_adapter])
    assert restarted.reconcile(request["publication_id"])["status"] == "UNKNOWN"
    assert restarted.reconcile(request["publication_id"])["status"] == "UNKNOWN"
    assert client.sends == [first["payload"], first["payload"]]
    assert restarted_outbox.latest_attempt(request["publication_id"])["attempt_id"] == first["attempt_id"]
    reopened.close()


def test_wrong_rpc_chain_or_contract_code_fails_closed():
    signer = Account.create()
    config = _config(signer.address)
    client = EVMJsonRpcClient(config)
    client.rpc = lambda method, params: "0x1" if method == "eth_chainId" else "0x"
    with pytest.raises(EVMRpcError, match="chain ID"):
        client.ensure_expected_deployment()
    client.rpc = lambda method, params: (
        hex(config.chain_id) if method == "eth_chainId"
        else {"hash": config.expected_genesis_hash} if method == "eth_getBlockByNumber" else "0x"
    )
    with pytest.raises(EVMRpcError, match="contract code"):
        client.ensure_expected_deployment()
    client.rpc = lambda method, params: (
        hex(config.chain_id) if method == "eth_chainId"
        else {"hash": "0x" + "4" * 64} if method == "eth_getBlockByNumber" else "0x"
    )
    with pytest.raises(EVMRpcError, match="genesis"):
        client.ensure_expected_deployment()
    client.rpc = lambda method, params: (
        hex(config.chain_id) if method == "eth_chainId"
        else {"hash": config.expected_genesis_hash} if method == "eth_getBlockByNumber"
        else "0x6000"
    )
    with pytest.raises(EVMRpcError, match="code did not match"):
        client.ensure_expected_deployment()


def test_evm_rpc_transport_unavailable_is_sanitized(monkeypatch):
    signer = Account.create()
    client = EVMJsonRpcClient(_config(signer.address))

    def unavailable(*_args, **_kwargs):
        raise urllib.error.URLError("private endpoint detail")

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    with pytest.raises(EVMRpcError, match="transport unavailable") as error:
        client.rpc("eth_chainId", [])
    assert "private endpoint detail" not in str(error.value)


@pytest.mark.parametrize("logs, malformed", [(None, True), ([{}], True), ([], False)])
def test_reverted_receipt_requires_well_formed_empty_logs(prepared_target, logs, malformed):
    _, _, request, adapter, _ = prepared_target
    transaction_id = "0x" + "a" * 64
    block_hash = "0x" + "b" * 64
    data = "0x" + (keccak(text="register(bytes32)")[:4] + bytes.fromhex(request["commitment"])).hex()

    class RevertReceiptRPC:
        config = adapter.config

        def ensure_expected_deployment(self):
            return None

        def rpc(self, method, _params):
            if method == "eth_getTransactionReceipt":
                return {
                    "blockNumber": "0x1", "blockHash": block_hash, "status": "0x0",
                    "transactionHash": transaction_id, "to": self.config.contract_address,
                    "from": self.config.publisher_address, "logs": logs,
                }
            if method == "eth_blockNumber":
                return "0x1"
            if method == "eth_getBlockByNumber":
                return {"hash": block_hash, "timestamp": "0x2"}
            if method == "eth_getTransactionByHash":
                return {
                    "hash": transaction_id, "blockHash": block_hash, "blockNumber": "0x1",
                    "to": self.config.contract_address, "from": self.config.publisher_address,
                    "input": data,
                }
            raise AssertionError(method)

    adapter.client = RevertReceiptRPC()
    envelope = build_public_envelope(request["commitment"])
    if malformed:
        with pytest.raises(EVMRpcError, match="reverted EVM receipt logs"):
            adapter.get_receipt(transaction_id, envelope)
    else:
        assert adapter.get_receipt(transaction_id, envelope).status == "REJECTED"


def test_cli_reports_evm_rpc_errors_without_traceback(monkeypatch, capsys, tmp_path):
    from riose.products.livestock_tracking import publication_cli

    def fail(_args):
        raise EVMRpcError("EVM RPC transport unavailable") from RuntimeError("private URL token")

    monkeypatch.setattr(publication_cli, "run_publication_command", fail)
    with pytest.raises(SystemExit) as error:
        main(["publication", "status", "--db", str(tmp_path / "db.sqlite3"),
              "--publication-id", "publication-1"])
    assert error.value.code == 2
    output = capsys.readouterr().err
    assert "EVM RPC transport unavailable" in output
    assert "private URL token" not in output
    assert "Traceback" not in output


def test_base_sepolia_identity_uses_the_shared_evm_adapter():
    """Exercise Base Sepolia identity with fake deployment-specific values."""
    config = EVMNetworkConfig(
        chain="base-sepolia",
        chain_id=84532,
        expected_genesis_hash="0x0dcc9e089e30b90ddfc55be9a37dd15bc551aeee999d2e2b51414c54eaf934e4",
        rpc_url="https://sepolia.base.org",
        contract_address="0x" + "1" * 40,
        expected_code_hash="0x" + keccak(b"base-sepolia-test-runtime").hex(),
        publisher_address="0x" + "2" * 40,
        confirmations=1,  # Test fixture only; no live confirmation depth is selected.
        gas_limit=150_000,
        max_fee_per_gas_wei=2_000_000_000,
        max_priority_fee_per_gas_wei=1_000_000_000,
    )
    client = EVMJsonRpcClient(config)
    runtime_code = b"base-sepolia-test-runtime"
    responses = {
        "eth_chainId": "0x14a34",
        "eth_getBlockByNumber": {"hash": config.expected_genesis_hash},
        "eth_getCode": "0x" + runtime_code.hex(),
        "eth_call": "0x" + ("0" * 24) + config.publisher_address[2:],
    }
    client.rpc = lambda method, _params: responses[method]

    client.ensure_expected_deployment()
    adapter = EVMRegistryAdapter(config, client=client)

    assert adapter.adapter_id == "evm-registry"
    assert adapter.chain == "base-sepolia"
    assert adapter.network == config.network_id

    responses["eth_chainId"] = "0x2105"
    with pytest.raises(EVMRpcError, match="chain ID"):
        client.ensure_expected_deployment()
    responses["eth_chainId"] = "0x14a34"
    responses["eth_getBlockByNumber"] = {"hash": "0x" + "4" * 64}
    with pytest.raises(EVMRpcError, match="genesis"):
        client.ensure_expected_deployment()
    responses["eth_getBlockByNumber"] = {"hash": config.expected_genesis_hash}
    responses["eth_getCode"] = "0x6000"
    with pytest.raises(EVMRpcError, match="contract code"):
        client.ensure_expected_deployment()


def test_network_config_rejects_implicit_or_wrong_deployment():
    signer = Account.create()
    with pytest.raises(ValueError, match="RPC URL"):
        EVMNetworkConfig(
            chain="evm", chain_id=31337, expected_genesis_hash="0x" + "3" * 64,
            rpc_url="http://public.example",
            contract_address="0x" + "1" * 40,
            expected_code_hash="0x" + "2" * 64,
            publisher_address=signer.address, confirmations=1, gas_limit=150_000,
            max_fee_per_gas_wei=2, max_priority_fee_per_gas_wei=1,
        )


def test_arbitrum_sepolia_config_pins_chain_and_full_rpc():
    signer = Account.create()
    values = {
        "chain": "arbitrum-sepolia", "chain_id": 421614,
        "expected_genesis_hash": "0x" + "3" * 64,
        "rpc_url": "https://sepolia-rollup.arbitrum.io/rpc",
        "contract_address": "0x" + "1" * 40,
        "expected_code_hash": "0x" + "2" * 64,
        "publisher_address": signer.address, "confirmations": 1,
        "gas_limit": 300_000, "max_fee_per_gas_wei": 2_000_000_000,
        "max_priority_fee_per_gas_wei": 1_000_000_000,
    }
    assert EVMNetworkConfig(**values).chain_id == 421614
    with pytest.raises(ValueError, match="chain_id must be 421614"):
        EVMNetworkConfig(**{**values, "chain_id": 31337})
    assert EVMNetworkConfig(**{**values, "chain": "arbitrum"}).chain_id == 421614
    with pytest.raises(ValueError, match="must use an Arbitrum label"):
        EVMNetworkConfig(**{**values, "chain": "evm"})
    with pytest.raises(ValueError, match="full RPC endpoint"):
        EVMNetworkConfig(**{
            **values,
            "rpc_url": "https://sepolia-rollup-sequencer.arbitrum.io/rpc",
        })


def test_expected_deployment_checks_immutable_publisher():
    signer = Account.create()
    code = "0x6000"
    config = replace(
        _config(signer.address),
        expected_code_hash="0x" + keccak(bytes.fromhex(code[2:])).hex(),
    )
    client = EVMJsonRpcClient(config)
    publisher_word = "0x" + ("0" * 24) + signer.address[2:].lower()
    client.rpc = lambda method, params: {
        "eth_chainId": hex(config.chain_id),
        "eth_getBlockByNumber": {"hash": config.expected_genesis_hash},
        "eth_getCode": code,
        "eth_call": publisher_word,
    }[method]
    client.ensure_expected_deployment()
    client.rpc = lambda method, params: (
        publisher_word[:-1] + ("0" if publisher_word[-1] != "0" else "1")
        if method == "eth_call" else {
            "eth_chainId": hex(config.chain_id),
            "eth_getBlockByNumber": {"hash": config.expected_genesis_hash},
            "eth_getCode": code,
        }[method]
    )
    with pytest.raises(EVMRpcError, match="publisher"):
        client.ensure_expected_deployment()
    malformed_word = "0x" + ("f" * 24) + signer.address[2:].lower()
    client.rpc = lambda method, params: (
        malformed_word if method == "eth_call" else {
            "eth_chainId": hex(config.chain_id),
            "eth_getBlockByNumber": {"hash": config.expected_genesis_hash},
            "eth_getCode": code,
        }[method]
    )
    with pytest.raises(EVMRpcError, match="publisher"):
        client.ensure_expected_deployment()


@pytest.mark.parametrize(
    ("estimate", "expected_gas", "raises"),
    [(100_000, 110_000, False), (121_000, None, True)],
)
def test_arbitrum_gas_estimate_uses_configured_cap(tmp_path, estimate, expected_gas, raises):
    store = Store(tmp_path / "arbitrum.sqlite3")
    store.create_animal("local-cow", "local-tag", "local-secret")
    event = store.append_animal_event("local-cow", "WEIGHT_RECORDED", {"weight": 425}, 1)
    signer = Account.create()
    config = replace(
        _config(signer.address), chain="arbitrum-sepolia", chain_id=421614,
        rpc_url="https://sepolia-rollup.arbitrum.io/rpc", gas_limit=120_000,
    )
    outbox = SQLitePublicationOutbox(store)
    request = outbox.enqueue_event(
        event.event_id, destination="evm-registry", chain=config.chain,
        network=config.network_id,
    )
    assert outbox.claim_processing(request["publication_id"])
    client = FakeRPC(config)
    client.estimate = estimate
    client.rpc = lambda method, params: (
        hex(client.estimate) if method == "eth_estimateGas"
        else "0x0" if method == "eth_getTransactionCount"
        else "0x" + keccak(bytes.fromhex(params[0][2:])).hex()
        if method == "eth_sendRawTransaction" else None
    )
    adapter = EVMRegistryAdapter(
        config, client=client, signer=signer,
        nonce_coordinator=EVMNonceCoordinator(store),
        publication_id=request["publication_id"],
    )
    try:
        if raises:
            with pytest.raises(EVMRpcError, match="gas cap"):
                adapter.prepare(build_public_envelope(request["commitment"]))
        else:
            prepared = adapter.prepare(build_public_envelope(request["commitment"]))
            transaction = TypedTransaction.from_bytes(HexBytes(prepared.payload)).as_dict()
            assert transaction["gas"] == expected_gas
    finally:
        store.close()


def test_network_config_rejects_duplicate_keys_and_oversized_json(tmp_path):
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"chain":"one","chain":"two"}')
    with pytest.raises(ValueError, match="configuration"):
        EVMNetworkConfig.from_json_file(duplicate)
    large = tmp_path / "large.json"
    large.write_text("{" + " " * 8192 + "}")
    with pytest.raises(ValueError, match="configuration"):
        EVMNetworkConfig.from_json_file(large)


def test_evm_cli_queue_derives_target_from_config_offline(tmp_path, capsys):
    db = tmp_path / "cli.sqlite3"
    store = Store(db)
    store.create_animal("private-animal", "private-tag", "private-secret")
    event = store.append_animal_event(
        "private-animal", "WEIGHT_RECORDED", {"weight": 425}, 1,
    )
    store.close()
    config = _config(Account.create().address)
    config_file = tmp_path / "evm.json"
    config_file.write_text(json.dumps(asdict(config)))
    assert main([
        "publication", "queue", "--db", str(db), "--event-id", str(event.event_id),
        "--evm-config", str(config_file),
    ]) == 0
    queued = json.loads(capsys.readouterr().out)
    assert queued["chain"] == config.chain
    assert queued["network"] == config.network_id
    assert queued["destination"] == "evm-registry"
    assert queued["status"] == "QUEUED"
    assert "private-animal" not in str(queued)


@pytest.mark.parametrize("after_send", [False, True])
def test_submit_timeout_retains_one_durable_wire_for_replay(prepared_target, after_send):
    _, outbox, request, adapter, client = prepared_target
    original = client.rpc

    def timeout(method, params):
        if method == "eth_sendRawTransaction":
            if after_send:
                original(method, params)
            raise TimeoutError("injected RPC timeout")
        return original(method, params)

    client.rpc = timeout
    result = PublicationDispatcher(outbox, [adapter]).process(request["publication_id"])
    assert result["status"] == "UNKNOWN"
    attempt = outbox.latest_attempt(request["publication_id"])
    assert attempt is not None
    assert client.sends == ([attempt["payload"]] if after_send else [])
    client.rpc = original
    replayed = PublicationDispatcher(outbox, [adapter]).reconcile(request["publication_id"])
    assert replayed["status"] == "RPC_ACCEPTED"
    assert client.sends[-1] == attempt["payload"]
    assert outbox.latest_attempt(request["publication_id"])["attempt_id"] == attempt["attempt_id"]
