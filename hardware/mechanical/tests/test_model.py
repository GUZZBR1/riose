from pathlib import Path
import json
import os
import struct

import pytest

from hardware.mechanical.model import SpecError, apply_overrides, build_report, export_cad, load_spec, main


ROOT = Path(__file__).parent


def test_fitting_assumed_spec_reports_mass_and_center_of_mass():
    report = build_report(load_spec(ROOT / "fixtures/fitting_spec.yaml"))
    assert report["fit"]["fits"] is True
    assert report["gate"] == "CONDITIONALLY_READY_PENDING_THRESHOLD_APPROVAL"
    assert report["mass_estimate_g"]["total"] > 0
    assert set(report["mass_by_material_class_g"]) == {"enclosure", "pcb", "battery", "components"}
    assert set(report["center_of_mass_mm"]) == {"x_mm", "y_mm", "z_mm"}
    assert min(report["enclosure_wall_clearances_mm"]["pcb"].values()) >= 0.5
    assert report["clearances_mm"]["mcu/radio"] == pytest.approx(0.5)
    assert report["mounting_hole"]["status"] == "ASSUMED"
    assert "MEASURED" not in report["specification_statuses"]
    assert not any(len(warning) == 1 for warning in report["warnings"])


def test_missing_material_density_is_reported_as_assumed_fallback():
    spec = load_spec(ROOT / "fixtures/fitting_spec.yaml")
    del spec["materials"]["pcb_density_g_cm3"]
    report = build_report(spec)
    assert "pcb density uses an ASSUMED fallback" in report["warnings"]
    assert not any(len(warning) == 1 for warning in report["warnings"])


def test_real_candidate_reports_battery_fit_failure_without_rewriting_inputs():
    spec_path = ROOT.parent.parent / "spec.yaml"
    report = build_report(load_spec(spec_path))
    assert report["fit"]["fits"] is False
    assert any("battery" in issue for issue in report["fit"]["issues"])
    assert not any("antenna keepout" in issue for issue in report["fit"]["issues"])
    assert {part["name"] for part in report["parts"]} >= {"antenna", "antenna_keepout"}
    assert report["envelope_mm"] == {"width": 38.0, "height": 68.0, "thickness": 15.0}
    assert report["mass_estimate_g"]["status"] == "ASSUMED"


def test_pcb_packing_keeps_keepout_inside_cavity_without_hiding_candidate_conflicts():
    report = build_report(load_spec(ROOT.parent.parent / "spec.yaml"))
    issues = report["fit"]["issues"]
    parts = {part["name"]: part for part in report["parts"]}

    # The spec provides no board origin. The left-packing heuristic must leave
    # enough cavity margin for the 32 mm keepout in the 35.6 mm cavity.
    assert parts["pcb"]["x"] == pytest.approx(-1.3)
    assert "antenna_keepout envelope exceeds enclosure cavity" not in issues
    assert parts["antenna_keepout"]["bounds_mm"]["x"] == pytest.approx([-17.3, 14.7])

    # Keepout may extend off the PCB into empty cavity; the antenna conductor
    # itself must fit the board, while the battery does not intersect it here.
    assert parts["antenna"]["bounds_mm"]["x"] == pytest.approx([-15.3, 12.7])
    assert not any("battery envelope violates antenna keepout" in issue for issue in issues)
    assert not any("keepout exceeds PCB envelope" in issue for issue in issues)

    # The remaining fit blockers come from the provisional package dimensions.
    assert "battery envelope exceeds enclosure cavity" in issues
    assert "unexpected envelope overlap: pcb / battery" in issues
    assert report["gate"] == "NOT_READY_FOR_PHYSICAL_PROTOTYPE"


def test_antenna_keepout_clash_with_battery_fails():
    spec = load_spec(ROOT.parent.parent / "spec.yaml")
    report = build_report(apply_overrides(spec, ["mechanical.antenna.keepout_mm=4"]))
    assert "battery envelope violates antenna keepout" in report["fit"]["issues"]


def test_measured_dimension_is_rejected():
    spec = load_spec(ROOT / "fixtures/fitting_spec.yaml")
    spec["mechanical"]["enclosure"]["width_mm"]["status"] = "MEASURED"
    with pytest.raises(SpecError, match="MEASURED"):
        build_report(spec)


def test_missing_required_dimensions_are_not_silently_defaulted():
    with pytest.raises(SpecError, match="mechanical.enclosure.width_mm"):
        build_report({"mechanical": {}})


def test_blank_parameter_provenance_is_rejected():
    spec = load_spec(ROOT / "fixtures/fitting_spec.yaml")
    spec["mechanical"]["pcb"]["width_mm"]["source"] = None
    with pytest.raises(SpecError, match="provenance"):
        build_report(spec)


def test_cli_spec_is_explicitly_unavailable_when_absent():
    with pytest.raises(SpecError, match="Hardware spec not found"):
        load_spec(ROOT / "fixtures/not-a-spec.yaml")


def test_cli_fails_when_spec_geometry_has_fit_blockers(tmp_path):
    spec_path = ROOT.parent.parent / "spec.yaml"
    output = tmp_path / "geometry.json"
    assert main(["--spec", str(spec_path), "--output", str(output)]) == 1
    result = json.loads(output.read_text())
    assert result["fit"]["fits"] is False
    assert result["gate"] == "NOT_READY_FOR_PHYSICAL_PROTOTYPE"


