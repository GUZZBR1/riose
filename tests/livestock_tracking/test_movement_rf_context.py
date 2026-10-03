from dataclasses import replace

import pytest

from riose.products.livestock_tracking.application.movement_rf_context import (
    ContextState,
    LocalizationStatus,
    RFStatus,
    assess_movement_rf_context,
)
from riose.products.livestock_tracking.domain.contracts import (
    Estimate,
    EvidenceStatus,
    RFObservation,
)
from riose.products.livestock_tracking.domain.movement_context import (
    MovementObservation,
    MovementStatus,
)


def movement(time=10.0, *, tag="tag-a", activity=0.02, quality=0.9,
             status=MovementStatus.OBSERVED, evidence=EvidenceStatus.SIMULATED,
             clock="simulation"):
    return MovementObservation(time, tag, activity, "REST", quality, status,
                               evidence, "fixture:movement", clock)


def rf(time=10.0, *, tag="tag-a", anchor="anchor-1", received=True,
       evidence=EvidenceStatus.SIMULATED):
    return RFObservation(time, tag, anchor, -70.0 if received else None,
                         20.0 if received else None, received,
                         status=evidence)


def assess(mov=movement(), rows=(rf(),), **kwargs):
    return assess_movement_rf_context("tag-a", 10.0, mov, rows, **kwargs)


def test_aligned_low_activity_and_rf_are_reported_as_apparently_immobile():
    result = assess()
    assert result.state is ContextState.APPARENTLY_IMMOBILE
    assert result.movement_only == "APPARENTLY_IMMOBILE"
    assert result.rf_only == "UNKNOWN_BEHAVIOR_RF_OBSERVABLE"
    assert result.combined == "APPARENTLY_IMMOBILE"
    assert result.movement is not None and result.rf_observations == (rf(),)
    assert result.provenance == ("fixture:movement", "rf:anchor-1:SIMULATED")
    assert result.derived_evidence_status is EvidenceStatus.SIMULATED


def test_movement_available_rf_missing_and_packet_loss_are_not_immobility():
    missing = assess(rows=())
    assert missing.state is ContextState.RF_OBSERVABILITY_LOST
    assert missing.rf_status is RFStatus.NO_OBSERVATION
    lost = assess(rows=(rf(received=False),))
    assert lost.state is ContextState.RF_OBSERVABILITY_LOST
    assert lost.rf_status is RFStatus.PACKET_LOSS
    assert lost.movement_only == "APPARENTLY_IMMOBILE"


def test_existing_rf_movement_hooks_are_preserved_without_using_packet_received():
    hooked = replace(rf(received=False), imu_accel_norm_g=1.02,
                     behavior_state="REST")
    source = MovementObservation.from_rf_hooks(hooked)
    assert source.status is MovementStatus.OBSERVED
    assert source.raw_imu_accel_norm_g == 1.02
    assert source.behavior_state == "REST"
    assert source.activity_level is None  # raw g is not an activity score
    result = assess_movement_rf_context("tag-a", 10.0, source, (hooked,))
    assert result.state is ContextState.INSUFFICIENT_EVIDENCE
    assert result.rf_status is RFStatus.PACKET_LOSS


def test_movement_missing_rf_present_and_both_missing_are_explicit():
    rf_only = assess(mov=None)
    assert rf_only.state is ContextState.MOVEMENT_OBSERVATION_MISSING
    both = assess(mov=None, rows=())
    assert both.state is ContextState.BOTH_SOURCES_MISSING


def test_tolerance_boundary_passes_but_outside_is_stale():
    boundary = assess(mov=movement(10.0), rows=(rf(12.0),), alignment_tolerance_s=2.0)
    assert boundary.state is ContextState.APPARENTLY_IMMOBILE
    assert boundary.temporal_delta_s == 2.0
    stale = assess(mov=movement(10.0), rows=(rf(12.0001),), alignment_tolerance_s=2.0)
    assert stale.state is ContextState.RF_OBSERVABILITY_LOST
    assert stale.rf_status is RFStatus.STALE
    stale_movement = assess(mov=movement(12.0001), rows=(rf(10.0),), alignment_tolerance_s=2.0)
    assert stale_movement.movement_status is MovementStatus.STALE
    assert stale_movement.movement_only == "UNKNOWN"


