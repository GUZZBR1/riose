"""Minimal immutable evidence record for a public commitment publication."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum

from .contracts import EvidenceStatus

_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z", re.ASCII)
_SCOPE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z", re.ASCII)


class ReceiptStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    """A chain-neutral observation; intentionally excludes animal/event data."""

    receipt_id: str
    version: int
    commitment: str
    destination: str
    network: str
    status: ReceiptStatus
    evidence_status: EvidenceStatus
    source: str
    observed_at: float
    reference: str | None = None

    def __post_init__(self) -> None:
        for name, value in (("receipt_id", self.receipt_id), ("reference", self.reference)):
            if value is None and name == "reference":
                continue
            if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"{name} must be an opaque technical identifier")
        if type(self.commitment) is not str or _DIGEST.fullmatch(self.commitment) is None:
            raise ValueError("commitment must be a lowercase SHA-256 digest")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be a positive integer")
        for name, value in (("destination", self.destination), ("network", self.network)):
            if type(value) is not str or _SCOPE.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase technical identifier")
        if not isinstance(self.status, ReceiptStatus):
            raise ValueError("status must be a ReceiptStatus")
        if not isinstance(self.evidence_status, EvidenceStatus):
            raise ValueError("evidence_status must be an EvidenceStatus")
        if type(self.source) is not str or _SCOPE.fullmatch(self.source) is None:
            raise ValueError("source must be a lowercase technical identifier")
        if self.status is ReceiptStatus.CONFIRMED and self.reference is None:
            raise ValueError("confirmed receipts require a reference")
        if (
            isinstance(self.observed_at, bool)
            or not isinstance(self.observed_at, (int, float))
            or not math.isfinite(self.observed_at)
        ):
            raise ValueError("observed_at must be a finite timestamp")
