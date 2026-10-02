from pathlib import Path
import json
import os
import struct

import pytest

from hardware.mechanical.model import SpecError, apply_overrides, build_report, export_cad, load_spec, main


ROOT = Path(__file__).parent


def test_fitting_assumed_spec_reports_mass_and_center_of_mass():
    spec = load_spec(ROOT / "fixtures/fitting_spec.yaml")
    report = build_report(spec)
    assert report["fit"]["fits"] is True
    assert report["gate"] == "CONDITIONALLY_READY_PENDING_THRESHOLD_APPROVAL"
    assert report["mass_estimate_g"]["total"] > 0
    assert set(report["mass_by_material_class_g"]) == {"enclosure", "pcb", "battery", "components"}
    assert set(report["center_of_mass_mm"]) == {"x_mm", "y_mm", "z_mm"}
    assert min(report["enclosure_wall_clearances_mm"]["pcb"].values()) >= 0.5
    assert report["clearances_mm"]["mcu/radio"] == pytest.approx(0.5)
    assert report["mounting_hole"]["status"] == "ASSUMED"
    assert "MEASURED" not in report["specification_statuses"]
    wall = spec["mechanical"]["enclosure"]["wall_thickness_mm"]["value"]
    hole_diameter = spec["mechanical"]["enclosure"]["mounting_hole_diameter_mm"]["value"]
    expected_hole_volume = 3.141592653589793 * (hole_diameter / 2) ** 2 * 2 * wall
    enclosure_shell_volume = (
        report["envelope_mm"]["width"] * report["envelope_mm"]["height"] * report["envelope_mm"]["thickness"]
        - report["internal_cavity_mm"]["width"] * report["internal_cavity_mm"]["height"] * report["internal_cavity_mm"]["thickness"]
        - expected_hole_volume
    )
    assert report["volume_mm3"]["enclosure"] == pytest.approx(enclosure_shell_volume)
    assert report["mass_estimate_g"]["parts"]["enclosure"] == pytest.approx(
        enclosure_shell_volume * report["materials"]["enclosure"]["density_g_cm3"] / 1000
    )
    assert not any(len(warning) == 1 for warning in report["warnings"])


def test_missing_material_density_is_reported_as_assumed_fallback():
    spec = load_spec(ROOT / "fixtures/fitting_spec.yaml")
    del spec["materials"]["pcb_density_g_cm3"]
    report = build_report(spec)
    assert "pcb density uses an ASSUMED fallback" in report["warnings"]
    assert not any(len(warning) == 1 for warning in report["warnings"])


def test_current_main_candidate_uses_explicit_spec_layout_without_rewriting_inputs():
    spec_path = ROOT.parent.parent / "spec.yaml"
    report = build_report(load_spec(spec_path))
    assert report["fit"]["fits"] is True
    assert report["fit"]["issues"] == []
    assert {part["name"] for part in report["parts"]} >= {"antenna", "antenna_keepout"}
    assert report["envelope_mm"] == {"width": 38.0, "height": 68.0, "thickness": 18.5}
    assert report["mass_estimate_g"]["status"] == "ASSUMED"
    assert report["provenance"]["analysis"] == "SIMULATED"
    assert report["provenance"]["physical_validation"] == "NOT_PERFORMED"
    spec = load_spec(spec_path)
    assert report["commercial_reference_envelope_mm"] == {
        "width": 38.0, "height": 68.0, "thickness": 15.0,
    }
    for dimension, raw in spec["mechanical"]["commercial_reference_envelope"].items():
        assert raw["status"] == "ASSUMED"
        assert report["commercial_reference_provenance"][dimension.removesuffix("_mm")]["source"] == raw["source"]
    assert spec["mechanical"]["enclosure"]["thickness_mm"]["status"] == "ASSUMED"