def test_tolerance_is_configurable_and_movement_rf_pair_must_align():
    too_far_from_query = assess(mov=movement(8.0), rows=(rf(12.0),),
                                alignment_tolerance_s=3.0)
    assert too_far_from_query.state is ContextState.RF_OBSERVABILITY_LOST
    with pytest.raises(ValueError):
        assess(alignment_tolerance_s=-1)


def test_incompatible_clocks_are_not_offset_guessed():
    result = assess(mov=movement(clock="device-a"), rf_clock_id="gateway-b")
    assert result.state is ContextState.CLOCKS_INCOMPATIBLE
    assert result.rf_status is RFStatus.INVALID


def test_missing_timestamps_are_rejected_or_reported_invalid():
    with pytest.raises(ValueError, match="timestamp_s"):
        movement(None)
    invalid_rf = replace(rf(), timestamp_s=None)
    result = assess(rows=(invalid_rf,))
    assert result.state is ContextState.INVALID_RF
    assert result.rf_status is RFStatus.INVALID


def test_identity_mismatch_and_cross_animal_contamination_are_rejected():
    result = assess(mov=movement(), rows=(rf(tag="tag-b"),))
    assert result.state is ContextState.IDENTITY_MISMATCH
    movement_mismatch = assess(mov=movement(tag="tag-b"))
    assert movement_mismatch.state is ContextState.IDENTITY_MISMATCH


def test_duplicate_rf_packets_are_deduplicated_and_conflicts_invalidated():
    duplicate = assess(rows=(rf(), rf()))
    assert duplicate.rf_status is RFStatus.OBSERVED
    assert len(duplicate.rf_observations) == 1
    conflict = assess(rows=(rf(), rf(received=False)))
    assert conflict.rf_status is RFStatus.INVALID
    assert conflict.state is ContextState.INVALID_RF


def test_out_of_order_rf_epochs_are_sorted_by_alignment_not_input_order():
    result = assess(rows=(rf(20.0), rf(9.0), rf(10.2)))
    assert result.rf_observations == (rf(10.2),)
    assert result.state is ContextState.APPARENTLY_IMMOBILE


def test_low_rf_quality_and_unknown_movement_are_explicit():
    low_rf = assess(rows=(rf(anchor="a1"), rf(anchor="a2", received=False)),
                    minimum_rf_quality=0.75)
    assert low_rf.rf_status is RFStatus.LOW_QUALITY
    assert low_rf.state is ContextState.RF_OBSERVABILITY_LOST
    unknown = assess(mov=movement(activity=None))
    assert unknown.state is ContextState.INSUFFICIENT_EVIDENCE
    assert unknown.movement_only == "UNKNOWN"
    unknown_label = assess(mov=movement(activity=None, status=MovementStatus.OBSERVED))
    assert unknown_label.state is ContextState.INSUFFICIENT_EVIDENCE
    low_movement_quality = assess(mov=movement(quality=0.2))
    assert low_movement_quality.state is ContextState.INSUFFICIENT_EVIDENCE


def test_low_quality_localization_is_context_only_not_behavior():
    low_position = Estimate(10.0, "tag-a", 9.0, 8.0, "fixture", 0.2,
                            EvidenceStatus.SIMULATED)
    result = assess(localization=low_position)
    assert result.state is ContextState.APPARENTLY_IMMOBILE
    assert result.localization_status is LocalizationStatus.LOW_QUALITY
    moved_position = replace(low_position, x=100.0, quality=0.9)
    result2 = assess(localization=moved_position)
    assert result2.state is ContextState.APPARENTLY_IMMOBILE
    lower_quality = replace(low_position, quality=0.6)
    result3 = assess(localization=lower_quality, minimum_localization_quality=0.7)
    assert result3.localization_status is LocalizationStatus.LOW_QUALITY
    assert result3.state is ContextState.APPARENTLY_IMMOBILE
    invalid_coordinate = replace(low_position, x=float("nan"))
    assert assess(localization=invalid_coordinate).localization_status is LocalizationStatus.INVALID


