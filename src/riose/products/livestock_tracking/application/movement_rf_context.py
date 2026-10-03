"""Experimental, offline alignment of independent movement and RF evidence."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from ..domain.contracts import Estimate, EvidenceStatus, RFObservation
from ..domain.movement_context import MovementObservation, MovementStatus


class ContextState(StrEnum):
    APPARENTLY_IMMOBILE = "APPARENTLY_IMMOBILE"
    MOVEMENT_OBSERVED = "MOVEMENT_OBSERVED"
    RF_OBSERVABILITY_LOST = "RF_OBSERVABILITY_LOST"
    MOVEMENT_OBSERVATION_MISSING = "MOVEMENT_OBSERVATION_MISSING"
    BOTH_SOURCES_MISSING = "BOTH_SOURCES_MISSING"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CLOCKS_INCOMPATIBLE = "CLOCKS_INCOMPATIBLE"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    INVALID_RF = "INVALID_RF"


class RFStatus(StrEnum):
    OBSERVED = "OBSERVED"
    LOW_QUALITY = "LOW_QUALITY"
    PACKET_LOSS = "PACKET_LOSS"
    NO_OBSERVATION = "NO_OBSERVATION"
    STALE = "STALE"
    INVALID = "INVALID"


class LocalizationStatus(StrEnum):
    USABLE = "USABLE"
    LOW_QUALITY = "LOW_QUALITY"
    MISSING = "MISSING"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class ContextResult:
    tag_id: str
    timestamp_s: float
    state: ContextState
    movement: MovementObservation | None
    rf_observations: tuple[RFObservation, ...]
    localization: Estimate | None
    movement_status: MovementStatus
    rf_status: RFStatus
    localization_status: LocalizationStatus
    movement_only: str
    rf_only: str
    combined: str
    movement_evidence_status: EvidenceStatus | None
    rf_evidence_status: EvidenceStatus | None
    derived_evidence_status: EvidenceStatus
    provenance: tuple[str, ...]
    temporal_delta_s: float | None
    alignment_tolerance_s: float


def assess_movement_rf_context(
    tag_id: str,
    timestamp_s: float,
    movement: MovementObservation | None,
    rf_observations: Sequence[RFObservation],
    localization: Estimate | None = None,
    *,
    alignment_tolerance_s: float = 5.0,
    rf_clock_id: str = "simulation",
    allowed_anchor_ids: frozenset[str] | None = None,
    immobility_activity_threshold: float = 0.1,
    minimum_rf_quality: float = 0.5,
    minimum_movement_quality: float = 0.5,
    minimum_localization_quality: float = 0.5,
) -> ContextResult:
    """Assess evidence for one tag/query time without turning position into behavior.

    Only exact tag identities and matching clock IDs are joined. RF packets are
    grouped by timestamp, then the nearest epoch must be inside the configurable
    tolerance. Samples outside the window are stale; no offset is guessed for
    incompatible clocks. Duplicate same-anchor/same-time packets are removed
    only when identical; conflicting duplicates invalidate that RF epoch.
    """
    if not tag_id or not tag_id.strip():
        raise ValueError("tag_id must be non-empty")
    if (isinstance(timestamp_s, bool) or not isinstance(timestamp_s, (int, float))
            or not isfinite(timestamp_s)):
        raise ValueError("timestamp_s must be finite")
    if not isfinite(alignment_tolerance_s) or alignment_tolerance_s < 0:
        raise ValueError("alignment_tolerance_s must be finite and non-negative")
    if not isfinite(immobility_activity_threshold) or immobility_activity_threshold < 0:
        raise ValueError("immobility_activity_threshold must be finite and non-negative")
    for name, value in (("minimum_rf_quality", minimum_rf_quality),
                        ("minimum_movement_quality", minimum_movement_quality),
                        ("minimum_localization_quality", minimum_localization_quality)):
        if not isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{name} must be between 0 and 1")

    if movement is not None and movement.tag_id != tag_id:
        return _result(tag_id, timestamp_s, ContextState.IDENTITY_MISMATCH,
                       movement, tuple(rf_observations), localization,
                       MovementStatus.INVALID, RFStatus.NO_OBSERVATION,
                       LocalizationStatus.MISSING, None, None, alignment_tolerance_s)
    if localization is not None and localization.tag_id != tag_id:
        return _result(tag_id, timestamp_s, ContextState.IDENTITY_MISMATCH,
                       movement, tuple(rf_observations), localization,
                       movement.status if movement else MovementStatus.MISSING,
                       RFStatus.NO_OBSERVATION,
                       LocalizationStatus.INVALID, None, None, alignment_tolerance_s)

    matching = [row for row in rf_observations if row.tag_id == tag_id]
    wrong_tag_rows = [row for row in rf_observations if row.tag_id != tag_id]
    if not matching and wrong_tag_rows:
        return _result(tag_id, timestamp_s, ContextState.IDENTITY_MISMATCH,
                       movement, tuple(wrong_tag_rows), localization,
                       movement.status if movement else MovementStatus.MISSING,
                       RFStatus.NO_OBSERVATION, LocalizationStatus.MISSING,
                       None, None, alignment_tolerance_s)

    if movement is not None and movement.clock_id != rf_clock_id and rf_observations:
        return _result(tag_id, timestamp_s, ContextState.CLOCKS_INCOMPATIBLE,
                       movement, tuple(rf_observations), localization,
                       movement.status, RFStatus.INVALID,
                       LocalizationStatus.MISSING, None, None, alignment_tolerance_s)

    movement_delta = abs(movement.timestamp_s - timestamp_s) if movement else None
    if movement is not None and movement_delta is not None and movement_delta > alignment_tolerance_s:
        movement_status = MovementStatus.STALE
    else:
        movement_status = movement.status if movement else MovementStatus.MISSING

    if allowed_anchor_ids is not None and any(row.anchor_id not in allowed_anchor_ids for row in matching):
        return _result(tag_id, timestamp_s, ContextState.INVALID_RF,
                       movement, tuple(matching), localization, movement_status, RFStatus.INVALID,
                       LocalizationStatus.MISSING, None, None, alignment_tolerance_s)

    epochs: dict[float, list[RFObservation]] = {}
    for row in matching:
        if (isinstance(row.timestamp_s, bool)
                or not isinstance(row.timestamp_s, (int, float))
                or not isfinite(row.timestamp_s)):
            return _result(tag_id, timestamp_s, ContextState.INVALID_RF,
                           movement, tuple(matching), localization, movement_status, RFStatus.INVALID,
                           LocalizationStatus.MISSING, None, None, alignment_tolerance_s)
        epochs.setdefault(float(row.timestamp_s), []).append(row)

    rf_rows: tuple[RFObservation, ...] = ()
    rf_delta: float | None = None
    rf_status = RFStatus.NO_OBSERVATION
    if epochs:
        nearest_time = min(epochs, key=lambda t: (abs(t - timestamp_s), t))
        rf_delta = abs(nearest_time - timestamp_s)
        deduped: dict[str, RFObservation] = {}
        for row in epochs[nearest_time]:
            previous = deduped.get(row.anchor_id)
            if previous is not None and previous != row:
                return _result(tag_id, timestamp_s, ContextState.INVALID_RF,
                               movement, tuple(epochs[nearest_time]), localization,
                               movement_status, RFStatus.INVALID,
                               LocalizationStatus.MISSING, movement_delta, rf_delta,
                               alignment_tolerance_s)
            deduped[row.anchor_id] = row
        rf_rows = tuple(deduped[key] for key in sorted(deduped))
        movement_rf_delta = (abs(movement.timestamp_s - nearest_time)
                             if movement is not None else 0.0)
        if rf_delta > alignment_tolerance_s or movement_rf_delta > alignment_tolerance_s:
            rf_status = RFStatus.STALE
        else:
            received = [row for row in rf_rows if row.packet_received and row.rssi_dbm is not None]
            quality = len(received) / len(rf_rows) if rf_rows else 0.0
            if not received:
                rf_status = RFStatus.PACKET_LOSS
            elif quality < minimum_rf_quality:
                rf_status = RFStatus.LOW_QUALITY
            else:
                rf_status = RFStatus.OBSERVED

    localization_status = _localization_status(localization, timestamp_s, tag_id,
                                                alignment_tolerance_s,
                                                minimum_localization_quality)
    movement_good = (movement is not None and movement_status is MovementStatus.OBSERVED
                     and movement_delta is not None and movement_delta <= alignment_tolerance_s
                     and movement.activity_level is not None
                     and (movement.quality is None or movement.quality >= minimum_movement_quality))
    rf_good = rf_status is RFStatus.OBSERVED
    if (not movement_good and not rf_good
            and movement_status in (MovementStatus.MISSING, MovementStatus.STALE)
            and rf_status in (RFStatus.NO_OBSERVATION, RFStatus.STALE)):
        state = ContextState.BOTH_SOURCES_MISSING
    elif (not movement_good and movement_status in (MovementStatus.MISSING, MovementStatus.STALE)
          and rf_good):
        state = ContextState.MOVEMENT_OBSERVATION_MISSING
    elif not movement_good:
        state = ContextState.INSUFFICIENT_EVIDENCE
    elif not rf_good:
        state = ContextState.RF_OBSERVABILITY_LOST
    elif movement.activity_level <= immobility_activity_threshold:
        state = ContextState.APPARENTLY_IMMOBILE
    else:
        state = ContextState.MOVEMENT_OBSERVED

    movement_only = _movement_baseline(movement, movement_good, immobility_activity_threshold)
    rf_only = "UNKNOWN_BEHAVIOR_RF_OBSERVABLE" if rf_good else "INSUFFICIENT_OBSERVABILITY"
    combined = state.value
    provenance = tuple(dict.fromkeys(
        ([movement.provenance] if movement is not None else [])
        + [f"rf:{row.anchor_id}:{row.status.value}" for row in rf_rows]
        + ([f"localization:{localization.method}:{localization.status.value}"]
           if localization is not None else [])
    ))
    return ContextResult(
        tag_id, timestamp_s, state, movement, rf_rows, localization,
        movement_status,
        rf_status, localization_status, movement_only, rf_only, combined,
        movement.evidence_status if movement is not None else None,
        _combine_evidence(row.status for row in rf_rows),
        _combine_evidence(([movement.evidence_status] if movement is not None else [])
                          + [row.status for row in rf_rows]
                          + ([localization.status] if localization is not None else [])),
        provenance, (abs(movement.timestamp_s - rf_rows[0].timestamp_s)
                     if movement is not None and rf_rows else
                     rf_delta if rf_delta is not None else movement_delta),
        alignment_tolerance_s,
    )


def _movement_baseline(movement: MovementObservation | None, usable: bool,
                       threshold: float) -> str:
    if not usable or movement is None:
        return "UNKNOWN"
    return "APPARENTLY_IMMOBILE" if movement.activity_level <= threshold else "MOVEMENT_OBSERVED"


def _localization_status(estimate: Estimate | None, timestamp_s: float, tag_id: str,
                         tolerance: float, quality_floor: float) -> LocalizationStatus:
    if estimate is None:
        return LocalizationStatus.MISSING
    if (estimate.tag_id != tag_id or isinstance(estimate.timestamp_s, bool)
            or not isinstance(estimate.timestamp_s, (int, float))
            or not isfinite(estimate.timestamp_s)
            or abs(estimate.timestamp_s - timestamp_s) > tolerance):
        return LocalizationStatus.INVALID
    if estimate.x is None or estimate.y is None or estimate.quality is None:
        return LocalizationStatus.LOW_QUALITY
    if not isfinite(estimate.x) or not isfinite(estimate.y) or not isfinite(estimate.quality):
        return LocalizationStatus.INVALID
    if not 0 <= estimate.quality <= 1:
        return LocalizationStatus.INVALID
    return LocalizationStatus.USABLE if estimate.quality >= quality_floor else LocalizationStatus.LOW_QUALITY


def _combine_evidence(statuses: Iterable[EvidenceStatus]) -> EvidenceStatus:
    values = tuple(statuses)
    if not values:
        return EvidenceStatus.FUTURE
    # Derived evidence can never outrank its least empirical input.
    for status in (EvidenceStatus.FUTURE, EvidenceStatus.SIMULATED,
                   EvidenceStatus.ASSUMED, EvidenceStatus.EXPERIMENTAL):
        if status in values:
            return status
    return EvidenceStatus.VALIDATED


def _result(tag_id: str, timestamp_s: float, state: ContextState,
            movement: MovementObservation | None, rf_rows: tuple[RFObservation, ...],
            localization: Estimate | None, movement_status: MovementStatus,
            rf_status: RFStatus, localization_status: LocalizationStatus,
            movement_delta: float | None, rf_delta: float | None,
            tolerance: float) -> ContextResult:
    provenance = tuple(dict.fromkeys(
        ([movement.provenance] if movement is not None else [])
        + [f"rf:{row.anchor_id}:{row.status.value}" for row in rf_rows]
        + ([f"localization:{localization.method}:{localization.status.value}"]
           if localization is not None else [])
    ))
    evidence = ([movement.evidence_status] if movement is not None else [])
    evidence.extend(row.status for row in rf_rows)
    evidence.extend([localization.status] if localization is not None else [])
    return ContextResult(
        tag_id, timestamp_s, state, movement, rf_rows, localization,
        movement_status, rf_status, localization_status,
        "UNKNOWN", "INSUFFICIENT_OBSERVABILITY",
        state.value, movement.evidence_status if movement else None,
        _combine_evidence(row.status for row in rf_rows),
        _combine_evidence(evidence), provenance,
        rf_delta if rf_delta is not None else movement_delta, tolerance,
    )
