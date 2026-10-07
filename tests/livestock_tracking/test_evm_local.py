"""Real local EVM deployment and publication through the production dispatcher."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time
import urllib.request

import pytest
from eth_account import Account
from eth_utils import keccak, to_checksum_address

from riose.products.livestock_tracking.adapters.evm_config import EVMNetworkConfig
from riose.products.livestock_tracking.adapters.evm_registry import (
    EVMJsonRpcClient, EVMRegistryAdapter, EVMRpcError,
)
from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.adapters.persistence.evm_nonce import EVMNonceCoordinator
from riose.products.livestock_tracking.adapters.persistence.publication_outbox import SQLitePublicationOutbox
from riose.products.livestock_tracking.application.publication_dispatcher import PublicationDispatcher
from riose.products.livestock_tracking.domain.privacy import build_public_envelope


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"


def _rpc(url: str, method: str, params: list) -> object:
    wire = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    with urllib.request.urlopen(
        urllib.request.Request(url, data=wire, headers={"Content-Type": "application/json"}),
        timeout=10,
    ) as response:
        result = json.load(response)
    if "error" in result:
        raise AssertionError(f"local EVM RPC failed: {method}: {result['error']}")
    return result["result"]


def _wait_receipt(url: str, tx_hash: str) -> dict:
    for _ in range(50):
        receipt = _rpc(url, "eth_getTransactionReceipt", [tx_hash])
        if receipt is not None:
            return receipt
        time.sleep(0.1)
    raise AssertionError("local EVM did not mine the transaction")


def test_real_local_evm_registry_deploy_dispatch_duplicate_and_revert(tmp_path):
    if not (CONTRACTS / "package-lock.json").exists():
        raise AssertionError("contract toolchain lock is missing")
    secret_file = tmp_path / "local-signer.json"
    server = subprocess.Popen(
        ["node", str(CONTRACTS / "test/local_evm_server.cjs"), str(secret_file)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        ready = server.stdout.readline()
        if not ready:
            raise AssertionError("local EVM server did not start")
        url = f"http://127.0.0.1:{json.loads(ready)['port']}"
        secret = json.loads(secret_file.read_text())
        assert secret_file.stat().st_mode & 0o077 == 0
        signer = Account.from_key(secret["privateKey"])
        assert signer.address.lower() == secret["address"].lower()
        compiled = json.loads(subprocess.check_output(
            ["node", str(CONTRACTS / "test/compile_registry.cjs"),
             str(CONTRACTS / "src/RioseCommitmentRegistry.sol")], text=True,
        ))
        bytecode = bytes.fromhex(compiled["evm"]["bytecode"]["object"]) + bytes.fromhex(
            "0" * 24 + signer.address[2:]
        )
        deployment = Account.sign_transaction({
            "type": 2, "chainId": 31337, "nonce": 0, "gas": 2_000_000,
            "maxFeePerGas": 2_000_000_000, "maxPriorityFeePerGas": 1_000_000_000,
            "value": 0, "data": bytecode,
        }, signer.key)
        deploy_hash = _rpc(url, "eth_sendRawTransaction", ["0x" + deployment.raw_transaction.hex()])
        deploy_receipt = _wait_receipt(url, deploy_hash)
        assert deploy_receipt["status"] == "0x1"
        address = deploy_receipt["contractAddress"]
        code = bytes.fromhex(_rpc(url, "eth_getCode", [address, "latest"])[2:])
        assert code
        genesis_hash = _rpc(url, "eth_getBlockByNumber", ["0x0", False])["hash"]
        config = EVMNetworkConfig(
            chain="local", chain_id=31337, expected_genesis_hash=genesis_hash,
            rpc_url=url, contract_address=address,
            expected_code_hash="0x" + keccak(code).hex(), publisher_address=signer.address,
            confirmations=1, gas_limit=150_000,
            max_fee_per_gas_wei=2_000_000_000,
            max_priority_fee_per_gas_wei=1_000_000_000,
        )
        store = Store(tmp_path / "riose.sqlite3")
        try:
            store.create_animal("local-animal", "local-tag", "local-secret")
            event = store.append_animal_event("local-animal", "WEIGHT_RECORDED", {"weight": 425}, 1)
            outbox = SQLitePublicationOutbox(store)
            request = outbox.enqueue_event(event.event_id, destination="evm-registry",
                                           chain=config.chain, network=config.network_id)
            adapter = EVMRegistryAdapter(
                config, signer=signer, nonce_coordinator=EVMNonceCoordinator(store),
                publication_id=request["publication_id"],
            )
            result = PublicationDispatcher(outbox, [adapter]).process(request["publication_id"])
            assert result["status"] == "VERIFIED"
            attempt = outbox.latest_attempt(request["publication_id"])
            receipt = _wait_receipt(url, attempt["transaction_id"])
            assert receipt["status"] == "0x1"
            assert len(receipt["logs"]) == 1
            assert receipt["logs"][0]["topics"][1].lower() == "0x" + request["commitment"]
            assert receipt["logs"][0]["topics"][2].lower().endswith(signer.address[2:].lower())
            assert "0x" + request["commitment"] in receipt["logs"][0]["topics"]
            assert _rpc(url, "eth_call", [{"to": address, "data": "0x" + keccak(text="registered(bytes32)")[:4].hex() + request["commitment"]}, "latest"]) == "0x" + "0" * 63 + "1"

            bad_client = EVMJsonRpcClient(config)
            original_rpc = bad_client.rpc

            def removed_log(method, params):
                observed = original_rpc(method, params)
                if method == "eth_getTransactionReceipt" and observed is not None:
                    observed["logs"][0]["removed"] = True
                return observed

            bad_client.rpc = removed_log
            with pytest.raises(EVMRpcError, match="registry commitment"):
                EVMRegistryAdapter(config, client=bad_client).get_receipt(
                    attempt["transaction_id"], build_public_envelope(request["commitment"]),
                )

            def displaced_transaction(method, params):
                observed = original_rpc(method, params)
                if method == "eth_getTransactionByHash" and observed is not None:
                    observed["blockHash"] = "0x" + "0" * 64
                return observed

            bad_client.rpc = displaced_transaction
            with pytest.raises(EVMRpcError, match="transaction did not match"):
                EVMRegistryAdapter(config, client=bad_client).get_receipt(
                    attempt["transaction_id"], build_public_envelope(request["commitment"]),
                )

            outsider = _rpc(url, "eth_accounts", [])[1]
            unauthorized_hash = _rpc(url, "eth_sendTransaction", [{
                "from": outsider, "to": address, "gas": hex(150_000),
                "data": "0x" + keccak(text="register(bytes32)")[:4].hex() + "ab" * 32,
            }])
            assert _wait_receipt(url, unauthorized_hash)["status"] == "0x0"

            # The contract rejects a second transaction with the same commitment.
            duplicate_data = keccak(text="register(bytes32)")[:4] + bytes.fromhex(request["commitment"])
            duplicate = Account.sign_transaction({
                "type": 2, "chainId": 31337, "nonce": 2, "to": to_checksum_address(address), "gas": 150_000,
                "maxFeePerGas": 2_000_000_000, "maxPriorityFeePerGas": 1_000_000_000,
                "value": 0, "data": duplicate_data,
            }, signer.key)
            duplicate_hash = _rpc(url, "eth_sendRawTransaction", ["0x" + duplicate.raw_transaction.hex()])
            duplicate_receipt = _wait_receipt(url, duplicate_hash)
            assert duplicate_receipt["status"] == "0x0"
            assert duplicate_receipt["logs"] == []
            assert adapter.get_receipt(duplicate_hash, build_public_envelope(request["commitment"])).status == "REJECTED"

            zero = Account.sign_transaction({
                "type": 2, "chainId": 31337, "nonce": 3, "to": to_checksum_address(address),
                "gas": 150_000, "maxFeePerGas": 2_000_000_000,
                "maxPriorityFeePerGas": 1_000_000_000, "value": 0,
                "data": keccak(text="register(bytes32)")[:4] + bytes(32),
            }, signer.key)
            zero_hash = _rpc(url, "eth_sendRawTransaction", ["0x" + zero.raw_transaction.hex()])
            assert _wait_receipt(url, zero_hash)["status"] == "0x0"

            next_event = store.append_animal_event(
                "local-animal", "WEIGHT_RECORDED", {"weight": 430}, 2,
            )
            next_request = outbox.enqueue_event(
                next_event.event_id, destination="evm-registry",
                chain=config.chain, network=config.network_id,
            )
            next_adapter = EVMRegistryAdapter(
                config, signer=signer, nonce_coordinator=EVMNonceCoordinator(store),
                publication_id=next_request["publication_id"],
            )
            next_result = PublicationDispatcher(outbox, [next_adapter]).process(next_request["publication_id"])
            assert next_result["status"] == "VERIFIED"
            next_attempt = outbox.latest_attempt(next_request["publication_id"])
            next_receipt = _wait_receipt(url, next_attempt["transaction_id"])
            assert next_receipt["logs"][0]["topics"][1].lower() == "0x" + next_request["commitment"]
            assert next_request["commitment"] != request["commitment"]

            second_deployment = Account.sign_transaction({
                "type": 2, "chainId": 31337, "nonce": 5, "gas": 2_000_000,
                "maxFeePerGas": 2_000_000_000, "maxPriorityFeePerGas": 1_000_000_000,
                "value": 0, "data": bytecode,
            }, signer.key)
            second_deploy_hash = _rpc(
                url, "eth_sendRawTransaction", ["0x" + second_deployment.raw_transaction.hex()],
            )
            second_address = _wait_receipt(url, second_deploy_hash)["contractAddress"]
            second_config = EVMNetworkConfig(
                chain="local", chain_id=31337, expected_genesis_hash=genesis_hash,
                rpc_url=url, contract_address=second_address,
                expected_code_hash=config.expected_code_hash,
                publisher_address=signer.address, confirmations=1, gas_limit=150_000,
                max_fee_per_gas_wei=2_000_000_000,
                max_priority_fee_per_gas_wei=1_000_000_000,
            )
            independent = outbox.enqueue_event(
                event.event_id, destination="evm-registry",
                chain=second_config.chain, network=second_config.network_id,
            )
            assert independent["commitment"] == request["commitment"]
            assert independent["network"] != request["network"]
            independent_adapter = EVMRegistryAdapter(
                second_config, signer=signer, nonce_coordinator=EVMNonceCoordinator(store),
                publication_id=independent["publication_id"],
            )
            assert PublicationDispatcher(outbox, [independent_adapter]).process(
                independent["publication_id"]
            )["status"] == "VERIFIED"
            independent_receipt = _wait_receipt(
                url, outbox.latest_attempt(independent["publication_id"])["transaction_id"],
            )
            assert independent_receipt["logs"][0]["topics"][1].lower() == "0x" + request["commitment"]

            recovery_event = store.append_animal_event(
                "local-animal", "WEIGHT_RECORDED", {"weight": 435}, 3,
            )
            recovery_request = outbox.enqueue_event(
                recovery_event.event_id, destination="evm-registry",
                chain=config.chain, network=config.network_id,
            )
            timeout_client = EVMJsonRpcClient(config)
            original_send = timeout_client.rpc

            def accept_then_timeout(method, params):
                answer = original_send(method, params)
                if method == "eth_sendRawTransaction":
                    raise TimeoutError("injected after-submit timeout")
                return answer

            timeout_client.rpc = accept_then_timeout
            recovery_adapter = EVMRegistryAdapter(
                config, client=timeout_client, signer=signer,
                nonce_coordinator=EVMNonceCoordinator(store),
                publication_id=recovery_request["publication_id"],
            )
            assert PublicationDispatcher(outbox, [recovery_adapter]).process(
                recovery_request["publication_id"]
            )["status"] == "UNKNOWN"
            recovery_attempt = outbox.latest_attempt(recovery_request["publication_id"])
            assert _wait_receipt(url, recovery_attempt["transaction_id"])["status"] == "0x1"
            store.close()
            store = Store(tmp_path / "riose.sqlite3")
            outbox = SQLitePublicationOutbox(store)
            resumed_adapter = EVMRegistryAdapter(config, publication_id=recovery_request["publication_id"])
            assert PublicationDispatcher(outbox, [resumed_adapter]).reconcile(
                recovery_request["publication_id"]
            )["status"] == "VERIFIED"
            assert outbox.latest_attempt(recovery_request["publication_id"])["attempt_id"] == recovery_attempt["attempt_id"]
            print(json.dumps({
                "runtime": "ganache", "contract_address": address,
                "deployment_gas": int(deploy_receipt["gasUsed"], 16),
                "publication_gas": int(receipt["gasUsed"], 16),
                "second_publication_gas": int(next_receipt["gasUsed"], 16),
                "duplicate_revert_gas": int(duplicate_receipt["gasUsed"], 16),
                "deployment_tx": deploy_hash, "publication_tx": attempt["transaction_id"],
            }))
        finally:
            store.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
