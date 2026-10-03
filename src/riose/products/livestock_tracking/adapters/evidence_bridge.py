"""Adapter from livestock RF contracts to the shared evidence vocabulary."""

from __future__ import annotations

from collections.abc import Mapping

from riose.evidence.bridge import (
    EvidenceBridgeRecord,
    MeasurementProvenance,
    map_source_evidence,
)

from ..domain.contracts import EvidenceStatus, Estimate, RFObservation


def bridge_rf_status(
    status: EvidenceStatus,
    *,
    source_ref: str | None = None,
    inference_method: str | None = None,
    source_context: Mapping[str, object] | None = None,
) -> EvidenceBridgeRecord:
    """Map a legacy RF status without modifying the source enum or object."""

    if not isinstance(status, EvidenceStatus):
        raise ValueError("status must be an EvidenceStatus")
    return map_source_evidence(
        status.value,
        source_ref=source_ref,
        inference_method=inference_method,
        source_context=source_context,
    )


def bridge_rf_record(
    record: RFObservation | Estimate,
    *,
    source_ref: str | None = None,
    inference_method: str | None = None,
) -> EvidenceBridgeRecord:
    """Adapt a record at its boundary while retaining its raw source fields."""

    if type(record) is RFObservation:
        context: dict[str, object] = {
            "anchor_id": record.anchor_id,
            "timestamp_s": record.timestamp_s,
            "tag_id": record.tag_id,
        }
    elif type(record) is Estimate:
        context = {
            "method": record.method,
            "tag_id": record.tag_id,
            "timestamp_s": record.timestamp_s,
        }
    else:
        raise ValueError("record must be an RFObservation or Estimate")
    return bridge_rf_status(
        record.status,
        source_ref=source_ref,
        inference_method=inference_method,
        source_context=context,
    )
