from pathlib import Path
import json

import pytest

from hardware.mechanical.model import SpecError, build_report, load_spec, main


ROOT = Path(__file__).parent


def test_fitting_assumed_spec_reports_mass_and_center_of_mass():
    report = build_report(load_spec(ROOT / "fixtures/fitting_spec.yaml"))
    assert report["fit"]["fits"] is True
    assert report["gate"] == "CONDITIONALLY_READY_PENDING_THRESHOLD_APPROVAL"
    assert report["mass_estimate_g"]["total"] > 0
    assert set(report["center_of_mass_mm"]) == {"x_mm", "y_mm", "z_mm"}
    assert report["mounting_hole"]["status"] == "ASSUMED"
    assert "MEASURED" not in report["specification_statuses"]


def test_real_candidate_reports_battery_fit_failure_without_rewriting_inputs():
    spec_path = ROOT.parent.parent / "spec.yaml"
    report = build_report(load_spec(spec_path))
    assert report["fit"]["fits"] is False
    assert any("battery" in issue for issue in report["fit"]["issues"])
    assert any("antenna keepout" in issue for issue in report["fit"]["issues"])
    assert {part["name"] for part in report["parts"]} >= {"antenna", "antenna_keepout"}
    assert report["envelope_mm"] == {"width": 38.0, "height": 68.0, "thickness": 15.0}
    assert report["mass_estimate_g"]["status"] == "ASSUMED"


def test_measured_dimension_is_rejected():
    spec = load_spec(ROOT / "fixtures/fitting_spec.yaml")
    spec["mechanical"]["enclosure"]["width_mm"]["status"] = "MEASURED"
    with pytest.raises(SpecError, match="MEASURED"):
        build_report(spec)


def test_missing_required_dimensions_are_not_silently_defaulted():
    with pytest.raises(SpecError, match="mechanical.enclosure.width_mm"):
        build_report({"mechanical": {}})


def test_cli_spec_is_explicitly_unavailable_when_absent():
    with pytest.raises(SpecError, match="Hardware spec not found"):
        load_spec(ROOT / "fixtures/not-a-spec.yaml")


def test_cli_success_means_analysis_completed_even_when_fit_is_blocked(tmp_path):
    spec_path = ROOT.parent.parent / "spec.yaml"
    output = tmp_path / "geometry.json"
    assert main(["--spec", str(spec_path), "--output", str(output)]) == 0
    result = json.loads(output.read_text())
    assert result["fit"]["fits"] is False
    assert result["gate"] == "NOT_READY_FOR_PHYSICAL_PROTOTYPE"
