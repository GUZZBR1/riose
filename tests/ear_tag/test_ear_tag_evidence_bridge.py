from __future__ import annotations

from riose.evidence.bridge import EvidenceClass
from riose.products.ear_tag.digital_twin.evidence_bridge import bridge_spec_parameter


def test_datasheet_parameter_maps_to_declared_and_preserves_value_and_unit():
    parameter = {
        "value": 2400,
        "unit": "mAh",
        "source": "vendor/battery-datasheet.pdf#page=4",
        "status": "DATASHEET",
    }
    bridge = bridge_spec_parameter(parameter)
    assert bridge.source_status == "DATASHEET"
    assert bridge.evidence_class is EvidenceClass.DECLARED
    assert bridge.source_ref == parameter["source"]
    assert bridge.source_context == {"unit": "mAh", "value": 2400}
    assert parameter["status"] == "DATASHEET"


def test_assumption_maps_to_unknown_until_explicit_inference_method_exists():
    parameter = {"value": 1.2, "unit": "mA", "source": "engineering-estimate", "status": "ASSUMED"}
    assert bridge_spec_parameter(parameter).evidence_class is EvidenceClass.UNKNOWN
    inferred = bridge_spec_parameter(parameter, inference_method="power-budget-v2")
    assert inferred.evidence_class is EvidenceClass.INFERRED
    assert inferred.source_status == "ASSUMED"


def test_simulated_spec_stays_simulated_and_measured_needs_physical_provenance():
    parameter = {"value": 0.8, "unit": "ratio", "source": "synthetic-run", "status": "SIMULATED"}
    bridge = bridge_spec_parameter(parameter)
    assert bridge.evidence_class is EvidenceClass.SIMULATED
    measured = dict(parameter, status="MEASURED")
    assert bridge_spec_parameter(measured).evidence_class is EvidenceClass.UNKNOWN
