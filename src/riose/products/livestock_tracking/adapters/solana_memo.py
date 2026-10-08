"""Explicit, opt-in Solana Memo publication using the Solders Python SDK."""

from __future__ import annotations

import base64
import json
import os
import re
import stat
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from math import isfinite
from urllib.parse import urlsplit

from ..domain.publication import ChainReceipt, PreparedPublication
from ..domain.privacy import PublicCommitmentEnvelope, serialize_public_envelope

MEMO_PROGRAM_ID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_HASH58 = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,64}\Z", re.ASCII)
_SIGNATURE58 = re.compile(r"[1-9A-HJ-NP-Za-km-z]{80,90}\Z", re.ASCII)
_ALLOWED_GENESIS = {
    "GH7ome3EiwEr7tu9JuTh2dpYWBJK3z69Xm1ZE3MEE6JC": "devnet",
    "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG": "devnet",
    "4uhcVJyU9pJkvQyS88uRDiswHXSCkY3zQawwpjk2NsNY": "testnet",
}


def _json_object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


class SolanaRpcError(RuntimeError):
    """Sanitized RPC/transport error; response bodies are never included."""


@dataclass(frozen=True, slots=True)
class SolanaMemoConfig:
    rpc_url: str
    expected_genesis_hash: str
    timeout_s: float = 10.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.rpc_url) if type(self.rpc_url) is str else None
        if parsed is None or parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Solana RPC URL must be an explicit HTTPS URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("RPC credentials must not be embedded in the URL")
        if type(self.expected_genesis_hash) is not str or _HASH58.fullmatch(self.expected_genesis_hash) is None:
            raise ValueError("expected_genesis_hash must be a base58 cluster genesis hash")
        if self.expected_genesis_hash not in _ALLOWED_GENESIS:
            raise ValueError("only allowlisted Solana devnet or testnet genesis hashes are supported")
        if isinstance(self.timeout_s, bool) or not isinstance(self.timeout_s, (int, float)) or not isfinite(self.timeout_s) or not 0.1 <= self.timeout_s <= 60:
            raise ValueError("timeout_s must be between 0.1 and 60 seconds")

    @property
    def network_id(self) -> str:
        return f"solana-{_ALLOWED_GENESIS[self.expected_genesis_hash]}-{self.expected_genesis_hash}"


