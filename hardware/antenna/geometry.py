"""Parametric antenna and tag RF geometry contracts.

Dimensions are read from ``hardware/spec.yaml`` and remain ASSUMED unless the
spec says otherwise. The CSXCAD adapter reconstructs these shapes directly;
mechanical STEP/STL files are not imported into the electromagnetic model.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any

from . import SCENARIOS


class GeometryError(ValueError):
    """The RF geometry cannot be derived from the central specification."""


@dataclass(frozen=True)
class Box:
    name: str
    start_mm: tuple[float, float, float]
    stop_mm: tuple[float, float, float]
    material: str
    provenance: str


SCENARIO_CONTENTS = {
    # The finite ground plane is part of the antenna reference in every case.
    "ANTENNA_FREE_SPACE": (False, False, False, False),
    "ANTENNA_WITH_PCB": (True, False, False, False),
    "ANTENNA_WITH_BATTERY": (True, True, False, False),
    "ANTENNA_WITH_ENCLOSURE": (True, True, True, False),
    "ANTENNA_NEAR_ANIMAL_APPROXIMATION": (True, True, True, True),
}


def _record(spec: dict[str, Any], path: str) -> dict[str, Any]:
    node: Any = spec
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            raise GeometryError(f"missing spec record: {path}")
        node = node[key]
    if not isinstance(node, dict) or not {"value", "unit", "source", "status"} <= node.keys():
        raise GeometryError(f"{path} must contain value, unit, source and status")
    if not isinstance(node["source"], str) or not node["source"].strip():
        raise GeometryError(f"{path}.source must be a non-empty string")
    status = str(node["status"]).upper()
    if status not in {"DATASHEET", "ASSUMED", "SIMULATED"}:
        raise GeometryError(f"{path}.status is not permitted for RF input: {status}")
    return {**node, "status": status}


def _number(spec: dict[str, Any], path: str, *, unit: str = "mm") -> tuple[float, dict[str, Any]]:
    item = _record(spec, path)
    if str(item["unit"]).lower() != unit.lower():
        raise GeometryError(f"{path}.unit must be {unit}")
    try:
        value = float(item["value"])
    except (TypeError, ValueError) as exc:
        raise GeometryError(f"{path}.value must be numeric") from exc
    if not math.isfinite(value) or value <= 0:
        raise GeometryError(f"{path}.value must be positive and finite")
    return value, item


def meander_path(length_mm: float, width_mm: float, height_mm: float,
                 trace_width_mm: float, turns: int = 4) -> tuple[tuple[float, float], ...]:
    """Return a centered, orthogonal path with a calculable total length."""
    values = (length_mm, width_mm, height_mm, trace_width_mm)
    if not all(math.isfinite(value) and value > 0 for value in values):
        raise GeometryError("meander dimensions must be positive and finite")
    if isinstance(turns, bool) or not isinstance(turns, int) or turns < 1:
        raise GeometryError("meander_turns must be a positive integer")
    if width_mm < trace_width_mm or height_mm < trace_width_mm:
        raise GeometryError("meander trace does not fit its footprint")
    rows = turns + 1
    y_step = (height_mm - trace_width_mm) / turns
    horizontal = (length_mm - turns * y_step) / rows
    if horizontal <= 0 or horizontal + trace_width_mm > width_mm + 1e-9:
        raise GeometryError("requested conductor length does not fit the meander footprint")
    x0, x1 = -horizontal / 2, horizontal / 2
    y0 = -height_mm / 2 + trace_width_mm / 2
    points: list[tuple[float, float]] = []
    for index in range(rows):
        y = y0 + index * y_step
        points.append((x0 if index % 2 == 0 else x1, y))
        points.append((x1 if index % 2 == 0 else x0, y))
        if index < turns:
            next_y = y0 + (index + 1) * y_step
            points.append((x1 if index % 2 == 0 else x0, next_y))
    actual = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
    if not math.isclose(actual, length_mm, rel_tol=0, abs_tol=1e-8):
        raise GeometryError("internal meander-length calculation mismatch")
    return tuple(points)


def _box(name: str, center: tuple[float, float, float], size: tuple[float, float, float],
         material: str, provenance: str) -> Box:
    if any(not math.isfinite(v) or v <= 0 for v in size):
        raise GeometryError(f"{name} dimensions must be positive and finite")
    x, y, z = center
    dx, dy, dz = size
    return Box(name, (x - dx / 2, y - dy / 2, z - dz / 2),
               (x + dx / 2, y + dy / 2, z + dz / 2), material, provenance)


def build_geometry(spec: dict[str, Any], scenario: str,
                   overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a deterministic, serializable CSXCAD primitive description."""
    if scenario not in SCENARIO_CONTENTS:
        raise GeometryError(f"unknown antenna scenario: {scenario}")
    overrides = overrides or {}
    include_pcb, include_battery, include_enclosure, include_animal = SCENARIO_CONTENTS[scenario]
    antenna = spec.get("antenna", {})
    mechanical = spec.get("mechanical", {})

    def record(path: str, override_key: str | None = None) -> tuple[float, dict[str, Any]]:
        if override_key and override_key in overrides:
            original = _record(spec, path)
            value = float(overrides[override_key])
            if not math.isfinite(value) or value <= 0:
                raise GeometryError(f"sweep override {override_key} must be positive and finite")
            return value, {**original, "value": value, "source": f"sweep override of {original['source']}"}
        if path in ("mechanical.antenna.width_mm", "mechanical.antenna.height_mm"):
            return _number(spec, path)
        if path not in ("antenna.center_frequency_hz",):
            return _number(spec, path)
        return _number(spec, path, unit="Hz")

    frequency, freq_record = record("antenna.center_frequency_hz")
    element, element_record = record("antenna.element_length_mm")
    trace_width, trace_record = record("antenna.trace_width_mm")
    feed_gap, feed_record = record("antenna.feed_gap_mm", "feed_gap_mm")
    conductor_thickness, conductor_record = record("antenna.conductor_thickness_mm")
    meander_width, width_record = record("mechanical.antenna.width_mm")
    meander_height, height_record = record("mechanical.antenna.height_mm")
    pcb_width, pcb_width_record = record("mechanical.pcb.width_mm")
    pcb_height, pcb_height_record = record("mechanical.pcb.height_mm")
    pcb_thickness, pcb_thickness_record = record("mechanical.pcb.thickness_mm")
    enclosure_width, enc_width_record = record("mechanical.enclosure.width_mm")
    enclosure_height, enc_height_record = record("mechanical.enclosure.height_mm")
    enclosure_thickness, enc_thick_record = record("mechanical.enclosure.thickness_mm")
    wall, wall_record = record("mechanical.enclosure.wall_thickness_mm", "enclosure_wall_thickness_mm")
    batt_length, batt_length_record = record("mechanical.battery.length_mm")
    batt_diameter, batt_diameter_record = record("mechanical.battery.diameter_mm")
    clearance, clearance_record = record("antenna.clearance_mm", "clearance_mm")
    turns_record = _record(spec, "antenna.meander_turns")
    raw_turns = turns_record["value"]
    if isinstance(raw_turns, bool) or int(raw_turns) != float(raw_turns) or int(raw_turns) < 1:
        raise GeometryError("antenna.meander_turns must be a positive integer")
    trace_turns = int(raw_turns)
    path = meander_path(element, meander_width, meander_height, trace_width, trace_turns)

    board_z = wall
    # Standard zero-thickness PEC sheets avoid an impractical CFL step from
    # meshing 35 um copper as a volumetric material.
    ground_z1 = board_z
    # The feed-gap sweep changes the physical air spacing above the substrate,
    # and therefore the PEC sheet and z-directed port, rather than only mesh lines.
    trace_z0 = board_z + pcb_thickness + feed_gap
    trace_z1 = trace_z0
    inner_width = enclosure_width - 2 * wall
    layout = mechanical.get("layout_candidate", {})
    pcb_x = float(layout.get("pcb_center_x_mm", {}).get("value", 0.0))
    pcb_y = float(layout.get("pcb_center_y_mm", {}).get("value", 0.0))
    battery_x = float(layout.get("battery_center_x_mm", {}).get("value", 0.0))
    battery_y = float(layout.get("battery_center_y_mm", {}).get("value", 0.0))
    # Match the mechanical candidate's board and antenna keepout placement.
    antenna_y = pcb_y + pcb_height / 2 - meander_height / 2 - clearance
    if inner_width <= 0:
        raise GeometryError("enclosure wall thickness leaves no internal RF geometry")
    antenna_x = pcb_x
    route = tuple((x + antenna_x, y + antenna_y) for x, y in path)
    feed_xy = route[0]

    boxes: list[Box] = []
    for index, (first, second) in enumerate(zip(route, route[1:])):
        dx, dy = abs(second[0] - first[0]), abs(second[1] - first[1])
        center_x, center_y = (first[0] + second[0]) / 2, (first[1] + second[1]) / 2
        half_x, half_y = max(dx, trace_width) / 2, max(dy, trace_width) / 2
        boxes.append(Box(f"antenna_trace_{index:02d}",
                         (center_x - half_x, center_y - half_y, trace_z0),
                         (center_x + half_x, center_y + half_y, trace_z0),
                         "PEC_ASSUMED_COPPER", trace_record["status"]))

    # A finite PEC return plane is part of the antenna candidate, including the
    # free-space reference. The substrate itself is added only WITH_PCB onward.
    boxes.append(Box("ground_plane", (pcb_x - pcb_width / 2, pcb_y - pcb_height / 2, board_z),
                     (pcb_x + pcb_width / 2, pcb_y + pcb_height / 2, board_z), "PEC_ASSUMED_COPPER",
                     conductor_record["status"]))
    if include_pcb:
        boxes.append(Box("pcb_substrate", (pcb_x - pcb_width / 2, pcb_y - pcb_height / 2, ground_z1),
                         (pcb_x + pcb_width / 2, pcb_y + pcb_height / 2, board_z + pcb_thickness), "FR4_ASSUMED",
                         pcb_thickness_record["status"]))
    if include_battery:
        # Match the canonical mechanical layout: battery long axis is X and its base sits at the inner floor.
        boxes.append(_box("battery_envelope", (battery_x, battery_y, wall + batt_diameter / 2),
                          (batt_length, batt_diameter, batt_diameter), "BATTERY_ENVELOPE_ASSUMED",
                          batt_length_record["status"]))
    if include_enclosure:
        eps = float(overrides.get("enclosure_relative_permittivity",
                                  _record(spec, "materials.enclosure_relative_permittivity")["value"]))
        material = f"ENCLOSURE_TPU_ASSUMED_EPS_{eps:g}"
        inner_w, inner_h = enclosure_width - 2 * wall, enclosure_height - 2 * wall
        z0, z1 = 0.0, enclosure_thickness
        boxes.extend((
            _box("enclosure_left_wall", (-enclosure_width / 2 + wall / 2, 0, (z0 + z1) / 2),
                 (wall, enclosure_height, enclosure_thickness), material, wall_record["status"]),
            _box("enclosure_right_wall", (enclosure_width / 2 - wall / 2, 0, (z0 + z1) / 2),
                 (wall, enclosure_height, enclosure_thickness), material, wall_record["status"]),
            _box("enclosure_front_wall", (0, -enclosure_height / 2 + wall / 2, (z0 + z1) / 2),
                 (inner_w, wall, enclosure_thickness), material, wall_record["status"]),
            _box("enclosure_back_wall", (0, enclosure_height / 2 - wall / 2, (z0 + z1) / 2),
                 (inner_w, wall, enclosure_thickness), material, wall_record["status"]),
            _box("enclosure_bottom_wall", (0, 0, wall / 2), (enclosure_width, enclosure_height, wall),
                 material, wall_record["status"]),
            _box("enclosure_top_wall", (0, 0, z1 - wall / 2), (enclosure_width, enclosure_height, wall),
                 material, wall_record["status"]),
        ))
    assumptions: list[str] = []
    electromagnetic_materials: dict[str, dict[str, Any]] = {}
    if include_pcb:
        pcb_eps_record = _record(spec, "materials.pcb_relative_permittivity")
        pcb_loss_record = _record(spec, "materials.pcb_loss_tangent")
        electromagnetic_materials["FR4_ASSUMED"] = {
            "relative_permittivity": float(pcb_eps_record["value"]),
            "loss_tangent": float(pcb_loss_record["value"]),
            "status": "ASSUMED",
            "source": f"{pcb_eps_record['source']}; {pcb_loss_record['source']}",
            "conductivity_s_m": 2 * math.pi * frequency * 8.8541878128e-12
            * float(pcb_eps_record["value"]) * float(pcb_loss_record["value"]),
        }
    if include_battery:
        batt_eps = _record(spec, "materials.battery_relative_permittivity")
        batt_sigma = _record(spec, "materials.battery_conductivity_s_m")
        electromagnetic_materials["BATTERY_ENVELOPE_ASSUMED"] = {
            "relative_permittivity": float(batt_eps["value"]),
            "conductivity_s_m": float(batt_sigma["value"]), "status": "ASSUMED",
            "source": f"{batt_eps['source']}; {batt_sigma['source']}",
        }
    if include_enclosure:
        enc_eps_record = _record(spec, "materials.enclosure_relative_permittivity")
        enc_eps = float(overrides.get("enclosure_relative_permittivity", enc_eps_record["value"]))
        enc_sigma = _record(spec, "materials.enclosure_conductivity_s_m")
        electromagnetic_materials[f"ENCLOSURE_TPU_ASSUMED_EPS_{enc_eps:g}"] = {
            "relative_permittivity": enc_eps,
            "conductivity_s_m": float(enc_sigma["value"]), "status": "ASSUMED",
            "source": f"{enc_eps_record['source']}; {enc_sigma['source']}",
        }
    if include_animal:
        tissue_thickness, tissue_record = record("materials.animal_approx_thickness_mm")
        raw_orientation = overrides.get("animal_orientation_deg", 0)
        if isinstance(raw_orientation, bool) or float(raw_orientation) not in (0.0, 90.0):
            raise GeometryError("animal_orientation_deg currently supports only 0 or 90 degrees")
        orientation = int(raw_orientation)
        animal_width, animal_height = ((enclosure_width, enclosure_height) if orientation == 0
                                       else (enclosure_height, enclosure_width))
        boxes.append(_box("animal_homogeneous_approximation", (0, 0,
                          board_z + enclosure_thickness + tissue_thickness / 2 + clearance),
                          (animal_width, animal_height, tissue_thickness), "ANIMAL_TISSUE_APPROX_ASSUMED",
                          tissue_record["status"]))
        assumptions.append("ASSUMED homogeneous dielectric sensitivity layer; not live-animal or tissue validation")
        tissue_eps = _record(spec, "materials.animal_approx_relative_permittivity")
        tissue_sigma = _record(spec, "materials.animal_approx_conductivity_s_m")
        orientation_record = {"value": orientation, "unit": "deg",
                             "source": str(overrides.get("animal_orientation_source", "default axis-aligned sensitivity orientation")),
                             "status": "ASSUMED"}
        electromagnetic_materials["ANIMAL_TISSUE_APPROX_ASSUMED"] = {
            "relative_permittivity": float(tissue_eps["value"]),
            "conductivity_s_m": float(tissue_sigma["value"]), "status": "ASSUMED",
            "source": f"{tissue_eps['source']}; {tissue_sigma['source']}; orientation {orientation_record['source']}",
            "thickness_mm": tissue_thickness,
            "orientation_deg": orientation_record["value"],
        }

    records = {
        "center_frequency_hz": freq_record,
        "element_length_mm": element_record,
        "trace_width_mm": trace_record,
        "feed_gap_mm": feed_record,
        "antenna_footprint_width_mm": width_record,
        "antenna_footprint_height_mm": height_record,
        "clearance_mm": clearance_record,
        "conductor_thickness_mm": conductor_record,
        "pcb_width_mm": pcb_width_record,
        "pcb_height_mm": pcb_height_record,
        "pcb_thickness_mm": pcb_thickness_record,
        "enclosure_width_mm": enc_width_record,
        "enclosure_height_mm": enc_height_record,
        "enclosure_thickness_mm": enc_thick_record,
        "enclosure_wall_thickness_mm": wall_record,
        "battery_length_mm": batt_length_record,
        "battery_diameter_mm": batt_diameter_record,
        "meander_turns": turns_record,
    }
    mechanical_clashes: list[str] = []
    if include_battery:
        pcb_x_bounds = (pcb_x - pcb_width / 2, pcb_x + pcb_width / 2)
        pcb_y_bounds = (pcb_y - pcb_height / 2, pcb_y + pcb_height / 2)
        battery_x_bounds = (battery_x - batt_length / 2, battery_x + batt_length / 2)
        x_overlap = min(pcb_x_bounds[1], battery_x_bounds[1]) - max(pcb_x_bounds[0], battery_x_bounds[0])
        battery_y_bounds = (battery_y - batt_diameter / 2, battery_y + batt_diameter / 2)
        y_overlap = min(pcb_y_bounds[1], battery_y_bounds[1]) - max(pcb_y_bounds[0], battery_y_bounds[0])
        pcb_z_bounds = (wall, wall + pcb_thickness)
        battery_z_bounds = (wall, wall + batt_diameter)
        z_overlap = min(pcb_z_bounds[1], battery_z_bounds[1]) - max(pcb_z_bounds[0], battery_z_bounds[0])
        if x_overlap > 1e-9 and y_overlap > 1e-9 and z_overlap > 1e-9:
            mechanical_clashes.append("battery envelope intersects the PCB envelope per mechanical/model.py placements")
        if (battery_x_bounds[0] < -inner_width / 2 - 1e-9
                or battery_x_bounds[1] > inner_width / 2 + 1e-9
                or battery_y_bounds[0] < -((enclosure_height - 2 * wall) / 2) - 1e-9
                or battery_y_bounds[1] > ((enclosure_height - 2 * wall) / 2) + 1e-9
                or battery_z_bounds[0] < wall - 1e-9
                or battery_z_bounds[1] > enclosure_thickness - wall + 1e-9):
            mechanical_clashes.append("battery envelope exceeds the mechanical enclosure cavity")
    canonical = json.dumps({"scenario": scenario, "route_mm": route,
                            "boxes": [asdict(box) for box in boxes],
                            "parameters": records, "assumptions": assumptions,
                            "mechanical_clashes": mechanical_clashes,
                            "electromagnetic_materials": electromagnetic_materials},
                           sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {
        "scenario": scenario,
        "units": "mm",
        "scenario_contents": {"pcb": include_pcb, "battery": include_battery,
                              "enclosure": include_enclosure, "animal_approximation": include_animal,
                              "finite_ground_plane": True},
        "antenna": {"frequency_hz": frequency, "feed_gap_mm": feed_gap,
                    "feed_gap_definition": "physical air spacing from PCB top to antenna PEC sheet; port spans substrate plus air gap",
                    "trace_width_mm": trace_width,
                    "conductor_model": "zero-thickness PEC sheet approximation",
                    "route_points_mm": route,
                    "route_length_mm": element, "footprint_mm": [meander_width, meander_height],
                    "feed_point_mm": feed_xy, "ground_plane_z_mm": board_z,
                    "trace_z_mm": [trace_z0, trace_z1]},
        "records": records,
        "primitives": [asdict(box) for box in boxes],
        "material_approximations": assumptions,
        "electromagnetic_materials": electromagnetic_materials,
        "mechanical_clashes": mechanical_clashes,
        "geometry_hash_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "geometry_method": "CSXCAD primitives reconstructed from hardware/spec.yaml; no STL imported",
        "source_scenario_names": list(SCENARIOS),
    }


def add_primitives(csx: Any, geometry: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Add RF geometry to a CSXCAD ContinuousStructure instance."""
    metal = csx.AddMetal("riose_assumed_copper")
    for primitive in geometry["primitives"]:
        if primitive["material"] == "PEC_ASSUMED_COPPER":
            metal.AddBox(start=primitive["start_mm"], stop=primitive["stop_mm"], priority=20)
    by_material: dict[str, list[dict[str, Any]]] = {}
    for primitive in geometry["primitives"]:
        if primitive["material"] != "PEC_ASSUMED_COPPER":
            by_material.setdefault(primitive["material"], []).append(primitive)
    for material_name, primitives in sorted(by_material.items()):
        material_record = geometry["electromagnetic_materials"].get(material_name)
        if material_record is None:
            raise GeometryError(f"unknown RF material primitive: {material_name}")
        material = csx.AddMaterial(material_name,
                                   epsilon=material_record["relative_permittivity"],
                                   kappa=material_record["conductivity_s_m"])
        for primitive in primitives:
            material.AddBox(start=primitive["start_mm"], stop=primitive["stop_mm"], priority=5)
    return {"metal": metal, "primitive_count": len(geometry["primitives"]),
            "material_names": sorted({p["material"] for p in geometry["primitives"]})}
