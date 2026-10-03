from __future__ import annotations

import pytest

from riose.evidence.bridge import EvidenceClass
from riose.products.livestock_tracking.adapters.evidence_bridge import (
    bridge_rf_record,
    bridge_rf_status,
)
from riose.products.livestock_tracking.domain.contracts import (
    Estimate,
    EvidenceStatus,
    RFObservation,
)


def test_rf_status_adapter_keeps_legacy_status_and_requires_explicit_method():
    ambiguous = bridge_rf_status(EvidenceStatus.ASSUMED, source_ref="filter:cfg-1")
    inferred = bridge_rf_status(
        EvidenceStatus.ASSUMED,
        source_ref="filter:cfg-1",
        inference_method="weighted-centroid-v1",
    )
    assert ambiguous.source_status == "ASSUMED"
    assert ambiguous.evidence_class is EvidenceClass.UNKNOWN
    assert inferred.source_status == "ASSUMED"
    assert inferred.evidence_class is EvidenceClass.INFERRED


def test_rf_observation_adapter_preserves_raw_source_context_without_changing_input():
    observation = RFObservation(
        timestamp_s=12.5,
        tag_id="tag-synthetic",
        anchor_id="anchor-synthetic",
        rssi_dbm=-71.0,
        snr_db=8.0,
        packet_received=True,
        status=EvidenceStatus.SIMULATED,
    )
    bridge = bridge_rf_record(observation, source_ref="episode:seed-7")
    assert bridge.evidence_class is EvidenceClass.SIMULATED
    assert bridge.source_context == {
        "anchor_id": "anchor-synthetic",
        "timestamp_s": 12.5,
        "tag_id": "tag-synthetic",
    }
    assert observation.status is EvidenceStatus.SIMULATED


def test_estimate_adapter_keeps_method_and_never_promotes_validated_status():
    estimate = Estimate(
        timestamp_s=1.0,
        tag_id="tag-synthetic",
        x=4.0,
        y=7.0,
        method="multilateration",
        status=EvidenceStatus.VALIDATED,
    )
    bridge = bridge_rf_record(estimate, source_ref="test:estimate-1")
    assert bridge.source_status == "VALIDATED"
    assert bridge.evidence_class is EvidenceClass.UNKNOWN
    assert bridge.source_context["method"] == "multilateration"


def test_rf_adapter_rejects_status_from_an_unrelated_enum():
    with pytest.raises(ValueError, match="EvidenceStatus"):
        bridge_rf_status("SIMULATED")