def test_layout_candidate_and_mounting_hole_positions_keep_spec_provenance():
    report = build_report(load_spec(ROOT.parent.parent / "spec.yaml"))
    issues = report["fit"]["issues"]
    parts = {part["name"]: part for part in report["parts"]}

    # The current main spec is the canonical source for explicit candidate centers.
    assert parts["pcb"]["x"] == pytest.approx(-1.8)
    assert parts["pcb"]["y"] == pytest.approx(-7.5)
    assert parts["battery"]["x"] == pytest.approx(-4.7)
    assert parts["battery"]["y"] == pytest.approx(24.25)
    assert "antenna_keepout envelope exceeds enclosure cavity" not in issues
    assert parts["antenna_keepout"]["bounds_mm"]["x"] == pytest.approx([-17.8, 14.2])

    # Keepout may extend off the PCB into empty cavity; the antenna conductor
    # itself must fit the board, while the battery does not intersect it here.
    assert parts["antenna"]["bounds_mm"]["x"] == pytest.approx([-15.8, 12.2])
    assert not any("violates antenna keepout" in issue for issue in issues)
    assert parts["battery"]["bounds_mm"]["x"] == pytest.approx([-17.3, 7.9])
    assert parts["battery"]["bounds_mm"]["y"] == pytest.approx([17.0, 31.5])
    assert report["mounting_hole"]["center_mm"] == pytest.approx({"x": 15.0, "y": 30.8})
    spec = load_spec(ROOT.parent.parent / "spec.yaml")
    for path in ("pcb_center_x_mm", "pcb_center_y_mm", "battery_center_x_mm", "battery_center_y_mm"):
        name = f"mechanical.layout_candidate.{path}"
        assert report["input_parameters"][name]["source"] == spec["mechanical"]["layout_candidate"][path]["source"]
        assert report["input_parameters"][name]["status"] == "ASSUMED"
    hole = report["input_parameters"]["mechanical.enclosure.mounting_hole_center_x_mm"]
    assert hole["value"] == 15
    assert hole["status"] == "ASSUMED"
    assert hole["source"] == spec["mechanical"]["enclosure"]["mounting_hole_center_x_mm"]["source"]


@pytest.mark.parametrize(("path", "value", "part", "axis"), [
    ("mechanical.layout_candidate.pcb_center_x_mm", "-0.8", "pcb", "x"),
    ("mechanical.layout_candidate.pcb_center_y_mm", "-8.0", "pcb", "y"),
    ("mechanical.layout_candidate.battery_center_x_mm", "-3.7", "battery", "x"),
    ("mechanical.layout_candidate.battery_center_y_mm", "24.75", "battery", "y"),
])
def test_explicit_layout_coordinate_changes_report_fit_and_com(path, value, part, axis):
    spec = load_spec(ROOT.parent.parent / "spec.yaml")
    baseline = build_report(spec)
    changed = build_report(apply_overrides(spec, [f"{path}={value}"]))
    before = next(row for row in baseline["parts"] if row["name"] == part)
    after = next(row for row in changed["parts"] if row["name"] == part)
    assert after[axis] == pytest.approx(float(value))
    assert changed["input_parameters"][path]["status"] == "SIMULATED"
    assert changed["input_parameters"][path]["source"].startswith("CLI override:")
    assert after[axis] != before[axis]
    assert changed["center_of_mass_mm"] != baseline["center_of_mass_mm"]


def test_mounting_hole_parameter_changes_report_and_center_of_mass():
    spec = load_spec(ROOT.parent.parent / "spec.yaml")
    baseline = build_report(spec)
    changed = build_report(apply_overrides(spec, ["mechanical.enclosure.mounting_hole_center_x_mm=14.5"]))
    assert changed["mounting_hole"]["center_mm"]["x"] == pytest.approx(14.5)
    assert changed["input_parameters"]["mechanical.enclosure.mounting_hole_center_x_mm"]["status"] == "SIMULATED"
    assert changed["center_of_mass_mm"] != baseline["center_of_mass_mm"]


def test_antenna_keepout_clash_with_battery_fails():
    spec = load_spec(ROOT.parent.parent / "spec.yaml")
    report = build_report(apply_overrides(spec, ["mechanical.layout_candidate.battery_center_y_mm=23.5"]))
    assert "battery envelope violates antenna keepout" in report["fit"]["issues"]


def test_sub_clearance_distance_to_keepout_fails():
    spec = load_spec(ROOT / "fixtures/fitting_spec.yaml")
    spec["mechanical"]["battery"]["diameter_mm"]["value"] = 1.0
    spec["mechanical"]["battery"]["length_mm"]["value"] = 1.0
    spec["mechanical"]["antenna"]["height_mm"]["value"] = 17.75
    report = build_report(spec)
    assert report["fit"]["fits"] is False
    assert any("minimum antenna-keepout clearance violated: mcu" in issue for issue in report["fit"]["issues"])


