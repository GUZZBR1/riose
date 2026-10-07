"""Shared EVM registry adapter; all network/deployment choices are configuration."""

from __future__ import annotations

import json
import os
import re
import stat
import urllib.error
import urllib.request
from typing import Any

from ..domain.privacy import PublicCommitmentEnvelope, guard_public_envelope
from ..domain.publication import ChainReceipt, PreparedPublication
from .evm_config import EVMNetworkConfig


_HASH = re.compile(r"0x[0-9a-fA-F]{64}\Z", re.ASCII)
_HEX = re.compile(r"0x(?:[0-9a-fA-F]{2})*\Z", re.ASCII)
_TOKEN = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_MAX_RPC_RESPONSE = 2 * 1024 * 1024


class EVMRpcError(RuntimeError):
    """Sanitized RPC, contract, or evidence error."""


def _eth_account():
    try:
        from eth_account import Account
        from eth_account.typed_transactions import TypedTransaction
        from eth_utils import keccak, to_checksum_address
        from hexbytes import HexBytes
    except ImportError as exc:
        raise EVMRpcError("install the optional evm extra to use the EVM adapter") from exc
    return Account, TypedTransaction, keccak, to_checksum_address, HexBytes


def encode_registry_commitment(envelope: PublicCommitmentEnvelope) -> bytes:
    """Encode the existing SHA-256 commitment as bytes32, with no rehashing."""
    valid = guard_public_envelope({
        "version": envelope.version,
        "algorithm": envelope.algorithm,
        "commitment": envelope.commitment,
    })
    return bytes.fromhex(valid.commitment)


def _selector(signature: str) -> bytes:
    return _eth_account()[2](text=signature)[:4]


def _event_topic(signature: str) -> str:
    return "0x" + _eth_account()[2](text=signature).hex()