class SolanaMemoClient:
    def __init__(self, config: SolanaMemoConfig) -> None:
        self.config = config
        self._next_id = 0

    @property
    def evidence_status(self) -> str:
        """A single JSON-RPC endpoint is assumed evidence, not independent proof."""
        return "ASSUMED"

    def rpc(self, method: str, params: list[object]) -> object:
        self._next_id += 1
        request_id = self._next_id
        payload = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}, separators=(",", ":")).encode()
        request = urllib.request.Request(self.config.rpc_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_s) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise SolanaRpcError("RPC transport unavailable") from exc
        if len(body) > MAX_RESPONSE_BYTES:
            raise SolanaRpcError("RPC response exceeded the size limit")
        try:
            data = json.loads(
                body,
                object_pairs_hook=_json_object_without_duplicate_keys,
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            raise SolanaRpcError("RPC response was invalid") from None
        if type(data) is not dict or data.get("jsonrpc") != "2.0" or data.get("id") != request_id or "error" in data or "result" not in data:
            raise SolanaRpcError("RPC request failed")
        return data["result"]

    def ensure_expected_cluster(self) -> None:
        if self.rpc("getGenesisHash", []) != self.config.expected_genesis_hash:
            raise SolanaRpcError("RPC cluster genesis hash did not match the configured network")

    def prepare(self, envelope: PublicCommitmentEnvelope, keypair: object) -> tuple[bytes, str, int]:
        """Build and sign locally; caller must persist returned bytes before sending."""
        try:
            from solders.hash import Hash
            from solders.instruction import Instruction
            from solders.message import MessageV0
            from solders.pubkey import Pubkey
            from solders.transaction import VersionedTransaction
        except ImportError as exc:
            raise SolanaRpcError("install the optional solana extra to use the Solana adapter") from exc
        self.ensure_expected_cluster()
        latest = self.rpc("getLatestBlockhash", [{"commitment": "confirmed"}])
        if type(latest) is not dict or type(latest.get("value")) is not dict:
            raise SolanaRpcError("RPC returned an invalid recent blockhash")
        value = latest["value"]
        try:
            blockhash = Hash.from_string(value["blockhash"])
            last_valid_height = value["lastValidBlockHeight"]
            if type(last_valid_height) is not int or last_valid_height < 0:
                raise ValueError
            memo_data = serialize_public_envelope(envelope)
            message = MessageV0.try_compile(
                keypair.pubkey(),
                [Instruction(Pubkey.from_string(MEMO_PROGRAM_ID), memo_data, [])],
                [],
                blockhash,
            )
            transaction = VersionedTransaction(message, [keypair])
        except Exception as exc:
            raise SolanaRpcError("could not build the signed Memo transaction") from None
        wire = bytes(transaction)
        if len(wire) > 1232:
            raise SolanaRpcError("signed transaction exceeds Solana packet size")
        signature = str(transaction.signatures[0])
        return wire, signature, last_valid_height

    def submit(self, signed_transaction: bytes, expected_signature: str) -> str:
        response = self.rpc("sendTransaction", [base64.b64encode(signed_transaction).decode("ascii"), {
            "encoding": "base64", "preflightCommitment": "confirmed", "maxRetries": 0,
        }])
        if type(response) is not str or response != expected_signature:
            raise SolanaRpcError("RPC response did not match the persisted transaction signature")
        return response

    def current_block_height(self) -> int:
        """Read the cluster's current height before deciding whether saved wire is reusable."""
        result = self.rpc("getBlockHeight", [{"commitment": "confirmed"}])
        if type(result) is not int or result < 0:
            raise SolanaRpcError("RPC returned an invalid block height")
        return result

    def verify(self, signature: str, envelope: PublicCommitmentEnvelope) -> tuple[bool | None, int | None]:
        """Return None for absent, False for execution errors, True for an exact Memo."""
        if type(signature) is not str or _SIGNATURE58.fullmatch(signature) is None:
            raise ValueError("signature must be a valid Solana transaction signature")
        try:
            from solders.signature import Signature
            Signature.from_string(signature)
        except Exception as exc:
            raise ValueError("signature must be a valid Solana transaction signature") from exc
        self.ensure_expected_cluster()
        result = self.rpc("getTransaction", [signature, {
            "commitment": "confirmed", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 0,
        }])
        if result is None:
            return None, None
        if type(result) is not dict or type(result.get("slot")) is not int or result["slot"] < 0:
            raise SolanaRpcError("RPC returned an invalid transaction")
        meta = result.get("meta")
        tx = result.get("transaction")
        signatures = tx.get("signatures") if type(tx) is dict else None
        msg = tx.get("message") if type(tx) is dict else None
        instructions = msg.get("instructions") if type(msg) is dict else None
        if (type(signatures) is not list or not signatures or signatures[0] != signature
                or type(meta) is not dict or "err" not in meta or type(instructions) is not list
                or any(type(item) is not dict or type(item.get("programId")) is not str for item in instructions)):
            raise SolanaRpcError("RPC returned an invalid transaction")
        if meta["err"] is not None:
            return False, result["slot"]
        wanted = serialize_public_envelope(envelope)
        matched = False
        for instruction in instructions:
            if instruction["programId"] != MEMO_PROGRAM_ID:
                continue
            raw = instruction.get("data")
            if type(raw) is str:
                try:
                    matched = _b58decode(raw) == wanted
                except ValueError as exc:
                    raise SolanaRpcError("RPC returned invalid Memo data") from exc
                break
            parsed = instruction.get("parsed")
            if type(parsed) is str:
                matched = parsed.encode("utf-8") == wanted
                break
            raise SolanaRpcError("RPC returned invalid Memo data")
        if not matched:
            raise SolanaRpcError("RPC transaction did not match the persisted Memo")
        return True, result["slot"]


class SolanaMemoAdapter:
    """Thin chain-neutral publication boundary over the existing Memo client."""

    chain = "solana"
    adapter_id = "solana-memo"

    def __init__(self, client: SolanaMemoClient, signer: object) -> None:
        self.client = client
        self.signer = signer
        self.network = client.config.network_id

    def prepare(self, commitment: PublicCommitmentEnvelope) -> PreparedPublication:
        payload, signature, last_valid_height = self.client.prepare(commitment, self.signer)
        return PreparedPublication(
            transaction_id=signature,
            payload=payload,
            metadata={"last_valid_block_height": last_valid_height},
        )

    def validate_prepared(
        self, prepared: PreparedPublication, commitment: PublicCommitmentEnvelope
    ) -> None:
        """Reject persisted wire that differs from the signed, single-Memo request."""
        try:
            from solders.message import MessageV0
            from solders.pubkey import Pubkey
            from solders.transaction import VersionedTransaction
        except ImportError as exc:
            raise SolanaRpcError("install the optional solana extra to use the Solana adapter") from exc

        if not isinstance(prepared, PreparedPublication):
            raise ValueError("prepared Solana publication is invalid")
        if type(prepared.metadata) is not dict:
            raise ValueError("prepared Solana publication is missing its expiry metadata")
        height = prepared.metadata.get("last_valid_block_height")
        if type(height) is not int or height < 0:
            raise ValueError("prepared Solana publication is missing its expiry metadata")
        if type(prepared.payload) is not bytes or not 1 <= len(prepared.payload) <= 1232:
            raise ValueError("prepared Solana transaction payload is invalid")
        try:
            transaction = VersionedTransaction.from_bytes(prepared.payload)
            transaction.sanitize()
            transaction.verify_and_hash_message()
            message = transaction.message
            instructions = message.instructions
            instruction = instructions[0]
            valid = (
                bytes(transaction) == prepared.payload
                and isinstance(message, MessageV0)
                and len(transaction.signatures) == 1
                and str(transaction.signatures[0]) == prepared.transaction_id
                and message.header.num_required_signatures == 1
                and not message.address_table_lookups
                and len(instructions) == 1
                and not instruction.accounts
                and message.account_keys[instruction.program_id_index] == Pubkey.from_string(MEMO_PROGRAM_ID)
                and bytes(instruction.data) == serialize_public_envelope(commitment)
            )
        except Exception as exc:
            raise ValueError("prepared Solana transaction does not match its commitment") from exc
        if not valid:
            raise ValueError("prepared Solana transaction does not match its commitment")

    def submit(self, prepared: PreparedPublication) -> str:
        height = prepared.metadata.get("last_valid_block_height")
        if type(height) is not int or height < 0:
            raise ValueError("prepared Solana publication is missing its expiry metadata")
        self.client.ensure_expected_cluster()
        return self.client.submit(prepared.payload, prepared.transaction_id)

    def can_replay(self, prepared: PreparedPublication) -> bool:
        """Only replay saved signed bytes while their recent blockhash remains valid."""
        height = prepared.metadata.get("last_valid_block_height")
        if type(height) is not int or height < 0:
            raise ValueError("prepared Solana publication is missing its expiry metadata")
        self.client.ensure_expected_cluster()
        return self.client.current_block_height() <= height

    def get_receipt(
        self, transaction_id: str, commitment: PublicCommitmentEnvelope
    ) -> ChainReceipt | None:
        matched, slot = self.client.verify(transaction_id, commitment)
        if matched is None:
            return None
        return ChainReceipt(
            chain=self.chain,
            network=self.network,
            transaction_id=transaction_id,
            status="CONFIRMED" if matched else "REJECTED",
            block_ref=str(slot) if slot is not None else None,
            confirmed_at=time.time() if matched else None,
            error=None if matched else "TRANSACTION_OR_MEMO_MISMATCH",
            retry_metadata={"slot": slot} if slot is not None else {},
            evidence_status=self.client.evidence_status,
        )

    def verify(self, commitment: PublicCommitmentEnvelope, receipt: ChainReceipt) -> bool | None:
        if receipt.chain != self.chain or receipt.network != self.network:
            return False
        matched, slot = self.client.verify(receipt.transaction_id, commitment)
        if matched is None:
            return None
        return bool(matched and (receipt.block_ref is None or receipt.block_ref == (str(slot) if slot is not None else None)))

    def healthcheck(self) -> bool:
        try:
            self.client.ensure_expected_cluster()
        except SolanaRpcError:
            return False
        return True


def load_keypair(path: str):
    """Load a Solana CLI JSON keypair file without echoing or retaining its secret."""
    try:
        from solders.keypair import Keypair
    except ImportError as exc:
        raise SolanaRpcError("install the optional solana extra to use the Solana adapter") from exc
    try:
        return _read_keypair(path, Keypair)
    except Exception:
        # Raise after leaving the except block so the underlying exception (which
        # may retain secret input bytes) is not attached to the sanitized error.
        pass
    raise SolanaRpcError("keypair file is invalid or unreadable")


def _read_keypair(path: str, keypair_type: type):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    # Avoid blocking forever if an attacker supplies a FIFO or another special file.
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError
        if os.name == "posix":
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise ValueError
            if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
                raise ValueError
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(513)
    finally:
        os.close(descriptor)

    if not raw or len(raw) > 512:
        raise ValueError
    document = json.loads(raw.decode("utf-8", errors="strict"))
    if (type(document) is not list or len(document) != 64
            or any(type(byte) is not int or not 0 <= byte <= 255 for byte in document)):
        raise ValueError
    return keypair_type.from_bytes(bytes(document))


def _b58decode(value: str) -> bytes:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = 0
    for char in value:
        if char not in alphabet:
            raise ValueError("invalid base58 data")
        number = number * 58 + alphabet.index(char)
    decoded = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\0" * (len(value) - len(value.lstrip("1"))) + decoded