def test_clearance_parameter_changes_report_and_is_simulated():
    spec = load_spec(ROOT / "fixtures/fitting_spec.yaml")
    baseline = build_report(spec)
    changed = build_report(apply_overrides(spec, ["mechanical.minimum_clearance_mm=1.25"]))
    assert changed != baseline
    assert changed["input_parameters"]["mechanical.minimum_clearance_mm"]["value"] == 1.25
    assert changed["input_parameters"]["mechanical.minimum_clearance_mm"]["status"] == "SIMULATED"
    assert changed["clearances_mm"] != baseline["clearances_mm"]


def test_clearance_overflow_is_a_fit_failure():
    spec = load_spec(ROOT / "fixtures/fitting_spec.yaml")
    report = build_report(apply_overrides(spec, ["mechanical.minimum_clearance_mm=100"]))
    assert report["fit"]["fits"] is False
    assert any("enclosure-wall clearance violated" in issue for issue in report["fit"]["issues"])


@pytest.mark.parametrize("override", [
    "mechanical.enclosure.width_mm=39",
    "mechanical.enclosure.height_mm=69",
    "mechanical.enclosure.thickness_mm=16",
    "mechanical.battery.diameter_mm=8.5",
    "mechanical.battery.length_mm=21",
    "mechanical.pcb.width_mm=13",
    "mechanical.pcb.height_mm=25",
    "mechanical.minimum_clearance_mm=0.75",
])
def test_each_required_parameter_override_changes_json_artifact(tmp_path, override):
    spec = ROOT / "fixtures/fitting_spec.yaml"
    baseline, changed = tmp_path / "baseline.json", tmp_path / "changed.json"
    main(["--spec", str(spec), "--output", str(baseline)])
    main(["--spec", str(spec), "--output", str(changed), "--set", override])
    assert baseline.read_bytes() != changed.read_bytes()


def test_cli_parameter_override_changes_artifact(tmp_path):
    spec = ROOT / "fixtures/fitting_spec.yaml"
    baseline_path, changed_path = tmp_path / "baseline.json", tmp_path / "changed.json"
    assert main(["--spec", str(spec), "--output", str(baseline_path)]) == 0
    assert main(["--spec", str(spec), "--output", str(changed_path), "--set", "mechanical.enclosure.width_mm=42"]) == 0
    assert json.loads(baseline_path.read_text()) != json.loads(changed_path.read_text())


def test_invalid_clearance_override_is_rejected():
    with pytest.raises(SpecError, match="positive"):
        apply_overrides(load_spec(ROOT / "fixtures/fitting_spec.yaml"), ["mechanical.minimum_clearance_mm=0"])


def test_cad_export_refuses_reports_with_clashes(tmp_path):
    report = build_report(load_spec(ROOT.parent.parent / "spec.yaml"))
    with pytest.raises(SpecError, match="fit/clash"):
        export_cad(report, tmp_path / "tag.step", tmp_path / "tag.stl")


def test_export_unavailable_is_explicit(tmp_path):
    if build_report(load_spec(ROOT / "fixtures/fitting_spec.yaml"))["cadquery_available"]:
        pytest.skip("CadQuery is available; covered by the CAD export integration test")
    report = build_report(load_spec(ROOT / "fixtures/fitting_spec.yaml"))
    with pytest.raises(SpecError, match="CadQuery unavailable"):
        export_cad(report, tmp_path / "tag.step")


def test_headless_step_stl_export_and_provenance(tmp_path):
    import hardware.mechanical.model as model

    if not model._cadquery_available():
        if os.environ.get("RIOSE_REQUIRE_CADQUERY") == "1":
            pytest.fail("CadQuery is required for the dedicated CAD export CI job")
        pytest.skip("CadQuery unavailable; dedicated CI CAD job installs requirements-cad.txt")
    step = tmp_path / "tag.step"
    spec = ROOT / "fixtures/fitting_spec.yaml"
    baseline_report = tmp_path / "baseline.json"
    changed_report = tmp_path / "changed.json"
    assert main(["--spec", str(spec), "--output", str(baseline_report), "--step", str(step)]) == 0
    changed_step = tmp_path / "changed.step"
    assert main(["--spec", str(spec), "--output", str(changed_report), "--step", str(changed_step),
                 "--set", "mechanical.enclosure.width_mm=42"]) == 0
    assert step.with_suffix(".stl").is_file()
    changed_stl = changed_step.with_suffix(".stl")
    assert step.is_file() and step.stat().st_size > 0
    assert step.read_text(encoding="ascii").startswith("ISO-10303-21;")
    assert step.with_suffix(".stl").stat().st_size > 0
    import cadquery as cq
    original_width = cq.importers.importStep(str(step)).val().BoundingBox().xlen
    changed_width = cq.importers.importStep(str(changed_step)).val().BoundingBox().xlen
    assert changed_width > original_width
    def stl_x_width(path):
        data = path.read_bytes()
        triangle_count = struct.unpack_from("<I", data, 80)[0]
        assert triangle_count > 0 and len(data) == 84 + triangle_count * 50
        xs = []
        for triangle in range(triangle_count):
            vertices = struct.unpack_from("<9f", data, 84 + triangle * 50 + 12)
            xs.extend((vertices[0], vertices[3], vertices[6]))
        return max(xs) - min(xs)

    assert stl_x_width(changed_stl) > stl_x_width(step.with_suffix(".stl"))
    for artifact in (step, step.with_suffix(".stl")):
        provenance = json.loads(artifact.with_suffix(artifact.suffix + ".provenance.json").read_text())
        assert provenance["analysis"] == "SIMULATED"
        assert provenance["physical_validation"] == "NOT_PERFORMED"