class EVMJsonRpcClient:
    def __init__(self, config: EVMNetworkConfig) -> None:
        self.config = config
        self._next_id = 0

    def rpc(self, method: str, params: list[object]) -> object:
        self._next_id += 1
        request_id = self._next_id
        wire = json.dumps({
            "jsonrpc": "2.0", "id": request_id, "method": method, "params": params,
        }, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.config.rpc_url, data=wire, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_s) as response:
                body = response.read(_MAX_RPC_RESPONSE + 1)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise EVMRpcError("EVM RPC transport unavailable") from exc
        if len(body) > _MAX_RPC_RESPONSE:
            raise EVMRpcError("EVM RPC response exceeded the size limit")
        try:
            def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
                result: dict[str, object] = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate JSON key")
                    result[key] = value
                return result

            def reject_constant(_value: str) -> object:
                raise ValueError("non-JSON constant")

            result = json.loads(
                body, object_pairs_hook=unique_pairs,
                parse_constant=reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
            raise EVMRpcError("EVM RPC response was invalid") from exc
        if (type(result) is not dict or result.get("jsonrpc") != "2.0"
                or result.get("id") != request_id or "error" in result
                or "result" not in result):
            raise EVMRpcError("EVM RPC request failed")
        return result["result"]

    def ensure_expected_deployment(self) -> None:
        chain_id = _quantity(self.rpc("eth_chainId", []), "chain ID")
        if chain_id != self.config.chain_id:
            raise EVMRpcError("EVM RPC chain ID did not match configuration")
        genesis = self.rpc("eth_getBlockByNumber", ["0x0", False])
        if (type(genesis) is not dict
                or str(genesis.get("hash", "")).lower() != self.config.expected_genesis_hash.lower()):
            raise EVMRpcError("EVM RPC genesis block did not match configuration")
        code = self.rpc("eth_getCode", [self.config.contract_address, "latest"])
        if type(code) is not str or _HEX.fullmatch(code) is None or code == "0x":
            raise EVMRpcError("EVM contract code was missing or malformed")
        code_hash = "0x" + _eth_account()[2](bytes.fromhex(code[2:])).hex()
        if code_hash.lower() != self.config.expected_code_hash.lower():
            raise EVMRpcError("EVM contract code did not match configuration")


class EVMRegistryAdapter:
    """One adapter for any explicitly configured EVM deployment."""

    adapter_id = "evm-registry"

    def __init__(
        self,
        config: EVMNetworkConfig,
        *,
        client: EVMJsonRpcClient | None = None,
        signer: object | None = None,
        nonce_coordinator: object | None = None,
        publication_id: str | None = None,
    ) -> None:
        self.config = config
        self.client = client or EVMJsonRpcClient(config)
        self.signer = signer
        self.nonce_coordinator = nonce_coordinator
        self.publication_id = publication_id
        self.chain = config.chain
        self.network = config.network_id
        if signer is not None and getattr(signer, "address", "").lower() != config.publisher_address.lower():
            raise ValueError("EVM signer does not match configured publisher")

    def healthcheck(self) -> bool:
        try:
            self.client.ensure_expected_deployment()
        except EVMRpcError:
            return False
        return True

    def prepare(self, commitment: PublicCommitmentEnvelope) -> PreparedPublication:
        if self.signer is None or self.nonce_coordinator is None or self.publication_id is None:
            raise ValueError("EVM signer and nonce coordination are required to prepare")
        Account, _, _, to_checksum_address, _ = _eth_account()
        self.client.ensure_expected_deployment()
        pending_nonce = _quantity(
            self.client.rpc("eth_getTransactionCount", [self.config.publisher_address, "pending"]),
            "pending nonce",
        )
        nonce, reservation_token = self.nonce_coordinator.reserve(
            self.publication_id, self.network, self.config.publisher_address, pending_nonce,
            nonce_scope=self.config.nonce_scope,
        )
        data = _selector("register(bytes32)") + encode_registry_commitment(commitment)
        transaction = {
            "type": 2,
            "chainId": self.config.chain_id,
            "nonce": nonce,
            "to": to_checksum_address(self.config.contract_address),
            "value": 0,
            "data": data,
            "gas": self.config.gas_limit,
            "maxFeePerGas": self.config.max_fee_per_gas_wei,
            "maxPriorityFeePerGas": self.config.max_priority_fee_per_gas_wei,
        }
        try:
            signed = Account.sign_transaction(transaction, self.signer.key)
        except Exception as exc:
            raise EVMRpcError("could not sign EVM registry transaction") from exc
        prepared = PreparedPublication(
            transaction_id="0x" + bytes(signed.hash).hex(),
            payload=bytes(signed.raw_transaction),
            metadata={
                "chain_id": self.config.chain_id,
                "contract_address": self.config.contract_address.lower(),
                "sender": self.config.publisher_address.lower(),
                "nonce": nonce,
                "nonce_reservation_token": reservation_token,
            },
        )
        self.validate_prepared(prepared, commitment)
        return prepared

    def validate_prepared(
        self, prepared: PreparedPublication, commitment: PublicCommitmentEnvelope
    ) -> None:
        Account, TypedTransaction, keccak, _, HexBytes = _eth_account()
        data = _selector("register(bytes32)") + encode_registry_commitment(commitment)
        if (not isinstance(prepared, PreparedPublication)
                or type(prepared.payload) is not bytes or not prepared.payload
                or len(prepared.payload) > 1_048_576
                or type(prepared.transaction_id) is not str
                or _HASH.fullmatch(prepared.transaction_id) is None
                or type(prepared.metadata) is not dict):
            raise ValueError("prepared EVM transaction is invalid")
        try:
            typed = TypedTransaction.from_bytes(HexBytes(prepared.payload))
            tx = typed.as_dict()
            recovered = Account.recover_transaction(prepared.payload)
            expected_hash = "0x" + keccak(prepared.payload).hex()
            metadata = prepared.metadata
            valid = (
                typed.encode() == prepared.payload
                and tx.get("type") == 2
                and tx.get("chainId") == self.config.chain_id
                and type(tx.get("nonce")) is int
                and tx["nonce"] >= 0
                and bytes(tx.get("to", b"")) == bytes.fromhex(self.config.contract_address[2:])
                and tx.get("value") == 0
                and bytes(tx.get("data", b"")) == data
                and not tx.get("accessList")
                and type(tx.get("gas")) is int
                and 21_000 <= tx["gas"] <= self.config.gas_limit
                and type(tx.get("maxFeePerGas")) is int
                and 1 <= tx["maxFeePerGas"] <= self.config.max_fee_per_gas_wei
                and type(tx.get("maxPriorityFeePerGas")) is int
                and 0 <= tx["maxPriorityFeePerGas"] <= tx["maxFeePerGas"]
                and recovered.lower() == self.config.publisher_address.lower()
                and expected_hash.lower() == prepared.transaction_id.lower()
                and metadata.get("chain_id") == tx["chainId"]
                and metadata.get("nonce") == tx["nonce"]
                and metadata.get("contract_address") == self.config.contract_address.lower()
                and metadata.get("sender") == self.config.publisher_address.lower()
                and type(metadata.get("nonce_reservation_token")) is str
                and _TOKEN.fullmatch(metadata["nonce_reservation_token"]) is not None
            )
        except Exception as exc:
            raise ValueError("prepared EVM transaction does not match its target") from exc
        if not valid:
            raise ValueError("prepared EVM transaction does not match its target")

    def submit(self, prepared: PreparedPublication) -> str:
        if (type(prepared.transaction_id) is not str or _HASH.fullmatch(prepared.transaction_id) is None
                or type(prepared.payload) is not bytes
                or "0x" + _eth_account()[2](prepared.payload).hex() != prepared.transaction_id.lower()):
            raise ValueError("prepared EVM transaction hash is invalid")
        self.client.ensure_expected_deployment()
        result = self.client.rpc("eth_sendRawTransaction", ["0x" + prepared.payload.hex()])
        if type(result) is not str or result.lower() != prepared.transaction_id.lower():
            raise EVMRpcError("EVM RPC returned a mismatched transaction hash")
        return prepared.transaction_id

    def get_receipt(
        self, transaction_id: str, commitment: PublicCommitmentEnvelope
    ) -> ChainReceipt | None:
        if type(transaction_id) is not str or _HASH.fullmatch(transaction_id) is None:
            raise ValueError("transaction_id must be a 32-byte EVM hash")
        self.client.ensure_expected_deployment()
        result = self.client.rpc("eth_getTransactionReceipt", [transaction_id])
        if result is None:
            return None
        if type(result) is not dict:
            raise EVMRpcError("EVM RPC returned an invalid receipt")
        block_number = _quantity(result.get("blockNumber"), "receipt block")
        latest = _quantity(self.client.rpc("eth_blockNumber", []), "latest block")
        if latest < block_number or latest - block_number + 1 < self.config.confirmations:
            return None
        block_hash = result.get("blockHash")
        status = _quantity(result.get("status"), "receipt status")
        tx_hash = result.get("transactionHash")
        if (type(block_hash) is not str or _HASH.fullmatch(block_hash) is None
                or type(tx_hash) is not str or tx_hash.lower() != transaction_id.lower()
                or status not in {0, 1}
                or str(result.get("to", "")).lower() != self.config.contract_address.lower()
                or str(result.get("from", "")).lower() != self.config.publisher_address.lower()):
            raise EVMRpcError("EVM receipt did not match the configured target")
        canonical_block = self.client.rpc("eth_getBlockByNumber", [hex(block_number), False])
        if (type(canonical_block) is not dict
                or str(canonical_block.get("hash", "")).lower() != block_hash.lower()):
            raise EVMRpcError("EVM receipt block is not canonical at the configured depth")
        block_timestamp = _quantity(canonical_block.get("timestamp"), "block timestamp")
        transaction = self.client.rpc("eth_getTransactionByHash", [transaction_id])
        expected_data = _selector("register(bytes32)") + encode_registry_commitment(commitment)
        if (type(transaction) is not dict
                or str(transaction.get("hash", "")).lower() != transaction_id.lower()
                or str(transaction.get("blockHash", "")).lower() != block_hash.lower()
                or _quantity(transaction.get("blockNumber"), "transaction block") != block_number
                or str(transaction.get("to", "")).lower() != self.config.contract_address.lower()
                or str(transaction.get("from", "")).lower() != self.config.publisher_address.lower()
                or str(transaction.get("input", "")).lower() != ("0x" + expected_data.hex())):
            raise EVMRpcError("EVM transaction did not match the commitment")
        if status == 1:
            self._require_registration_log(
                result.get("logs"), commitment, transaction_id, block_hash, block_number,
            )
        return ChainReceipt(
            chain=self.chain, network=self.network, transaction_id=transaction_id,
            status="CONFIRMED" if status == 1 else "REJECTED",
            block_ref=block_hash.lower(),
            confirmed_at=float(block_timestamp) if status == 1 else None,
            error=None if status == 1 else "TRANSACTION_REVERTED",
            retry_metadata={"slot": block_number},
            evidence_status="ASSUMED",
        )

    def _require_registration_log(
        self, logs: object, commitment: PublicCommitmentEnvelope, transaction_id: str,
        block_hash: str, block_number: int,
    ) -> None:
        if type(logs) is not list:
            raise EVMRpcError("EVM receipt logs are malformed")
        topic0 = _event_topic("CommitmentRegistered(bytes32,address)")
        topic1 = "0x" + encode_registry_commitment(commitment).hex()
        topic2 = "0x" + ("0" * 24) + self.config.publisher_address[2:].lower()
        matching = [
            item for item in logs
            if (type(item) is dict
                and str(item.get("address", "")).lower() == self.config.contract_address.lower()
                and str(item.get("transactionHash", "")).lower() == transaction_id.lower()
                and str(item.get("blockHash", "")).lower() == block_hash.lower()
                and item.get("removed") is not True
                and _quantity(item.get("blockNumber"), "log block") == block_number
                and type(item.get("topics")) is list
                and [str(topic).lower() for topic in item["topics"]] == [topic0, topic1, topic2]
                and item.get("data") == "0x")
        ]
        if len(matching) != 1:
            raise EVMRpcError("EVM receipt did not prove the registry commitment")

    def verify(self, commitment: PublicCommitmentEnvelope, receipt: ChainReceipt) -> bool | None:
        if (receipt.chain, receipt.network) != (self.chain, self.network):
            return False
        observed = self.get_receipt(receipt.transaction_id, commitment)
        if observed is None:
            return None
        return observed.status == "CONFIRMED" and observed.block_ref == receipt.block_ref


def load_evm_signer(path: str) -> object:
    """Read a local private key without placing it in logs or persistence."""
    Account, _, _, _, _ = _eth_account()
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            mode = os.fstat(descriptor).st_mode
            if not stat.S_ISREG(mode) or stat.S_IMODE(mode) & 0o077:
                raise ValueError
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(130).strip()
        finally:
            os.close(descriptor)
        if len(raw) not in {64, 66} or not re.fullmatch(rb"(?:0x)?[0-9a-fA-F]{64}", raw):
            raise ValueError
        return Account.from_key(raw.decode("ascii"))
    except (OSError, TypeError, ValueError) as exc:
        raise EVMRpcError("EVM signer file is invalid or unreadable") from exc


def _quantity(value: Any, label: str) -> int:
    if (type(value) is not str or not value.startswith("0x")
            or len(value) > 34 or not re.fullmatch(r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)", value)):
        raise EVMRpcError(f"EVM RPC returned an invalid {label}")
    return int(value, 16)
