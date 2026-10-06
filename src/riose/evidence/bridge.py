"""Lossless mapping from product-local status vocabularies to evidence classes.

The bridge describes provenance; it does not verify sensors, scientific
validity, or software correctness. In particular, ``VALIDATED`` alone never
means ``MEASURED``.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

EVIDENCE_MAPPING_VERSION = 1
MAX_EVIDENCE_CONTEXT_BYTES = 4096
MAX_EVIDENCE_BRIDGE_BYTES = 8192
_STATUS = re.compile(r"[^\x00-\x1f\x7f]{1,64}\Z")
_PLACEHOLDER_REFERENCES = frozenset({"assumed", "n/a", "none", "placeholder", "unknown"})


class EvidenceClass(StrEnum):
    DECLARED = "DECLARED"
    MEASURED = "MEASURED"
    INFERRED = "INFERRED"
    SIMULATED = "SIMULATED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class MeasurementProvenance:
    """References needed to audit a physical capture outside this bridge."""

    physical_source_ref: str
    capture_ref: str
    provenance_ref: str

    def __post_init__(self) -> None:
        for name, value in (
            ("physical_source_ref", self.physical_source_ref),
            ("capture_ref", self.capture_ref),
            ("provenance_ref", self.provenance_ref),
        ):
            _validate_reference(value, name)


@dataclass(frozen=True, slots=True)
class EvidenceBridgeRecord:
    """Immutable, local record that preserves the source status and context."""

    source_status: str
    evidence_class: EvidenceClass
    source_ref: str | None = None
    mapping_version: int = EVIDENCE_MAPPING_VERSION
    inference_method: str | None = None
    measurement_provenance: MeasurementProvenance | None = None
    source_context_json: bytes = b"{}"

    def __post_init__(self) -> None:
        _validate_source_status(self.source_status)
        if type(self.mapping_version) is not int or self.mapping_version != EVIDENCE_MAPPING_VERSION:
            raise ValueError("unsupported evidence mapping version")
        if not isinstance(self.evidence_class, EvidenceClass):
            raise ValueError("evidence_class must be an EvidenceClass")
        if self.source_ref is not None:
            _validate_reference(self.source_ref, "source_ref")
        if self.inference_method is not None:
            _validate_reference(self.inference_method, "inference_method")
        if self.measurement_provenance is not None and type(self.measurement_provenance) is not MeasurementProvenance:
            raise ValueError("measurement_provenance must be a MeasurementProvenance")
        context = _parse_context(self.source_context_json)
        expected = _classify(
            self.source_status,
            self.source_ref,
            self.inference_method,
            self.measurement_provenance,
        )
        if self.evidence_class is not expected:
            raise ValueError("evidence class does not match the source mapping rules")
        # Validate canonical bytes, not just JSON parseability.
        if _encode_context(context) != self.source_context_json:
            raise ValueError("source context must use deterministic JSON encoding")

    @property
    def source_context(self) -> dict[str, object]:
        """Return a decoded copy of the original JSON-compatible source context."""

        return json.loads(self.source_context_json)


def map_source_evidence(
    source_status: str,
    *,
    source_ref: str | None = None,
    inference_method: str | None = None,
    measurement_provenance: MeasurementProvenance | None = None,
    source_context: Mapping[str, object] | None = None,
) -> EvidenceBridgeRecord:
    """Map one exact source status; ambiguous and unknown values stay UNKNOWN."""

    _validate_source_status(source_status)
    if source_ref is not None:
        _validate_reference(source_ref, "source_ref")
    if inference_method is not None:
        _validate_reference(inference_method, "inference_method")
    if measurement_provenance is not None and type(measurement_provenance) is not MeasurementProvenance:
        raise ValueError("measurement_provenance must be a MeasurementProvenance")
    if source_context is None:
        context = _encode_context({})
    elif isinstance(source_context, Mapping):
        context = _encode_context(dict(source_context))
    else:
        raise ValueError("source_context must be a mapping")
    return EvidenceBridgeRecord(
        source_status=source_status,
        evidence_class=_classify(
            source_status, source_ref, inference_method, measurement_provenance
        ),
        source_ref=source_ref,
        mapping_version=EVIDENCE_MAPPING_VERSION,
        inference_method=inference_method,
        measurement_provenance=measurement_provenance,
        source_context_json=context,
    )


def serialize_evidence_bridge(record: EvidenceBridgeRecord) -> bytes:
    if type(record) is not EvidenceBridgeRecord:
        raise ValueError("record must be an EvidenceBridgeRecord")
    provenance = record.measurement_provenance
    document = {
        "evidence_class": record.evidence_class.value,
        "inference_method": record.inference_method,
        "mapping_version": record.mapping_version,
        "measurement_provenance": (
            {
                "capture_ref": provenance.capture_ref,
                "physical_source_ref": provenance.physical_source_ref,
                "provenance_ref": provenance.provenance_ref,
            }
            if provenance is not None
            else None
        ),
        "source_context": record.source_context,
        "source_ref": record.source_ref,
        "source_status": record.source_status,
    }
    encoded = json.dumps(
        document,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > MAX_EVIDENCE_BRIDGE_BYTES:
        raise ValueError("evidence bridge record exceeds the size limit")
    return encoded


def parse_evidence_bridge(document: str | bytes) -> EvidenceBridgeRecord:
    if type(document) is bytes:
        if len(document) > MAX_EVIDENCE_BRIDGE_BYTES:
            raise ValueError("evidence bridge record exceeds the size limit")
        text = document.decode("utf-8", errors="strict")
    elif type(document) is str:
        text = document
        if len(text.encode("utf-8", errors="strict")) > MAX_EVIDENCE_BRIDGE_BYTES:
            raise ValueError("evidence bridge record exceeds the size limit")
    else:
        raise ValueError("evidence bridge input must be JSON text or bytes")
    try:
        value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("evidence bridge input is not valid JSON") from exc
    required = {
        "evidence_class",
        "inference_method",
        "mapping_version",
        "measurement_provenance",
        "source_context",
        "source_ref",
        "source_status",
    }
    if type(value) is not dict or frozenset(value) != required:
        raise ValueError("evidence bridge fields are unsupported or incomplete")
    provenance_value = value["measurement_provenance"]
    provenance = None
    if provenance_value is not None:
        provenance_fields = {"capture_ref", "physical_source_ref", "provenance_ref"}
        if type(provenance_value) is not dict or frozenset(provenance_value) != provenance_fields:
            raise ValueError("measurement provenance fields are unsupported or incomplete")
        provenance = MeasurementProvenance(**provenance_value)
    context_json = _encode_context(value["source_context"])
    record = EvidenceBridgeRecord(
        source_status=value["source_status"],
        evidence_class=EvidenceClass(value["evidence_class"]),
        source_ref=value["source_ref"],
        mapping_version=value["mapping_version"],
        inference_method=value["inference_method"],
        measurement_provenance=provenance,
        source_context_json=context_json,
    )
    if serialize_evidence_bridge(record) != text.encode("utf-8"):
        raise ValueError("evidence bridge JSON must use deterministic encoding")
    return record


def _classify(
    status: str,
    source_ref: str | None,
    inference_method: str | None,
    provenance: MeasurementProvenance | None,
) -> EvidenceClass:
    if status == "SIMULATED":
        return EvidenceClass.SIMULATED
    if status == "ASSUMED":
        return EvidenceClass.INFERRED if inference_method is not None else EvidenceClass.UNKNOWN
    if status == "DATASHEET":
        return EvidenceClass.DECLARED if source_ref is not None else EvidenceClass.UNKNOWN
    if status in {"MEASURED", "VALIDATED"}:
        if (
            provenance is not None
            and source_ref is not None
            and source_ref == provenance.provenance_ref
        ):
            return EvidenceClass.MEASURED
    return EvidenceClass.UNKNOWN


def _encode_context(context: object) -> bytes:
    if type(context) is not dict:
        raise ValueError("source_context must be a JSON object")
    _validate_json_value(context)
    encoded = json.dumps(
        context,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > MAX_EVIDENCE_CONTEXT_BYTES:
        raise ValueError("source context exceeds the size limit")
    return encoded


def _parse_context(encoded: bytes) -> dict[str, object]:
    if type(encoded) is not bytes or len(encoded) > MAX_EVIDENCE_CONTEXT_BYTES:
        raise ValueError("source_context_json must be bounded bytes")
    try:
        context = json.loads(
            encoded.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("source_context_json must contain a JSON object") from exc
    if type(context) is not dict:
        raise ValueError("source_context_json must contain a JSON object")
    _validate_json_value(context)
    return context


def _validate_json_value(value: object) -> None:
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("source context numbers must be finite")
        return
    if type(value) is list:
        for item in value:
            _validate_json_value(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("source context keys must be strings")
            _validate_json_value(item)
        return
    raise ValueError("source context must contain only JSON-compatible values")


def _validate_source_status(status: str) -> None:
    if type(status) is not str or _STATUS.fullmatch(status) is None:
        raise ValueError("source_status must be a bounded raw status string")


def _validate_reference(value: str, name: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or value.strip().casefold() in _PLACEHOLDER_REFERENCES
        or len(value) > 512
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError(f"{name} must be a bounded, non-empty source reference")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("evidence bridge JSON has duplicate keys")
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise ValueError("evidence bridge JSON contains a non-JSON number")
