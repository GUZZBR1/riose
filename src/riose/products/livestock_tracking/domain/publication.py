"""Chain-neutral publication values and the narrow adapter boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .privacy import PublicCommitmentEnvelope


@dataclass(frozen=True, slots=True)
class PreparedPublication:
    """Opaque adapter-prepared payload; the commitment is not rewritten."""

    transaction_id: str
    payload: bytes
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChainReceipt:
    """Normalized observation for one target-specific transaction."""

    chain: str
    network: str
    transaction_id: str
    status: str
    block_ref: str | None = None
    submitted_at: float | None = None
    confirmed_at: float | None = None
    error: str | None = None
    retry_metadata: dict[str, Any] = field(default_factory=dict)
    evidence_status: str = "UNKNOWN"


@runtime_checkable
class ChainAdapter(Protocol):
    """Minimal boundary for target-specific publication and observation.

    Implementations may encode the same public commitment differently for a
    chain, but must never replace or recompute its digest.
    """

    chain: str
    network: str

    def prepare(self, commitment: PublicCommitmentEnvelope) -> PreparedPublication: ...

    def submit(self, prepared: PreparedPublication) -> str: ...

    def get_receipt(
        self, transaction_id: str, commitment: PublicCommitmentEnvelope
    ) -> ChainReceipt | None: ...

    def verify(
        self, commitment: PublicCommitmentEnvelope, receipt: ChainReceipt
    ) -> bool | None: ...

    def healthcheck(self) -> bool: ...