def test_battery_pcb_clearance_near_miss_is_reported():
    spec = load_spec(ROOT.parent.parent / "spec.yaml")
    spec["mechanical"]["layout_candidate"]["battery_center_y_mm"]["value"] = 23.85
    report = build_report(spec)
    assert "battery violates minimum clearance to pcb envelope" in report["fit"]["issues"]
    assert report["fit"]["fits"] is False


def test_mounting_hole_clearance_near_miss_is_reported():
    spec = load_spec(ROOT.parent.parent / "spec.yaml")
    report = build_report(apply_overrides(spec, ["mechanical.enclosure.mounting_hole_center_x_mm=10"]))
    assert "mounting hole violates clearance to battery envelope" in report["fit"]["issues"]
    assert report["fit"]["fits"] is False


def test_mounting_hole_must_remain_inside_enclosure_width():
    spec = load_spec(ROOT.parent.parent / "spec.yaml")
    report = build_report(apply_overrides(spec, ["mechanical.enclosure.mounting_hole_center_x_mm=18"]))
    assert "mounting hole is outside the enclosure envelope" in report["fit"]["issues"]
    assert report["fit"]["fits"] is False


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


def test_cli_fails_when_overridden_geometry_has_fit_blockers(tmp_path):
    spec_path = ROOT.parent.parent / "spec.yaml"
    output = tmp_path / "geometry.json"
    assert main(["--spec", str(spec_path), "--output", str(output),
                 "--set", "mechanical.minimum_clearance_mm=100"]) == 1
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


def test_cli_rejects_output_path_collisions_without_clobbering(tmp_path):
    spec = ROOT / "fixtures/fitting_spec.yaml"
    shared = tmp_path / "shared.output"
    shared.write_text("preserve this file")
    assert main(["--spec", str(spec), "--output", str(shared), "--step", str(shared)]) == 2
    assert shared.read_text() == "preserve this file"

    original_spec = spec.read_text()
    assert main(["--spec", str(spec), "--output", str(spec)]) == 2
    assert spec.read_text() == original_spec


def test_invalid_clearance_override_is_rejected():
    with pytest.raises(SpecError, match="positive"):
        apply_overrides(load_spec(ROOT / "fixtures/fitting_spec.yaml"), ["mechanical.minimum_clearance_mm=0"])


def test_cad_export_refuses_reports_with_clashes(tmp_path):
    report = build_report(apply_overrides(
        load_spec(ROOT.parent.parent / "spec.yaml"), ["mechanical.minimum_clearance_mm=100"]
    ))
    outputs = [tmp_path / "tag.step", tmp_path / "tag.step.provenance.json",
               tmp_path / "tag.stl", tmp_path / "tag.stl.provenance.json"]
    for output in outputs:
        output.write_text("stale artifact")
    with pytest.raises(SpecError, match="fit/clash"):
        export_cad(report, outputs[0], outputs[2])
    assert all(not output.exists() for output in outputs)


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
    step_text = step.read_text(encoding="ascii")
    for part_name in ("enclosure_shell", "pcb", "battery", "mcu", "radio", "imu", "antenna"):
        assert part_name in step_text
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
    changed_provenance = json.loads(changed_step.with_suffix(".step.provenance.json").read_text())
    assert changed_provenance["inputs"]["mechanical.enclosure.width_mm"]["source"].startswith("CLI override:")
    assert changed_provenance["inputs"]["mechanical.enclosure.width_mm"]["status"] == "SIMULATED"

    imported = cq.importers.importStep(str(step))
    solids = imported.solids().vals()
    assert len(solids) == 7
    assert all(shape.isValid() for shape in solids)
    assert sum(shape.Volume() for shape in solids) == pytest.approx(
        sum(json.loads(baseline_report.read_text())["volume_mm3"].values()), rel=1e-8
    )
    assert any(
        abs(shape.BoundingBox().xlen - 20) < 1e-6
        and abs(shape.BoundingBox().ylen - 8) < 1e-6
        and abs(shape.BoundingBox().zlen - 8) < 1e-6
        for shape in solids
    )

    def geometry_signature(path):
        imported_shapes = cq.importers.importStep(str(path)).solids().vals()
        return sorted(
            tuple(round(value, 5) for value in (
                shape.BoundingBox().xmin, shape.BoundingBox().ymin, shape.BoundingBox().zmin,
                shape.BoundingBox().xmax, shape.BoundingBox().ymax, shape.BoundingBox().zmax,
                shape.Volume(),
            ))
            for shape in imported_shapes
        )

    baseline_signature = geometry_signature(step)
    for index, override in enumerate((
        "mechanical.enclosure.height_mm=69",
        "mechanical.enclosure.thickness_mm=16",
        "mechanical.battery.diameter_mm=8.5",
        "mechanical.battery.length_mm=21",
        "mechanical.pcb.width_mm=13",
        "mechanical.pcb.height_mm=25",
        "mechanical.minimum_clearance_mm=0.75",
    )):
        variant_step = tmp_path / f"variant_{index}.step"
        variant_report = tmp_path / f"variant_{index}.json"
        assert main([
            "--spec", str(spec), "--output", str(variant_report), "--step", str(variant_step),
            "--set", override,
        ]) == 0
        variant_stl = variant_step.with_suffix(".stl")
        assert variant_step.read_bytes() != step.read_bytes()
        assert variant_stl.read_bytes() != step.with_suffix(".stl").read_bytes()
        assert geometry_signature(variant_step) != baseline_signature, override


