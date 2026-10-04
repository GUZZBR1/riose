from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from hardware.antenna import SCENARIOS
from hardware.antenna.geometry import GeometryError, add_primitives, build_geometry, meander_path


@pytest.fixture
def spec():
    return yaml.safe_load(Path("hardware/spec.yaml").read_text())


def test_meander_length_is_exact_and_within_declared_footprint():
    points = meander_path(82.0, 28.0, 10.0, 1.0, turns=4)
    assert sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
               for a, b in zip(points, points[1:])) == pytest.approx(82.0)
    assert max(point[0] for point in points) - min(point[0] for point in points) + 1.0 <= 28.0
    assert max(point[1] for point in points) - min(point[1] for point in points) + 1.0 <= 10.0


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_builds_deterministic_csx_geometry_for_each_scenario(spec, scenario):
    first = build_geometry(spec, scenario)
    second = build_geometry(spec, scenario)
    assert first["geometry_hash_sha256"] == second["geometry_hash_sha256"]
    assert first["geometry_method"].startswith("CSXCAD primitives")
    assert first["antenna"]["route_length_mm"] == spec["antenna"]["element_length_mm"]["value"]
    assert len(first["primitives"]) >= 6
    assert all(p["material"] != "STL" for p in first["primitives"])


def test_scenarios_are_nested_and_animal_is_explicitly_assumed(spec):
    free = build_geometry(spec, "ANTENNA_FREE_SPACE")
    pcb = build_geometry(spec, "ANTENNA_WITH_PCB")
    battery = build_geometry(spec, "ANTENNA_WITH_BATTERY")
    enclosure = build_geometry(spec, "ANTENNA_WITH_ENCLOSURE")
    animal = build_geometry(spec, "ANTENNA_NEAR_ANIMAL_APPROXIMATION")
    assert not free["scenario_contents"]["pcb"]
    assert pcb["scenario_contents"]["pcb"]
    assert battery["scenario_contents"]["battery"]
    assert enclosure["scenario_contents"]["enclosure"]
    assert animal["electromagnetic_materials"]["ANIMAL_TISSUE_APPROX_ASSUMED"]["status"] == "ASSUMED"
    assert "not live-animal" in animal["material_approximations"][0]


def test_spec_geometry_material_clearance_and_sweep_override_change_hash(spec):
    base = build_geometry(spec, "ANTENNA_WITH_ENCLOSURE")
    changed = build_geometry(spec, "ANTENNA_WITH_ENCLOSURE",
                             {"enclosure_relative_permittivity": 4.2, "enclosure_wall_thickness_mm": 1.6})
    assert base["geometry_hash_sha256"] != changed["geometry_hash_sha256"]
    material = changed["electromagnetic_materials"]["ENCLOSURE_TPU_ASSUMED_EPS_4.2"]
    assert material["relative_permittivity"] == pytest.approx(4.2)
    assert material["status"] == "ASSUMED"


def test_rf_candidate_matches_updated_mechanical_layout_without_clash(spec):
    geometry = build_geometry(spec, "ANTENNA_WITH_BATTERY")
    assert geometry["mechanical_clashes"] == []
    primitives = {p["name"]: p for p in geometry["primitives"]}
    assert primitives["pcb_substrate"]["start_mm"][:2] == pytest.approx([-16.8, -31.5])
    assert primitives["battery_envelope"]["start_mm"] == pytest.approx([-17.3, 17.0, 1.2])
    assert primitives["battery_envelope"]["stop_mm"] == pytest.approx([7.9, 31.5, 15.7])
    pcb_top = primitives["pcb_substrate"]["stop_mm"][1]
    battery_bottom = primitives["battery_envelope"]["start_mm"][1]
    assert battery_bottom - pcb_top == pytest.approx(0.5)


def test_ground_plane_is_partial_and_covers_feed_reference(spec):
    geometry = build_geometry(spec, "ANTENNA_FREE_SPACE")
    plane = next(p for p in geometry["primitives"] if p["name"] == "ground_plane")
    feed_y = geometry["antenna"]["feed_point_mm"][1]
    trace_width = spec["antenna"]["trace_width_mm"]["value"]
    assert plane["stop_mm"][1] == pytest.approx(geometry["antenna"]["ground_plane_y_bounds_mm"][1])
    assert plane["stop_mm"][1] >= feed_y + trace_width / 2
    assert plane["stop_mm"][1] < max(point[1] for point in geometry["antenna"]["route_points_mm"])
    changed = copy.deepcopy(spec)
    changed["antenna"]["ground_plane_length_mm"]["value"] += 1
    assert build_geometry(changed, "ANTENNA_FREE_SPACE")["geometry_hash_sha256"] != geometry["geometry_hash_sha256"]


