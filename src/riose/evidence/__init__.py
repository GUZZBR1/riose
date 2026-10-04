"""Shared, product-neutral evidence contracts."""

from .bridge import (
    EVIDENCE_MAPPING_VERSION,
    EvidenceBridgeRecord,
    EvidenceClass,
    MeasurementProvenance,
    map_source_evidence,
    parse_evidence_bridge,
    serialize_evidence_bridge,
)

__all__ = [
    "EVIDENCE_MAPPING_VERSION",
    "EvidenceBridgeRecord",
    "EvidenceClass",
    "MeasurementProvenance",
    "map_source_evidence",
    "parse_evidence_bridge",
    "serialize_evidence_bridge",
]