def test_current_candidate_step_stl_uses_spec_positions_and_provenance(tmp_path):
    import cadquery as cq

    spec = ROOT.parent.parent / "spec.yaml"
    report_path, step_path = tmp_path / "candidate.json", tmp_path / "candidate.step"
    assert main(["--spec", str(spec), "--output", str(report_path), "--step", str(step_path)]) == 0
    stl_path = step_path.with_suffix(".stl")
    report = json.loads(report_path.read_text())
    assert report["fit"]["fits"] is True
    assert step_path.is_file() and stl_path.is_file()
    assert step_path.read_text(encoding="ascii").startswith("ISO-10303-21;")
    step_text = step_path.read_text(encoding="ascii")
    for name in ("enclosure_shell", "pcb", "battery", "mcu", "radio", "imu", "antenna"):
        assert name in step_text

    imported = cq.importers.importStep(str(step_path))
    solids = imported.solids().vals()
    assert len(solids) == 7 and all(shape.isValid() for shape in solids)
    assert sum(shape.Volume() for shape in solids) == pytest.approx(
        sum(report["volume_mm3"].values()), rel=1e-8
    )

    def matching_solid(width, height, thickness):
        matches = [shape for shape in solids if
                   shape.BoundingBox().xlen == pytest.approx(width, abs=1e-5) and
                   shape.BoundingBox().ylen == pytest.approx(height, abs=1e-5) and
                   shape.BoundingBox().zlen == pytest.approx(thickness, abs=1e-5)]
        assert len(matches) == 1
        return matches[0]

    pcb = matching_solid(30.0, 48.0, 1.6).BoundingBox()
    assert (pcb.xmin + pcb.xmax) / 2 == pytest.approx(-1.8, abs=1e-5)
    assert (pcb.ymin + pcb.ymax) / 2 == pytest.approx(-7.5, abs=1e-5)
    battery = matching_solid(25.2, 14.5, 14.5).BoundingBox()
    assert (battery.xmin + battery.xmax) / 2 == pytest.approx(-4.7, abs=1e-5)
    assert (battery.ymin + battery.ymax) / 2 == pytest.approx(24.25, abs=1e-5)

    hole = report["mounting_hole"]
    shell = max(solids, key=lambda shape: shape.Volume())
    circular_edges = [edge for edge in shell.Edges() if edge.geomType() == "CIRCLE"]
    assert any(abs(edge.radius() - hole["diameter_mm"] / 2) < 1e-5 and
               abs(edge.Center().x - hole["center_mm"]["x"]) < 1e-5 and
               abs(edge.Center().y - hole["center_mm"]["y"]) < 1e-5
               for edge in circular_edges)

    stl_data = stl_path.read_bytes()
    triangle_count = struct.unpack_from("<I", stl_data, 80)[0]
    assert triangle_count > 0 and len(stl_data) == 84 + triangle_count * 50
    vertices = [struct.unpack_from("<9f", stl_data, 84 + index * 50 + 12)
                for index in range(triangle_count)]
    coordinates = [[vertex[offset] for vertex in vertices for offset in (axis, axis + 3, axis + 6)]
                   for axis in (0, 1, 2)]
    stl_extents = [max(axis) - min(axis) for axis in coordinates]
    assert stl_extents == pytest.approx([38.0, 68.0, 18.5], abs=0.05)

    for suffix in (".step", ".stl"):
        provenance = json.loads((tmp_path / f"candidate{suffix}.provenance.json").read_text())
        assert provenance["physical_validation"] == "NOT_PERFORMED"
        assert provenance["commercial_reference_envelope_mm"] == {
            "width": 38.0, "height": 68.0, "thickness": 15.0,
        }
        assert all(value["status"] == "ASSUMED"
                   for value in provenance["commercial_reference_provenance"].values())
        for key in ("mechanical.layout_candidate.pcb_center_x_mm",
                    "mechanical.layout_candidate.pcb_center_y_mm",
                    "mechanical.layout_candidate.battery_center_x_mm",
                    "mechanical.layout_candidate.battery_center_y_mm",
                    "mechanical.enclosure.mounting_hole_center_x_mm"):
            assert provenance["inputs"][key]["status"] == "ASSUMED"
            assert provenance["inputs"][key]["source"]


