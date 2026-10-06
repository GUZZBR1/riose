"""Explicit identity and timestamp boundary for simulator event attribution.

This contract keeps request, packet and sequence identities separate. It is
deliberately independent of any backend and must not be replaced by FIFO joins.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
import re


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,191}\Z", re.ASCII)


class RequestState(StrEnum):
    CREATED = "REQUEST_CREATED"
    SUPERSEDED = "REQUEST_SUPERSEDED"
    TRANSMITTED = "TRANSMITTED"
    RECEIVED = "RECEIVED"


@dataclass(frozen=True, slots=True)
class RequestTimeline:
    """Milestones for one explicit request; all times are seconds on one clock."""

    run_id: str
    request_id: str
    state: RequestState
    requested_at_s: float
    source_timestamp_s: float | None = None
    scheduled_at_s: float | None = None
    transmitted_at_s: float | None = None
    received_at_s: float | None = None
    packet_id: str | None = None
    sequence_id: str | None = None
    superseded_by_request_id: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        _identifier(self.request_id, "request_id")
        if not isinstance(self.state, RequestState):
            raise ValueError("state must be a RequestState")
        _time(self.requested_at_s, "requested_at_s", required=True)
        for name in ("source_timestamp_s", "scheduled_at_s", "transmitted_at_s", "received_at_s"):
            _time(getattr(self, name), name)
        for name in ("packet_id", "sequence_id", "superseded_by_request_id"):
            value = getattr(self, name)
            if value is not None:
                _identifier(value, name)
        if self.source_timestamp_s is not None and self.source_timestamp_s > self.requested_at_s:
            raise ValueError("source_timestamp_s cannot be after request creation")
        if self.scheduled_at_s is not None and self.scheduled_at_s < self.requested_at_s:
            raise ValueError("scheduled_at_s cannot be before request creation")
        if self.transmitted_at_s is not None and (
            self.scheduled_at_s is None or self.transmitted_at_s < self.scheduled_at_s
        ):
            raise ValueError("transmission requires an earlier schedule timestamp")
        if self.received_at_s is not None and (
            self.transmitted_at_s is None or self.received_at_s < self.transmitted_at_s
        ):
            raise ValueError("reception requires an earlier transmission timestamp")

        has_tx = self.transmitted_at_s is not None
        has_rx = self.received_at_s is not None
        if self.state in {RequestState.CREATED, RequestState.SUPERSEDED} and (has_tx or has_rx):
            raise ValueError("created or superseded request cannot have TX/RX timestamps")
        if self.state is RequestState.SUPERSEDED:
            if self.superseded_by_request_id is None:
                raise ValueError("superseded request must identify its replacement request")
            if self.superseded_by_request_id == self.request_id:
                raise ValueError("request cannot supersede itself")
        elif self.superseded_by_request_id is not None:
            raise ValueError("superseded_by_request_id is only valid for a superseded request")
        if self.state is RequestState.TRANSMITTED and (not has_tx or has_rx):
            raise ValueError("transmitted state requires TX and must not claim RX")
        if self.state is RequestState.RECEIVED and (not has_tx or not has_rx):
            raise ValueError("received state requires both TX and RX timestamps")
        if has_tx and self.packet_id is None:
            raise ValueError("transmitted request must carry packet_id")


def _identifier(value: object, name: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} must be a non-empty bounded identifier")


def _time(value: object, name: str, *, required: bool = False) -> None:
    if value is None and not required:
        return
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0):
        raise ValueError(f"{name} must be finite seconds >= 0")
