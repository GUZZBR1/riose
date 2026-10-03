"""Opt-in Solana Memo adapter for public commitment envelopes.

No endpoint or cluster is selected implicitly. The adapter uses Solders for
transaction message construction and an injected JSON-RPC transport so tests
and local demos never need a live RPC endpoint.
"""

from __future__ import annotations

import json
import hashlib
import math
import re
from threading import Lock
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.parse import urlsplit

from ..domain.anchoring_signer import (
    AnchorSigningRequest,
    AnchoringPurpose,
    AnchoringSignerPort,
    SignatureVerifier,
    SigningStatus,
    sign_anchor_transaction,
)
from ..domain.contracts import EvidenceStatus
from ..domain.publication import (
    AdapterCapabilities,
    CommitmentPublicationRequest,
    ConfirmationResult,
    PublicationReason,
    PublicationStatus,
    SubmissionResult,
)
from ..domain.privacy import parse_public_envelope_json, serialize_public_envelope

MEMO_PROGRAM_ID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z", re.ASCII)
_SIGNATURE = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,128}\Z", re.ASCII)
_COMMITMENT_RANK = {"processed": 0, "confirmed": 1, "finalized": 2}
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
MAX_RPC_RESPONSE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SolanaMemoConfig:
    """Explicit RPC/cluster/signer configuration; no mainnet default exists."""

    rpc_url: str
    cluster: str
    payer_public_key: str
    expected_genesis_hash: str
    commitment: str = "confirmed"
    timeout_s: float = 10.0

    def __post_init__(self) -> None:
        if type(self.rpc_url) is not str:
            raise ValueError("rpc_url must be explicit")
        parsed = urlsplit(self.rpc_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("rpc_url must be an explicit HTTP(S) endpoint")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("RPC credentials must not be embedded in rpc_url")
        if type(self.cluster) is not str or _IDENTIFIER.fullmatch(self.cluster) is None:
            raise ValueError("cluster must be an explicit technical identifier")
        if type(self.payer_public_key) is not str or not self.payer_public_key:
            raise ValueError("payer_public_key must be explicit")
        if type(self.expected_genesis_hash) is not str or re.fullmatch(
            r"[1-9A-HJ-NP-Za-km-z]{32,64}", self.expected_genesis_hash, re.ASCII
        ) is None:
            raise ValueError("expected_genesis_hash must be an explicit base58 hash")
        if self.commitment not in {"processed", "confirmed", "finalized"}:
            raise ValueError("commitment must be processed, confirmed, or finalized")
        if (
            isinstance(self.timeout_s, bool)
            or not isinstance(self.timeout_s, (int, float))
            or not math.isfinite(self.timeout_s)
            or self.timeout_s <= 0
        ):
            raise ValueError("timeout_s must be a finite positive number")

    @property
    def network(self) -> str:
        identity = hashlib.sha256(self.expected_genesis_hash.encode("ascii")).hexdigest()[:48]
        return f"solana-genesis-{identity}"


class SolanaRpcPort(Protocol):
    """Small JSON-RPC seam, intentionally easy to replace with an offline fake."""

    def call(self, method: str, params: list[object]) -> object: ...

    @property
    def evidence_status(self) -> EvidenceStatus: ...


class HttpSolanaRpc:
    """Minimal JSON-RPC transport using the standard library and fixed timeout."""

    def __init__(self, url: str, *, timeout_s: float = 10.0) -> None:
        self._url = url
        self._timeout_s = timeout_s
        self._request_id = 0
        self._request_lock = Lock()

    @property
    def evidence_status(self) -> EvidenceStatus:
        # An RPC endpoint is an attesting source, not an independent light client.
        return EvidenceStatus.ASSUMED

    def call(self, method: str, params: list[object]) -> object:
        with self._request_lock:
            self._request_id += 1
            request_id = self._request_id
        body = json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            self._url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
            payload = response.read(MAX_RPC_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RPC_RESPONSE_BYTES:
            raise ValueError("RPC response exceeded the size limit")
        document = json.loads(payload)
        if (
            type(document) is not dict
            or document.get("jsonrpc") != "2.0"
            or document.get("id") != request_id
            or "error" in document
            or "result" not in document
        ):
            raise ValueError("RPC response was unavailable")
        return document["result"]


class SolanaMemoPublicationAdapter:
    """Publish only a guarded commitment as a Memo program instruction."""

    def __init__(
        self,
        config: SolanaMemoConfig,
        signer: AnchoringSignerPort,
        verifier: SignatureVerifier,
        rpc: SolanaRpcPort | None = None,
    ) -> None:
        self._config = config
        self._signer = signer
        self._verifier = verifier
        self._rpc = rpc or HttpSolanaRpc(config.rpc_url, timeout_s=config.timeout_s)

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            enabled=True,
            destinations=("solana-memo",),
            networks=(self._config.network,),
            query_supported=True,
            evidence_status=EvidenceStatus.FUTURE,
        )

    def submit(self, request: CommitmentPublicationRequest) -> SubmissionResult:
        if (
            request.destination != "solana-memo"
            or request.network != self._config.network
        ):
            return SubmissionResult(
                PublicationStatus.REJECTED,
                request.envelope.commitment,
                request.destination,
                request.network,
                reason=PublicationReason.INVALID_REQUEST,
                evidence_status=EvidenceStatus.FUTURE,
            )
        try:
            from solders.hash import Hash
            from solders.instruction import Instruction
            from solders.message import MessageV0
            from solders.pubkey import Pubkey
            from solders.signature import Signature
            from solders.transaction import VersionedTransaction

            memo = serialize_public_envelope(request.envelope)
            if not self._network_matches_config():
                return SubmissionResult(
                    PublicationStatus.REJECTED,
                    request.envelope.commitment,
                    request.destination,
                    request.network,
                    reason=PublicationReason.OBSERVATION_MISMATCH,
                    evidence_status=self._rpc.evidence_status,
                )
            blockhash_result = self._rpc.call(
                "getLatestBlockhash", [{"commitment": "confirmed"}]
            )
            blockhash_text = blockhash_result["value"]["blockhash"]
            payer = Pubkey.from_string(self._config.payer_public_key)
            message = MessageV0.try_compile(
                payer=payer,
                instructions=[
                    Instruction(Pubkey.from_string(MEMO_PROGRAM_ID), memo, [])
                ],
                address_lookup_table_accounts=[],
                recent_blockhash=Hash.from_string(blockhash_text),
            )
            signing_request = AnchorSigningRequest(
                message=bytes(message),
                network=self._config.network,
                expected_public_key=self._config.payer_public_key,
                purpose=AnchoringPurpose.TRANSACTION,
            )
            signing = sign_anchor_transaction(signing_request, self._signer, self._verifier)
            if signing.status is not SigningStatus.SIGNED or signing.signature is None:
                return SubmissionResult(
                    PublicationStatus.UNAVAILABLE,
                    request.envelope.commitment,
                    request.destination,
                    request.network,
                    reason=PublicationReason.SIGNER_UNAVAILABLE,
                    evidence_status=signing.evidence_status,
                )
            rpc_evidence = self._rpc.evidence_status
            if (
                rpc_evidence is not EvidenceStatus.SIMULATED
                and signing.evidence_status is not EvidenceStatus.VALIDATED
            ):
                return SubmissionResult(
                    PublicationStatus.UNAVAILABLE,
                    request.envelope.commitment,
                    request.destination,
                    request.network,
                    reason=PublicationReason.SIGNER_UNAVAILABLE,
                    evidence_status=signing.evidence_status,
                )
            transaction = VersionedTransaction.populate(
                message, [Signature.from_bytes(signing.signature)]
            )
            local_reference = str(transaction.signatures[0])
            response = self._rpc.call(
                "sendTransaction",
                [
                    _b64encode(bytes(transaction)),
                    {"encoding": "base64", "preflightCommitment": "confirmed"},
                ],
            )
            remote_reference = str(response)
            if remote_reference != local_reference:
                return SubmissionResult(
                    PublicationStatus.UNKNOWN,
                    request.envelope.commitment,
                    request.destination,
                    request.network,
                    reason=PublicationReason.OBSERVATION_MISMATCH,
                    evidence_status=rpc_evidence,
                )
            return SubmissionResult(
                PublicationStatus.SUBMITTED,
                request.envelope.commitment,
                request.destination,
                request.network,
                reference=remote_reference,
                evidence_status=rpc_evidence,
            )
        except Exception:
            return SubmissionResult(
                PublicationStatus.UNKNOWN,
                request.envelope.commitment,
                request.destination,
                request.network,
                reason=PublicationReason.UNKNOWN,
                evidence_status=EvidenceStatus.FUTURE,
            )

    def query(
        self, *, commitment: str, destination: str, network: str, reference: str
    ) -> ConfirmationResult:
        for name, value in (("destination", destination), ("network", network)):
            if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase technical identifier")
        if type(commitment) is not str or _DIGEST.fullmatch(commitment) is None:
            raise ValueError("commitment must be a lowercase SHA-256 digest")
        if type(reference) is not str or _SIGNATURE.fullmatch(reference) is None or not _valid_signature(reference):
            raise ValueError("reference must be a valid Solana transaction signature")
        if (
            destination != "solana-memo"
            or network != self._config.network
        ):
            return ConfirmationResult(
                PublicationStatus.REJECTED,
                commitment,
                destination,
                network,
                reference,
                reason=PublicationReason.INVALID_REQUEST,
                evidence_status=EvidenceStatus.FUTURE,
            )
        try:
            import base64
            from solders.signature import Signature
            from solders.transaction import VersionedTransaction

            if not self._network_matches_config():
                return ConfirmationResult(
                    PublicationStatus.UNAVAILABLE, commitment, destination, network, reference,
                    reason=PublicationReason.OBSERVATION_MISMATCH,
                    evidence_status=self._rpc.evidence_status,
                )

            tx = self._rpc.call(
                "getTransaction",
                [reference, {"encoding": "base64", "commitment": "processed",
                             "maxSupportedTransactionVersion": 0}],
            )
            if tx is None:
                return ConfirmationResult(
                    PublicationStatus.UNAVAILABLE, commitment, destination, network, reference,
                    reason=PublicationReason.NOT_FOUND, evidence_status=self._rpc.evidence_status,
                )
            memo_bytes, signature, payer, message_bytes = _extract_signed_memo(
                tx, base64.b64decode, VersionedTransaction
            )
            if (
                memo_bytes is None
                or signature != reference
                or payer is None
                or str(payer) != self._config.payer_public_key
                or not Signature.from_string(reference).verify(payer, message_bytes)
                or parse_public_envelope_json(memo_bytes).commitment != commitment
            ):
                return ConfirmationResult(
                    PublicationStatus.REJECTED, commitment, destination, network, reference,
                    reason=PublicationReason.OBSERVATION_MISMATCH,
                    evidence_status=self._rpc.evidence_status,
                )
            rpc_evidence = self._rpc.evidence_status
            meta = tx.get("meta")
            if type(meta) is not dict or "err" not in meta:
                return ConfirmationResult(
                    PublicationStatus.UNAVAILABLE, commitment, destination, network, reference,
                    reason=PublicationReason.UNKNOWN,
                    evidence_status=rpc_evidence,
                )
            if meta.get("err") is not None:
                return ConfirmationResult(
                    PublicationStatus.REJECTED, commitment, destination, network, reference,
                    reason=PublicationReason.DESTINATION_REJECTED,
                    evidence_status=rpc_evidence,
                )
            statuses = self._rpc.call(
                "getSignatureStatuses",
                [[reference], {"searchTransactionHistory": True}],
            )
            values = statuses.get("value") if type(statuses) is dict else None
            status = values[0] if type(values) is list and values else None
            if type(status) is dict and status.get("err") is not None:
                return ConfirmationResult(
                    PublicationStatus.REJECTED, commitment, destination, network, reference,
                    reason=PublicationReason.DESTINATION_REJECTED,
                    evidence_status=rpc_evidence,
                )
            if type(status) is not dict or "err" not in status or status.get("err") is not None:
                return ConfirmationResult(
                    PublicationStatus.UNAVAILABLE, commitment, destination, network, reference,
                    reason=PublicationReason.UNKNOWN,
                    evidence_status=rpc_evidence,
                )
            observed_level = status.get("confirmationStatus")
            if type(observed_level) is not str or observed_level not in _COMMITMENT_RANK:
                return ConfirmationResult(
                    PublicationStatus.UNAVAILABLE, commitment, destination, network, reference,
                    reason=PublicationReason.UNKNOWN,
                    evidence_status=rpc_evidence,
                )
            confirmed = (
                _COMMITMENT_RANK[observed_level] >= _COMMITMENT_RANK[self._config.commitment]
            )
            return ConfirmationResult(
                PublicationStatus.CONFIRMED if confirmed else PublicationStatus.SUBMITTED,
                commitment,
                destination,
                network,
                reference,
                evidence_status=rpc_evidence,
            )
        except Exception:
            return ConfirmationResult(
                PublicationStatus.UNAVAILABLE, commitment, destination, network, reference,
                reason=PublicationReason.DESTINATION_UNAVAILABLE,
                evidence_status=EvidenceStatus.FUTURE,
            )

    def _network_matches_config(self) -> bool:
        return self._rpc.call("getGenesisHash", []) == self._config.expected_genesis_hash


def _extract_signed_memo(tx: object, decode: Callable[..., bytes], parser: object):
    """Decode a base64 transaction and require exactly one Memo instruction."""
    if type(tx) is not dict:
        return None, None, None, None
    encoded = tx.get("transaction")
    if type(encoded) is not list or len(encoded) != 2 or encoded[1] != "base64":
        return None, None, None, None
    try:
        transaction = parser.from_bytes(decode(encoded[0], validate=True))
    except Exception:
        return None, None, None, None
    message = transaction.message
    keys = message.account_keys
    instructions = message.instructions
    if len(instructions) != 1 or not keys:
        return None, None, None, None
    instruction = instructions[0]
    index = instruction.program_id_index
    if not 0 <= index < len(keys) or str(keys[index]) != MEMO_PROGRAM_ID:
        return None, None, None, None
    return bytes(instruction.data), str(transaction.signatures[0]), keys[0], bytes(message)


def _valid_signature(reference: str) -> bool:
    try:
        from solders.signature import Signature

        return len(bytes(Signature.from_string(reference))) == 64
    except Exception:
        return False


def _b64encode(value: bytes) -> str:
    import base64

    return base64.b64encode(value).decode("ascii")