def test_ground_plane_must_cover_feed_trace(spec):
    invalid = copy.deepcopy(spec)
    invalid["antenna"]["ground_plane_length_mm"]["value"] = 20
    with pytest.raises(GeometryError, match="cover the complete feed trace width"):
        build_geometry(invalid, "ANTENNA_FREE_SPACE")


def test_invalid_scenario_dimensions_and_measured_inputs_rejected(spec):
    with pytest.raises(GeometryError, match="unknown antenna scenario"):
        build_geometry(spec, "ANTENNA_NOT_REAL")
    with pytest.raises(GeometryError, match="does not fit"):
        meander_path(1000, 28, 10, 1, 4)
    invalid = copy.deepcopy(spec)
    invalid["antenna"]["trace_width_mm"]["status"] = "MEASURED"
    with pytest.raises(GeometryError, match="not permitted"):
        build_geometry(invalid, "ANTENNA_FREE_SPACE")
    with pytest.raises(GeometryError, match="supports only 0 or 90"):
        build_geometry(spec, "ANTENNA_NEAR_ANIMAL_APPROXIMATION", {"animal_orientation_deg": 45})


def test_add_primitives_uses_native_csx_properties_without_stl(spec):
    class Property:
        def __init__(self):
            self.boxes = []

        def AddBox(self, **kwargs):
            self.boxes.append(kwargs)

    class CSX:
        def __init__(self):
            self.properties = {}

        def AddMetal(self, name):
            prop = Property()
            self.properties[name] = prop
            return prop

        def AddMaterial(self, name, **kwargs):
            prop = Property()
            prop.material = kwargs
            self.properties[name] = prop
            return prop

    geometry = build_geometry(spec, "ANTENNA_NEAR_ANIMAL_APPROXIMATION")
    csx = CSX()
    metadata = add_primitives(csx, geometry, spec)
    assert metadata["primitive_count"] == len(geometry["primitives"])
    assert metadata["material_names"] == sorted({p["material"] for p in geometry["primitives"]})
    assert csx.properties["ANIMAL_TISSUE_APPROX_ASSUMED"].material["epsilon"] == 50.0
    assert sum(len(p.boxes) for p in csx.properties.values()) == len(geometry["primitives"])


@pytest.mark.parametrize("source", [None, "", "  "])
def test_geometry_rejects_empty_provenance_source(spec, source):
    spec["antenna"]["trace_width_mm"]["source"] = source
    with pytest.raises(GeometryError, match="source must be a non-empty string"):
        build_geometry(spec, "ANTENNA_FREE_SPACE")


def test_feed_gap_changes_physical_trace_and_port_extent(spec):
    small = build_geometry(spec, "ANTENNA_WITH_PCB", {"feed_gap_mm": 0.25})
    large = build_geometry(spec, "ANTENNA_WITH_PCB", {"feed_gap_mm": 1.0})
    assert large["antenna"]["trace_z_mm"][0] - small["antenna"]["trace_z_mm"][0] == pytest.approx(0.75)
    assert large["antenna"]["ground_plane_z_mm"] == small["antenna"]["ground_plane_z_mm"]
    small_trace = next(p for p in small["primitives"] if p["name"] == "antenna_trace_00")
    large_trace = next(p for p in large["primitives"] if p["name"] == "antenna_trace_00")
    assert large_trace["start_mm"][2] - small_trace["start_mm"][2] == pytest.approx(0.75)


def test_enclosure_has_all_six_physical_faces(spec):
    geometry = build_geometry(spec, "ANTENNA_WITH_ENCLOSURE")
    faces = {p["name"]: p for p in geometry["primitives"] if p["name"].startswith("enclosure_")}
    assert set(faces) == {f"enclosure_{side}_wall" for side in ("left", "right", "front", "back", "bottom", "top")}
    height = spec["mechanical"]["enclosure"]["height_mm"]["value"]
    assert faces["enclosure_front_wall"]["start_mm"][1] == pytest.approx(-height / 2)
    assert faces["enclosure_back_wall"]["stop_mm"][1] == pytest.approx(height / 2)
