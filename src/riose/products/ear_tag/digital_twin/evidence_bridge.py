"""Adapter from digital-twin specification entries to shared evidence."""

from __future__ import annotations

from collections.abc import Mapping

from riose.evidence.bridge import EvidenceBridgeRecord, map_source_evidence


def bridge_spec_parameter(
    parameter: Mapping[str, object],
    *,
    inference_method: str | None = None,
) -> EvidenceBridgeRecord:
    """Adapt a spec entry while retaining its declared value/unit/source."""

    if not isinstance(parameter, Mapping):
        raise ValueError("parameter must be a mapping")
    status = parameter.get("status")
    source = parameter.get("source")
    if type(status) is not str:
        raise ValueError("parameter status must be a raw string")
    if source is not None and type(source) is not str:
        raise ValueError("parameter source must be a string")
    source_context = {
        key: value
        for key, value in parameter.items()
        if key not in {"status", "source"}
    }
    return map_source_evidence(
        status,
        source_ref=source,
        inference_method=inference_method,
        source_context=source_context,
    )
