"""Generate an auditable mechanical envelope report from hardware/spec.yaml.

CadQuery is an optional export backend.  The geometry and fit report use only
the Python standard library and remain available when CadQuery is not installed.
All input dimensions retain their source/status and are rejected if marked
MEASURED: MVP 2 has no physical measurements.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - reported by CLI when spec is YAML
    yaml = None


class SpecError(ValueError):
    """The hardware specification is missing or invalid."""


@dataclass(frozen=True)
class Parameter:
    value: float
    unit: str
    source: str
    status: str


@dataclass(frozen=True)
class Box:
    name: str
    x: float
    y: float
    z: float
    width: float
    height: float
    thickness: float
    material: str
    source: str
    status: str

    def bounds(self) -> dict[str, tuple[float, float]]:
        return {
            "x": (self.x - self.width / 2, self.x + self.width / 2),
            "y": (self.y - self.height / 2, self.y + self.height / 2),
            "z": (self.z, self.z + self.thickness),
        }

    def volume_mm3(self) -> float:
        return self.width * self.height * self.thickness


def _node(spec: dict[str, Any], path: str) -> Any:
    current: Any = spec
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _parameter(spec: dict[str, Any], paths: list[str], *, name: str) -> Parameter:
    for path in paths:
        raw = _node(spec, path)
        if raw is None:
            continue
        if not isinstance(raw, dict) or not {"value", "unit", "source", "status"} <= raw.keys():
            raise SpecError(f"{path} must contain value, unit, source and status")
        if (not isinstance(raw["source"], str) or not raw["source"].strip()
                or not isinstance(raw["unit"], str) or not raw["unit"].strip()):
            raise SpecError(f"{path} must have non-empty unit and source provenance")
        try:
            value = float(raw["value"])
        except (TypeError, ValueError) as exc:
            raise SpecError(f"{path}.value must be numeric") from exc
        if not math.isfinite(value) or value <= 0:
            raise SpecError(f"{path}.value must be finite and positive")
        status = str(raw["status"]).upper()
        if status == "MEASURED":
            raise SpecError(f"{path} is MEASURED, which is forbidden in MVP 2")
        if status not in {"DATASHEET", "ASSUMED", "SIMULATED"}:
            raise SpecError(f"{path}.status must be DATASHEET, ASSUMED or SIMULATED")
        return Parameter(value, str(raw["unit"]), str(raw["source"]), status)
    raise SpecError(f"Missing required parameter {name}; expected one of: {', '.join(paths)}")


def _mm(parameter: Parameter, name: str) -> Parameter:
    factors = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "inch": 25.4}
    unit = parameter.unit.strip().lower()
    if unit not in factors:
        raise SpecError(f"{name} must use a length unit (mm, cm, m, in); got {parameter.unit!r}")
    value = parameter.value * factors[unit]
    if not math.isfinite(value) or value <= 0:
        raise SpecError(f"{name} is outside the supported numeric range")
    return Parameter(value, "mm", parameter.source, parameter.status)


def _get_mm(spec: dict[str, Any], path: str, *aliases: str) -> Parameter:
    return _mm(_parameter(spec, [path, *aliases], name=path), path)


def _density(spec: dict[str, Any], key: str, fallback: float) -> tuple[float, str, str, str, list[str]]:
    raw = _node(spec, f"materials.{key}")
    if raw is None:
        label = key.removesuffix("_density_g_cm3")
        return fallback, "g/cm3", "generic engineering estimate; fallback", "ASSUMED", [f"{label} density uses an ASSUMED fallback"]
    p = _parameter(spec, [f"materials.{key}"], name=f"materials.{key}")
    if p.unit.lower() not in {"g/cm3", "g/cm^3", "g/cm³"}:
        raise SpecError(f"materials.{key} must use g/cm3")
    return p.value, p.unit, p.source, p.status, []


def load_spec(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SpecError(f"Hardware spec not found: {path}")
    if yaml is None:
        raise SpecError("PyYAML is required to read hardware/spec.yaml")
    with path.open(encoding="utf-8") as stream:
        spec = yaml.safe_load(stream)
    if not isinstance(spec, dict):
        raise SpecError("hardware/spec.yaml must contain a YAML mapping")
    return spec


def build_report(spec: dict[str, Any]) -> dict[str, Any]:
    """Return fit, envelope, mass and approximate center-of-mass analysis."""
    root = "mechanical"
    ew = _get_mm(spec, f"{root}.enclosure.width_mm", f"{root}.enclosure.width")
    eh = _get_mm(spec, f"{root}.enclosure.height_mm", f"{root}.enclosure.height")
    et = _get_mm(spec, f"{root}.enclosure.thickness_mm", f"{root}.enclosure.thickness")
    wall = _get_mm(spec, f"{root}.enclosure.wall_thickness_mm")
    pw = _get_mm(spec, f"{root}.pcb.width_mm", f"{root}.pcb.width")
    ph = _get_mm(spec, f"{root}.pcb.height_mm", f"{root}.pcb.height")
    pt = _get_mm(spec, f"{root}.pcb.thickness_mm", f"{root}.pcb.thickness")
    bd = _get_mm(spec, f"{root}.battery.diameter_mm", f"{root}.battery.width_mm")
    bl = _get_mm(spec, f"{root}.battery.length_mm", f"{root}.battery.height_mm")
    hole_d = _get_mm(spec, f"{root}.enclosure.mounting_hole_diameter_mm")
    aw = _get_mm(spec, f"{root}.antenna.width_mm")
    ah = _get_mm(spec, f"{root}.antenna.height_mm")
    at = _get_mm(spec, f"{root}.antenna.thickness_mm")
    ak = _get_mm(spec, f"{root}.antenna.keepout_mm")
    clearance = _get_mm(spec, f"{root}.minimum_clearance_mm")
    dims: dict[str, tuple[Parameter, Parameter, Parameter]] = {
        "mcu": tuple(_get_mm(spec, f"{root}.components.mcu.{axis}_mm") for axis in ("width", "height", "thickness")),
        "radio": tuple(_get_mm(spec, f"{root}.components.radio.{axis}_mm") for axis in ("width", "height", "thickness")),
        "imu": tuple(_get_mm(spec, f"{root}.components.imu.{axis}_mm") for axis in ("width", "height", "thickness")),
    }
    for label, p in (("wall thickness", wall),):
        if p.value * 2 >= min(ew.value, eh.value, et.value):
            raise SpecError(f"Enclosure {label} leaves no internal cavity")

    warnings: list[str] = [
        "Bounding-box placement and mass properties are estimates; validate clearances and retention in a reviewed design.",
        "Battery cylinder is approximated by a rectangular envelope with length along X.",
        "PCB is placed toward the left cavity edge to reserve the assumed right-side battery location; no PCB origin is specified.",
        "Antenna keepout may extend beyond the PCB edge into empty cavity; mounted-package intersections remain fit blockers.",
        "Mounting hole position is assumed at the upper end of the enclosure; review the retention interface.",
    ]
    den_shell = _density(spec, "enclosure_density_g_cm3", 1.2)
    den_pcb = _density(spec, "pcb_density_g_cm3", 1.85)
    den_batt = _density(spec, "battery_density_g_cm3", 2.0)
    den_parts = _density(spec, "component_density_g_cm3", 2.0)
    for density in (den_shell, den_pcb, den_batt, den_parts):
        warnings.extend(density[4])

    # Body represented as a hollow rectangular shell. Other parts are simple
    # envelopes; PCB-mounted component mass is not subtracted from the PCB.
    inner_w, inner_h, inner_t = ew.value - 2 * wall.value, eh.value - 2 * wall.value, et.value - 2 * wall.value
    # Keep the left-aligned packing heuristic, but constrain its placement so
    # the antenna keepout does not cross the cavity wall merely because the
    # board was anchored flush to the left. The hardware spec does not declare
    # an origin, so this remains an explicit placement estimate.
    pcb_left_aligned_x = -inner_w / 2 + clearance.value + pw.value / 2
    antenna_keepout_half_width = aw.value / 2 + ak.value
    pcb_keepout_clearance_x = -inner_w / 2 + antenna_keepout_half_width + clearance.value
    pcb_x = max(pcb_left_aligned_x, pcb_keepout_clearance_x)
    boxes: list[Box] = [
        Box("enclosure", 0, 0, 0, ew.value, eh.value, et.value, "enclosure", ew.source, ew.status),
        Box("pcb", pcb_x, 0, wall.value, pw.value, ph.value, pt.value, "pcb", pw.source, pw.status),
        # Side-by-side with PCB; an overlap means the selected envelopes do not fit.
        Box("battery", inner_w / 2 - clearance.value - bl.value / 2, 0, wall.value, bl.value, bd.value, bd.value, "battery", bl.source, bl.status),
    ]
    hole_y = eh.value / 2 - wall.value - hole_d.value / 2

    board = boxes[1]
    cursor_x = board.x - pw.value / 2
    cursor_y = board.y - ph.value / 2
    row_height = 0.0
    gap = clearance.value
    warnings.append("Component placement uses the spec minimum clearance; it is ASSUMED until design review.")
    for name in ("mcu", "radio", "imu"):
        a, b, c = dims[name]
        if cursor_x + a.value > board.x + pw.value / 2:
            cursor_x = board.x - pw.value / 2
            cursor_y += row_height + gap
            row_height = 0.0
        center_x, center_y = cursor_x + a.value / 2, cursor_y + b.value / 2
        z = wall.value + pt.value
        boxes.append(Box(name, center_x, center_y, z, a.value, b.value, c.value, "component", a.source, a.status))
        cursor_x += a.value + gap
        row_height = max(row_height, b.value)
    antenna = Box("antenna", board.x, board.y + ph.value / 2 - ah.value / 2 - ak.value, wall.value + pt.value,
                  aw.value, ah.value, at.value, "antenna", aw.source, aw.status)
    antenna_keepout = Box("antenna_keepout", antenna.x, antenna.y, antenna.z,
                          aw.value + 2 * ak.value, ah.value + 2 * ak.value,
                          at.value + 2 * ak.value, "keepout", ak.source, ak.status)
    boxes.extend((antenna, antenna_keepout))

    def inside(box: Box) -> bool:
        bounds = box.bounds()
        return (bounds["x"][0] >= -inner_w / 2 - 1e-9 and bounds["x"][1] <= inner_w / 2 + 1e-9
                and bounds["y"][0] >= -inner_h / 2 - 1e-9 and bounds["y"][1] <= inner_h / 2 + 1e-9
                and bounds["z"][0] >= wall.value - 1e-9 and bounds["z"][1] <= et.value - wall.value + 1e-9)

    issues: list[str] = []
    if hole_d.value <= 0 or hole_y + hole_d.value / 2 > eh.value / 2 + 1e-9:
        issues.append("mounting hole is outside the enclosure envelope")
    if pw.value > inner_w or ph.value > inner_h or pt.value > inner_t:
        issues.append("PCB envelope exceeds enclosure cavity")
    for box in boxes[1:]:
        if not inside(box):
            issues.append(f"{box.name} envelope exceeds enclosure cavity")
    for box in boxes[3:6]:
        b = box.bounds()
        if (b["x"][0] < board.x - board.width / 2 - 1e-9 or b["x"][1] > board.x + board.width / 2 + 1e-9
                or b["y"][0] < board.y - board.height / 2 - 1e-9 or b["y"][1] > board.y + board.height / 2 + 1e-9):
            issues.append(f"{box.name} package exceeds PCB envelope")
    ab = antenna.bounds()
    if (ab["x"][0] < board.x - board.width / 2 - 1e-9 or ab["x"][1] > board.x + board.width / 2 + 1e-9
            or ab["y"][0] < board.y - board.height / 2 - 1e-9 or ab["y"][1] > board.y + board.height / 2 + 1e-9):
        issues.append("antenna footprint exceeds PCB envelope")
    for box in (boxes[2], *boxes[3:6]):
        distance = _box_distance(box, antenna_keepout)
        if _overlap(box, antenna_keepout):
            issues.append(f"{box.name} envelope violates antenna keepout")
        elif distance + 1e-9 < clearance.value:
            issues.append(
                f"minimum antenna-keepout clearance violated: {box.name} "
                f"({distance:.3f} mm < {clearance.value:.3f} mm)"
            )
    # Check solid part overlaps, with PCB/component contact intentionally allowed.
    physical = [box for box in boxes if box.name not in {"enclosure", "antenna_keepout"}]
    wall_clearances = {box.name: _wall_clearances(box, inner_w, inner_h, et.value - wall.value) for box in physical}
    for name, distances in wall_clearances.items():
        minimum = min(distances.values())
        if minimum + 1e-9 < clearance.value:
            issues.append(
                f"minimum enclosure-wall clearance violated: {name} "
                f"({minimum:.3f} mm < {clearance.value:.3f} mm)"
            )
    for i, first in enumerate(physical):
        for second in physical[i + 1:]:
            if _overlap(first, second):
                issues.append(f"unexpected envelope overlap: {first.name} / {second.name}")
            elif not _intentional_contact(first.name, second.name):
                distance = _box_distance(first, second)
                if distance + 1e-9 < clearance.value:
                    issues.append(
                        f"minimum clearance violated: {first.name} / {second.name} "
                        f"({distance:.3f} mm < {clearance.value:.3f} mm)"
                    )
    if not (ew.value > 0 and eh.value > 0 and et.value > 0):
        issues.append("invalid external envelope")

    densities = {"enclosure": den_shell[0], "pcb": den_pcb[0], "battery": den_batt[0], "component": den_parts[0]}
    # Shell volume is outer minus inner cavity. Components contribute their full
    # box volumes; this deliberately overestimates solid component packaging.
    enclosure_before_hole = ew.value * eh.value * et.value - inner_w * inner_h * inner_t
    # The mounting hole is tangent to the inner side wall by construction and
    # removes material only from the two enclosure skins along the z axis.
    hole_volume = math.pi * (hole_d.value / 2) ** 2 * (2 * wall.value)
    volumes = {
        "enclosure": enclosure_before_hole - hole_volume,
        "pcb": boxes[1].volume_mm3(),
        "battery": math.pi * (bd.value / 2) ** 2 * bl.value,
    }
    for part in (*boxes[3:6], antenna):
        volumes["components"] = volumes.get("components", 0.0) + part.volume_mm3()
    masses = {
        "enclosure": volumes["enclosure"] * densities["enclosure"] / 1000,
        "pcb": volumes["pcb"] * densities["pcb"] / 1000,
        "battery": volumes["battery"] * densities["battery"] / 1000,
        "components": volumes.get("components", 0.0) * densities["component"] / 1000,
    }
    mass_total = sum(masses.values())
    # Approximate body and cylinder centroids; remaining parts use bbox centers.
    enclosure_mass_before_hole = enclosure_before_hole * densities["enclosure"] / 1000
    hole_mass = hole_volume * densities["enclosure"] / 1000
    weighted = [(enclosure_mass_before_hole, 0, 0, et.value / 2),
                (-hole_mass, 0, hole_y, et.value / 2),
                (masses["pcb"], board.x, board.y, board.z + pt.value / 2),
                (masses["battery"], boxes[2].x, boxes[2].y, boxes[2].z + bd.value / 2)]
    for box in (*boxes[3:6], antenna):
        m = box.volume_mm3() * densities["component"] / 1000
        weighted.append((m, box.x, box.y, box.z + box.thickness / 2))
    cg = {axis: sum(m * coords[i] for m, *coords in weighted) / mass_total for i, axis in enumerate(("x_mm", "y_mm", "z_mm"))}

    parameter_inputs = {
        "mechanical.enclosure.width_mm": ew, "mechanical.enclosure.height_mm": eh,
        "mechanical.enclosure.thickness_mm": et, "mechanical.enclosure.wall_thickness_mm": wall,
        "mechanical.enclosure.mounting_hole_diameter_mm": hole_d,
        "mechanical.pcb.width_mm": pw, "mechanical.pcb.height_mm": ph, "mechanical.pcb.thickness_mm": pt,
        "mechanical.battery.diameter_mm": bd, "mechanical.battery.length_mm": bl,
        "mechanical.antenna.width_mm": aw, "mechanical.antenna.height_mm": ah,
        "mechanical.antenna.thickness_mm": at, "mechanical.antenna.keepout_mm": ak,
        "mechanical.minimum_clearance_mm": clearance,
    }
    for name, group in dims.items():
        for axis, parameter in zip(("width_mm", "height_mm", "thickness_mm"), group):
            parameter_inputs[f"mechanical.components.{name}.{axis}"] = parameter
    statuses = {p.status for p in parameter_inputs.values()}
    if "MEASURED" in statuses:
        raise SpecError("MVP 2 mechanical inputs cannot have status MEASURED")
    clearance_report = _clearances(physical)
    return {
        "schema_version": "1.0",
        "analysis": "SIMULATED_GEOMETRY_ESTIMATE",
        "gate": "NOT_READY_FOR_PHYSICAL_PROTOTYPE" if issues else "CONDITIONALLY_READY_PENDING_THRESHOLD_APPROVAL",
        "gate_note": "Mechanical dimensions, antenna and fit require explicit review before READY_FOR_PHYSICAL_PROTOTYPE.",
        "specification_statuses": sorted(statuses),
        "input_parameters": {name: asdict(parameter) for name, parameter in parameter_inputs.items()},
        "envelope_mm": {"width": ew.value, "height": eh.value, "thickness": et.value},
        "internal_cavity_mm": {"width": inner_w, "height": inner_h, "thickness": inner_t},
        "parts": [asdict(box) | {"volume_mm3": box.volume_mm3(), "bounds_mm": {k: list(v) for k, v in box.bounds().items()}} for box in boxes],
        "fit": {"fits": not issues, "issues": issues},
        "clearances_mm": clearance_report,
        "enclosure_wall_clearances_mm": wall_clearances,
        "volume_mm3": volumes,
        "mass_estimate_g": {"parts": masses, "total": mass_total, "status": "ASSUMED"},
        "mass_by_material_class_g": {
            "enclosure": masses["enclosure"],
            "pcb": masses["pcb"],
            "battery": masses["battery"],
            "components": masses["components"],
        },
        "center_of_mass_mm": cg,
        "materials": {
            "enclosure": {"density_g_cm3": den_shell[0], "source": den_shell[2], "status": den_shell[3]},
            "pcb": {"density_g_cm3": den_pcb[0], "source": den_pcb[2], "status": den_pcb[3]},
            "battery": {"density_g_cm3": den_batt[0], "source": den_batt[2], "status": den_batt[3]},
            "component": {"density_g_cm3": den_parts[0], "source": den_parts[2], "status": den_parts[3]},
        },
        "mounting_hole": {"diameter_mm": hole_d.value, "center_mm": {"x": 0.0, "y": hole_y}, "axis": "z", "source": hole_d.source, "status": hole_d.status},
        "warnings": sorted(set(warnings)),
        "cadquery_available": _cadquery_available(),
        "provenance": {
            "analysis": "SIMULATED",
            "geometry_inputs": {name: {"source": p.source, "status": p.status} for name, p in parameter_inputs.items()},
            "mass_estimate": "ASSUMED",
            "physical_validation": "NOT_PERFORMED",
        },
    }


def _overlap(a: Box, b: Box) -> bool:
    ab, bb = a.bounds(), b.bounds()
    return all(min(ab[axis][1], bb[axis][1]) - max(ab[axis][0], bb[axis][0]) > 1e-9 for axis in ("x", "y", "z"))


def _clearances(boxes: list[Box]) -> dict[str, float]:
    """Report axis-aligned envelope distances; intended PCB contacts are zero."""
    result: dict[str, float] = {}
    for index, first in enumerate(boxes):
        for second in boxes[index + 1:]:
            result[f"{first.name}/{second.name}"] = _box_distance(first, second)
    return result


def _box_distance(first: Box, second: Box) -> float:
    a, b = first.bounds(), second.bounds()
    gaps = [max(0.0, b[axis][0] - a[axis][1], a[axis][0] - b[axis][1]) for axis in ("x", "y", "z")]
    return math.sqrt(sum(gap * gap for gap in gaps))


def _wall_clearances(box: Box, inner_w: float, inner_h: float, ceiling_z: float) -> dict[str, float]:
    bounds = box.bounds()
    return {
        "left": bounds["x"][0] + inner_w / 2,
        "right": inner_w / 2 - bounds["x"][1],
        "front": bounds["y"][0] + inner_h / 2,
        "rear": inner_h / 2 - bounds["y"][1],
        # PCB, battery and board-mounted parts intentionally rest on the floor.
        "ceiling": ceiling_z - bounds["z"][1],
    }


def _intentional_contact(first: str, second: str) -> bool:
    names = {first, second}
    return "pcb" in names and bool(names & {"mcu", "radio", "imu", "antenna"})


def apply_overrides(spec: dict[str, Any], overrides: list[str]) -> dict[str, Any]:
    """Apply numeric CLI parameter overrides while recording simulated provenance."""
    result = copy.deepcopy(spec)
    for override in overrides:
        path, separator, value_text = override.partition("=")
        if not separator or not path or not value_text:
            raise SpecError(f"Invalid --set {override!r}; expected dotted.path=value")
        raw = _node(result, path)
        if not isinstance(raw, dict) or "value" not in raw:
            raise SpecError(f"--set target {path!r} is not an existing spec parameter")
        try:
            value = float(value_text)
        except ValueError as exc:
            raise SpecError(f"--set value for {path!r} must be numeric") from exc
        if not math.isfinite(value) or value <= 0:
            raise SpecError(f"--set value for {path!r} must be finite and positive")
        raw["value"] = value
        raw["source"] = f"CLI override: --set {path}={value_text}"
        raw["status"] = "SIMULATED"
    return result


def _cadquery_available() -> bool:
    try:
        import cadquery  # noqa: F401
        return True
    except ImportError:
        return False


def export_cad(report: dict[str, Any], step_output: Path, stl_output: Path | None = None) -> None:
    outputs = [step_output, step_output.with_suffix(step_output.suffix + ".provenance.json")]
    if stl_output is not None:
        outputs.extend((stl_output, stl_output.with_suffix(stl_output.suffix + ".provenance.json")))
    # A refused or interrupted export must not leave artifacts from an older run
    # that could be mistaken for the result of this report.
    for output in outputs:
        output.unlink(missing_ok=True)
    if not report["fit"]["fits"]:
        raise SpecError("CAD export blocked because the report contains fit/clash failures")
    try:
        import cadquery as cq
    except ImportError as exc:
        raise SpecError("CadQuery unavailable; install the optional CadQuery runtime to export STEP") from exc
    assembly = cq.Assembly(name="riose_ear_tag_assumed")
    shapes = []
    for part in report["parts"]:
        if part["name"] in {"enclosure", "antenna_keepout"}:
            continue
        if part["name"] == "battery":
            shape = cq.Workplane("YZ").circle(part["height"] / 2).extrude(part["width"])
            shape = shape.translate((part["x"] - part["width"] / 2, part["y"], part["z"] + part["thickness"] / 2))
        else:
            shape = cq.Workplane("XY").box(part["width"], part["height"], part["thickness"], centered=(True, True, False))
            shape = shape.translate((part["x"], part["y"], part["z"]))
        assembly.add(shape, name=part["name"])
        shapes.append(shape.val())
    # Hollow open-top envelope keeps the first export simple and editable.
    w, h, t = (report["envelope_mm"][key] for key in ("width", "height", "thickness"))
    cavity = report["internal_cavity_mm"]
    # CadQuery shell/export is generated as a difference of outer/inner boxes.
    outer = cq.Workplane("XY").box(w, h, t, centered=(True, True, False))
    inner = cq.Workplane("XY").box(cavity["width"], cavity["height"], cavity["thickness"], centered=(True, True, False)).translate((0, 0, (t-cavity["thickness"])/2))
    hole = report["mounting_hole"]
    cutter = cq.Workplane("XY").circle(hole["diameter_mm"] / 2).extrude(t + 2).translate((hole["center_mm"]["x"], hole["center_mm"]["y"], -1))
    shell = outer.cut(inner).cut(cutter)
    assembly.add(shell, name="enclosure_shell")
    shapes.append(shell.val())
    provenance = {
        "analysis": "SIMULATED",
        "physical_validation": "NOT_PERFORMED",
        "specification_statuses": report["specification_statuses"],
        "inputs": report["input_parameters"],
        "materials": report["materials"],
        "mass_estimate_g": report["mass_estimate_g"],
    }
    try:
        step_output.parent.mkdir(parents=True, exist_ok=True)
        assembly.export(str(step_output), exportType="STEP")
        step_output.with_suffix(step_output.suffix + ".provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
        if stl_output is not None:
            stl_output.parent.mkdir(parents=True, exist_ok=True)
            cq.exporters.export(cq.Compound.makeCompound(shapes), str(stl_output), exportType="STL")
            stl_output.with_suffix(stl_output.suffix + ".provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    except Exception:
        for output in outputs:
            try:
                output.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=Path("hardware/spec.yaml"))
    parser.add_argument("--output", type=Path, default=Path("results/mvp2/mechanical/geometry.json"))
    parser.add_argument("--step", type=Path, help="Optional STEP export (requires CadQuery)")
    parser.add_argument("--stl", type=Path, help="Optional STL export; with --step both formats use the same shapes")
    parser.add_argument("--set", dest="overrides", action="append", default=[], metavar="PATH=VALUE", help="Override a numeric spec value (repeatable); provenance is marked SIMULATED")
    args = parser.parse_args(argv)
    try:
        step_path = args.step or (args.stl.with_suffix(".step") if args.stl else None)
        stl_path = args.stl or (step_path.with_suffix(".stl") if step_path else None)
        planned_outputs = [args.output]
        if step_path and stl_path:
            planned_outputs.extend((step_path, stl_path,
                                    step_path.with_suffix(step_path.suffix + ".provenance.json"),
                                    stl_path.with_suffix(stl_path.suffix + ".provenance.json")))
        resolved_outputs = [path.expanduser().resolve() for path in planned_outputs]
        if len(resolved_outputs) != len(set(resolved_outputs)):
            raise SpecError("Report, CAD and provenance output paths must be distinct")
        input_path = args.spec.expanduser().resolve()
        if input_path in resolved_outputs:
            raise SpecError("Output paths must not overwrite the input hardware specification")
        report = build_report(apply_overrides(load_spec(args.spec), args.overrides))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if args.step or args.stl:
            assert step_path is not None and stl_path is not None
            export_cad(report, step_path, stl_path)
    except (SpecError, OSError) as exc:
        print(f"mechanical model error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"report": str(args.output), "gate": report["gate"], "fits": report["fit"]["fits"], "cadquery_available": report["cadquery_available"]}))
    # Preserve the report for diagnosis while failing the CLI on fit blockers.
    return 0 if report["fit"]["fits"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
