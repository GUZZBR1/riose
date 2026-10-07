"""Explicit deployment configuration shared by all EVM publication targets."""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from urllib.parse import urlsplit


_CHAIN = re.compile(r"[a-z][a-z0-9-]{0,31}\Z", re.ASCII)
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z", re.ASCII)
_HASH = re.compile(r"0x[0-9a-fA-F]{64}\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class EVMNetworkConfig:
    """One explicitly identified deployment; no public network is implicit."""

    chain: str
    chain_id: int
    expected_genesis_hash: str
    rpc_url: str
    contract_address: str
    expected_code_hash: str
    publisher_address: str
    confirmations: int
    gas_limit: int
    max_fee_per_gas_wei: int
    max_priority_fee_per_gas_wei: int
    explorer_tx_url: str | None = None
    timeout_s: float = 10.0

    def __post_init__(self) -> None:
        if type(self.chain) is not str or _CHAIN.fullmatch(self.chain) is None:
            raise ValueError("EVM chain must be a bounded technical identifier")
        if type(self.chain_id) is not int or not 1 <= self.chain_id < 2**64:
            raise ValueError("EVM chain_id must be a positive integer")
        if self.chain == "arbitrum-sepolia" and self.chain_id != 421614:
            raise ValueError("Arbitrum Sepolia chain_id must be 421614")
        if self.chain_id == 421614 and self.chain not in {"arbitrum", "arbitrum-sepolia"}:
            raise ValueError("chain ID 421614 must use an Arbitrum label")
        if type(self.expected_genesis_hash) is not str or _HASH.fullmatch(self.expected_genesis_hash) is None:
            raise ValueError("EVM expected_genesis_hash must be a 32-byte hex digest")
        if int(self.expected_genesis_hash, 16) == 0:
            raise ValueError("EVM expected_genesis_hash cannot be zero")
        if type(self.contract_address) is not str or _ADDRESS.fullmatch(self.contract_address) is None:
            raise ValueError("EVM contract_address must be a 20-byte hex address")
        if int(self.contract_address, 16) == 0:
            raise ValueError("EVM contract_address cannot be zero")
        if type(self.publisher_address) is not str or _ADDRESS.fullmatch(self.publisher_address) is None:
            raise ValueError("EVM publisher_address must be a 20-byte hex address")
        if int(self.publisher_address, 16) == 0:
            raise ValueError("EVM publisher_address cannot be zero")
        if type(self.expected_code_hash) is not str or _HASH.fullmatch(self.expected_code_hash) is None:
            raise ValueError("EVM expected_code_hash must be a 32-byte hex digest")
        if int(self.expected_code_hash, 16) == 0:
            raise ValueError("EVM expected_code_hash cannot be zero")
        parsed = urlsplit(self.rpc_url) if type(self.rpc_url) is str else None
        if parsed is None or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("EVM RPC URL is invalid")
        local_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if parsed.scheme != "https" and not local_http:
            raise ValueError("EVM RPC URL must be HTTPS or loopback HTTP")
        if (self.chain_id == 421614 and parsed.hostname
                and parsed.hostname.endswith("-sequencer.arbitrum.io")):
            raise ValueError("Arbitrum Sepolia requires a full RPC endpoint")
        if type(self.confirmations) is not int or not 1 <= self.confirmations <= 128:
            raise ValueError("EVM confirmations must be between 1 and 128")
        if type(self.gas_limit) is not int or not 21_000 <= self.gas_limit <= 1_000_000:
            raise ValueError("EVM gas_limit must be between 21000 and 1000000")
        if (type(self.max_fee_per_gas_wei) is not int
                or not 1 <= self.max_fee_per_gas_wei <= 10**12):
            raise ValueError("EVM max fee is invalid")
        if (type(self.max_priority_fee_per_gas_wei) is not int
                or not 0 <= self.max_priority_fee_per_gas_wei <= self.max_fee_per_gas_wei):
            raise ValueError("EVM priority fee is invalid")
        if (isinstance(self.timeout_s, bool) or not isinstance(self.timeout_s, (int, float))
                or not isfinite(self.timeout_s) or not 0.1 <= self.timeout_s <= 60):
            raise ValueError("EVM timeout_s must be between 0.1 and 60")
        if self.explorer_tx_url is not None:
            explorer = urlsplit(self.explorer_tx_url) if type(self.explorer_tx_url) is str else None
            if (explorer is None or explorer.scheme != "https" or not explorer.netloc
                    or explorer.username or explorer.password or explorer.fragment
                    or "{tx_hash}" not in self.explorer_tx_url):
                raise ValueError("EVM explorer_tx_url must be an HTTPS template")

    @property
    def network_id(self) -> str:
        identity = (f"{self.chain_id}:{self.expected_genesis_hash.lower()}:"
                    f"{self.contract_address.lower()}").encode("ascii")
        return f"evm-{self.chain}-{self.chain_id}-{hashlib.sha256(identity).hexdigest()}"

    @property
    def nonce_scope(self) -> str:
        """Nonce ownership is per EVM chain and sender, not per contract."""
        return f"evm-chain-{self.chain_id}-{self.expected_genesis_hash[2:].lower()}"

    @classmethod
    def from_json_file(cls, path: str | Path) -> EVMNetworkConfig:
        try:
            with open(path, "rb") as stream:
                raw = stream.read(8193)
            if len(raw) > 8192:
                raise ValueError

            def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
                result: dict[str, object] = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate EVM configuration key")
                    result[key] = value
                return result

            document = json.loads(raw, object_pairs_hook=unique_pairs)
            if type(document) is not dict:
                raise ValueError
            return cls(**document)
        except (OSError, TypeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("EVM network configuration is invalid or unreadable") from exc