@pytest.mark.parametrize(("parameter", "value", "part", "axis"), [
    ("mechanical.layout_candidate.pcb_center_x_mm", "-0.8", "pcb", "x"),
    ("mechanical.layout_candidate.pcb_center_y_mm", "-8.0", "pcb", "y"),
    ("mechanical.layout_candidate.battery_center_x_mm", "-3.7", "battery", "x"),
    ("mechanical.layout_candidate.battery_center_y_mm", "24.75", "battery", "y"),
    ("mechanical.enclosure.mounting_hole_center_x_mm", "14.5", "enclosure_shell", "hole_x"),
])
def test_current_candidate_coordinate_overrides_change_real_step(tmp_path, parameter, value, part, axis):
    import cadquery as cq

    spec = ROOT.parent.parent / "spec.yaml"
    base_step = tmp_path / "base.step"
    changed_step = tmp_path / "changed.step"
    assert main(["--spec", str(spec), "--output", str(tmp_path / "base.json"), "--step", str(base_step)]) == 0
    assert main(["--spec", str(spec), "--output", str(tmp_path / "changed.json"), "--step", str(changed_step),
                 "--set", f"{parameter}={value}"]) == 0
    base_solids = cq.importers.importStep(str(base_step)).solids().vals()
    changed_solids = cq.importers.importStep(str(changed_step)).solids().vals()
    if part in {"pcb", "battery"}:
        def part_center(shapes):
            dimensions = (30, 48, 1.6) if part == "pcb" else (25.2, 14.5, 14.5)
            shape = next(shape for shape in shapes if
                         shape.BoundingBox().xlen == pytest.approx(dimensions[0], abs=1e-5) and
                         shape.BoundingBox().ylen == pytest.approx(dimensions[1], abs=1e-5) and
                         shape.BoundingBox().zlen == pytest.approx(dimensions[2], abs=1e-5))
            bounds = shape.BoundingBox()
            return (bounds.xmin + bounds.xmax) / 2 if axis == "x" else (bounds.ymin + bounds.ymax) / 2
        assert part_center(base_solids) != pytest.approx(float(value), abs=1e-5)
        assert part_center(changed_solids) == pytest.approx(float(value), abs=1e-5)
    else:
        def hole_edges(shapes):
            shell = max(shapes, key=lambda shape: shape.Volume())
            return [edge for edge in shell.Edges() if edge.geomType() == "CIRCLE" and
                    abs(edge.radius() - 2.0) < 1e-5 and abs(edge.Center().y - 30.8) < 1e-5]
        assert any(abs(edge.Center().x - 15.0) < 1e-5 for edge in hole_edges(base_solids))
        assert any(abs(edge.Center().x - float(value)) < 1e-5 for edge in hole_edges(changed_solids))
    changed_report = json.loads((tmp_path / "changed.json").read_text())
    assert changed_report["input_parameters"][parameter]["status"] == "SIMULATED"
    assert changed_report["input_parameters"][parameter]["source"].startswith("CLI override:")