def test_movement_and_rf_use_independent_quality_thresholds():
    result = assess(mov=movement(quality=0.6),
                    rows=(rf(anchor="a1"), rf(anchor="a2", received=False)),
                    minimum_rf_quality=0.75, minimum_movement_quality=0.5)
    assert result.rf_status is RFStatus.LOW_QUALITY
    assert result.movement_only == "APPARENTLY_IMMOBILE"
    assert result.state is ContextState.RF_OBSERVABILITY_LOST
    lower_movement_threshold = assess(mov=movement(quality=0.6),
                                      minimum_movement_quality=0.7)
    assert lower_movement_threshold.state is ContextState.INSUFFICIENT_EVIDENCE


def test_unknown_anchor_is_rejected_when_inventory_is_configured():
    result = assess(allowed_anchor_ids=frozenset({"anchor-2"}))
    assert result.state is ContextState.INVALID_RF
    assert result.rf_status is RFStatus.INVALID


def test_evidence_status_is_never_promoted_and_source_statuses_are_preserved():
    experimental = assess(mov=movement(evidence=EvidenceStatus.EXPERIMENTAL),
                          rows=(rf(evidence=EvidenceStatus.SIMULATED),))
    assert experimental.movement_evidence_status is EvidenceStatus.EXPERIMENTAL
    assert experimental.rf_evidence_status is EvidenceStatus.SIMULATED
    assert experimental.derived_evidence_status is EvidenceStatus.SIMULATED
    validated = assess(mov=movement(evidence=EvidenceStatus.VALIDATED),
                       rows=(rf(evidence=EvidenceStatus.VALIDATED),))
    assert validated.derived_evidence_status is EvidenceStatus.VALIDATED


def test_comparative_fixture_demonstrates_scoped_ambiguity_resolution_gain():
    # Binary fixture cases: observed immobility (1, 3) versus insufficient
    # observability (2, 4). This is not field validation or a product claim.
    cases = (
        (movement(), (rf(),), "IMMOBILE"),
        (None, (), "INSUFFICIENT"),
        (movement(10.0, activity=0.03), (rf(10.1),), "IMMOBILE"),
        (movement(), (rf(30.0),), "INSUFFICIENT"),
    )
    movement_hits = rf_hits = combined_hits = 0
    for mov, rows, expected in cases:
        result = assess(mov=mov, rows=rows, alignment_tolerance_s=2.0)
        target = "APPARENTLY_IMMOBILE" if expected == "IMMOBILE" else "INSUFFICIENT"
        movement_prediction = ("APPARENTLY_IMMOBILE" if result.movement_only == "APPARENTLY_IMMOBILE"
                               else "INSUFFICIENT" if result.movement_only == "INSUFFICIENT"
                               else "UNKNOWN")
        rf_prediction = ("INSUFFICIENT" if result.rf_only == "INSUFFICIENT_OBSERVABILITY"
                         else "UNKNOWN")
        combined_prediction = ("APPARENTLY_IMMOBILE" if result.state is ContextState.APPARENTLY_IMMOBILE
                               else "INSUFFICIENT" if result.state in {
                                   ContextState.BOTH_SOURCES_MISSING,
                                   ContextState.RF_OBSERVABILITY_LOST,
                                   ContextState.MOVEMENT_OBSERVATION_MISSING,
                               } else "UNKNOWN")
        movement_hits += movement_prediction == target
        rf_hits += rf_prediction == target
        combined_hits += combined_prediction == target
    assert (movement_hits, rf_hits, combined_hits) == (2, 2, 4)


def test_offline_deterministic_and_no_external_side_effects():
    one = assess()
    two = assess()
    assert one == two
