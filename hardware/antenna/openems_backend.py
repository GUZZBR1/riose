"""Native, headless CSXCAD/openEMS execution path for the antenna model."""
from __future__ import annotations

import csv
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from .geometry import GeometryError, add_primitives
from .metrics import parse_pattern_rows, parse_s11_rows, power_metrics, summarize_s11, vswr_from_s11_db

C0_M_S = 299_792_458.0
EPS0_F_M = 8.8541878128e-12
MAX_TIME_STEPS = 300_000
END_CRITERIA = 1e-5
SOLVER_SETUP_VERSION = 9
FREQUENCY_MIN_RATIO = 0.65
FREQUENCY_MAX_RATIO = 2.5
EXCITATION_MIN_RATIO = 0.4
EXCITATION_MAX_RATIO = 2.8
FREQUENCY_SAMPLE_COUNT = 371
MAX_S11_ROUNDOFF_DB = 0.05
MESH_BASE_MAX_CELL_WAVELENGTH_FRACTION = 1 / 20
MESH_REFINEMENT_COARSE_FACTOR = 1.5
EXCITATION_CONFIG = {"type": "Gaussian",
                     "center_frequency_fraction": (EXCITATION_MIN_RATIO + EXCITATION_MAX_RATIO) / 2,
                     "band_min_frequency_fraction": EXCITATION_MIN_RATIO,
                     "band_max_frequency_fraction": EXCITATION_MAX_RATIO,
                     "cutoff_frequency_fraction": (EXCITATION_MAX_RATIO - EXCITATION_MIN_RATIO) / 2}
PORT_CONFIG = {"type": "z_directed_lumped_port",
               "cross_section": "trace_width_perpendicular_to_feed_tangent",
               "reference_plane": "stop_at_ground_plane"}


def solver_executable() -> str | None:
    """Find the native solver using explicit env, activated toolchain, or PATH."""
    configured = os.environ.get("RIOSE_OPENEMS_EXECUTABLE")
    if configured:
        return configured if Path(configured).is_file() else None
    prefix = os.environ.get("OPENEMS_INSTALL_PATH")
    if prefix:
        for name in ("openEMS", "openEMS.exe"):
            candidate = Path(prefix) / "bin" / name
            if candidate.is_file():
                return str(candidate)
    return shutil.which("openEMS") or shutil.which("openEMS.exe")


def runtime_status() -> dict[str, Any]:
    try:
        csxcad_available = importlib.util.find_spec("CSXCAD") is not None
        openems_available = importlib.util.find_spec("openEMS") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        csxcad_available = openems_available = False
    executable = solver_executable()
    installed = csxcad_available and openems_available and executable is not None
    version = None
    version_source = None
    if installed:
        try:
            proc = subprocess.run([executable, "--help"], capture_output=True, text=True,
                                  timeout=10, check=False)
            banner = "\n".join((proc.stdout, proc.stderr))
            match = re.search(r"openEMS[^\n]*?version\s+v?([\w.+-]+)", banner, re.I)
            if match:
                version, version_source = match.group(1), "openEMS executable banner"
            if not version:
                version = importlib.metadata.version("openEMS")
                version_source = "Python distribution metadata"
        except (OSError, subprocess.TimeoutExpired, importlib.metadata.PackageNotFoundError):
            pass
    return {
        "available": bool(installed and version),
        "bindings": {"openEMS": openems_available, "CSXCAD": csxcad_available},
        "executable": executable,
        "solver_version": version,
        "version_source": version_source,
        "reason": None if installed and version else "openEMS executable, Python bindings, or verifiable version is unavailable",
    }


def parse_run_statistics(lines: Iterable[str], *, max_time_steps: int = MAX_TIME_STEPS,
                         end_criteria: float = END_CRITERIA) -> dict[str, Any]:
    """Read openEMS ``dump_statistics`` rows and prove energy convergence.

    openEMS records time, timestep, speed and energy. The residual is computed
    against the largest recorded energy. Reaching the timestep cap, missing
    rows, malformed values, or a residual above EndCriteria is non-converged.
    """
    observations: list[dict[str, float]] = []
    for line in lines:
        tokens = [item for item in re.split(r"[,;\s]+", line.strip()) if item]
        values: list[float] = []
        for token in tokens:
            try:
                value = float(token)
            except ValueError:
                continue
            if math.isfinite(value):
                values.append(value)
        if len(values) < 4:
            continue
        # DumpRunStatistics writes (time, timestep, speed, energy).
        time_s, timestep, speed, energy = values[:4]
        if timestep < 0 or not math.isclose(timestep, round(timestep), abs_tol=1e-6) or energy < 0:
            continue
        observations.append({"time_s": time_s, "time_step": timestep,
                             "speed_mcells_s": speed, "energy": energy})
    if not observations:
        return {"converged": False, "status": "NON_CONVERGED",
                "reason": "openEMS run statistics contain no parseable time/step/speed/energy rows",
                "sample_count": 0}
    final = observations[-1]
    peak = max(item["energy"] for item in observations)
    residual = final["energy"] / peak if peak > 0 else math.inf
    converged = (final["time_step"] < max_time_steps and math.isfinite(residual)
                 and residual <= end_criteria)
    return {
        "converged": converged,
        "status": "COMPLETED" if converged else "NON_CONVERGED",
        "reason": None if converged else "energy residual/cap does not prove convergence",
        "sample_count": len(observations),
        "final_time_s": final["time_s"],
        "final_time_step": int(final["time_step"]),
        "max_time_steps": max_time_steps,
        "final_energy": final["energy"],
        "peak_recorded_energy": peak,
        "energy_residual_fraction": residual,
        "end_criteria": end_criteria,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty result artifact: {path.name}")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _normalize_s11_magnitude_db(values: Any) -> tuple[Any, bool]:
    """Clamp only tiny passive-limit roundoff from openEMS port transforms."""
    import numpy as np

    s11_db = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(s11_db)):
        raise ValueError("openEMS returned non-finite S11 values")
    maximum = float(np.max(s11_db))
    if maximum > MAX_S11_ROUNDOFF_DB:
        raise ValueError(f"openEMS S11 exceeds the passive limit by {maximum:.6g} dB")
    return np.minimum(s11_db, 0.0), maximum > 0.0


def _reactance_resonance(frequencies: Any, impedance: Any,
                         target_frequency_hz: float) -> tuple[float, complex]:
    """Interpolate an input-reactance zero crossing nearest the target band."""
    import numpy as np

    freq = np.asarray(frequencies, dtype=float)
    zin = np.asarray(impedance, dtype=complex)
    if freq.ndim != 1 or zin.ndim != 1 or len(freq) != len(zin) or len(freq) < 2:
        raise ValueError("frequency and impedance arrays must be aligned one-dimensional samples")
    if (not np.all(np.isfinite(freq)) or not np.all(np.isfinite(zin.real))
            or not np.all(np.isfinite(zin.imag)) or np.any(np.diff(freq) <= 0)):
        raise ValueError("frequency and impedance samples must be finite and ordered")
    candidates: list[tuple[float, float, complex]] = []
    for index in range(len(freq) - 1):
        left, right = float(zin[index].imag), float(zin[index + 1].imag)
        if left == 0.0:
            fraction = 0.0
        elif right == 0.0:
            fraction = 1.0
        elif left * right < 0.0:
            fraction = -left / (right - left)
        else:
            continue
        crossing_frequency = float(freq[index] + fraction * (freq[index + 1] - freq[index]))
        resistance = float(zin[index].real + fraction * (zin[index + 1].real - zin[index].real))
        candidates.append((abs(crossing_frequency - target_frequency_hz), crossing_frequency,
                           complex(resistance, 0.0)))
    if not candidates:
        raise ValueError("input reactance does not cross zero inside the configured frequency sweep")
    _, crossing_frequency, crossing_impedance = min(candidates, key=lambda item: item[0])
    return crossing_frequency, crossing_impedance


@contextmanager
def _working_directory(path: Path):
    previous = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(previous)


def _mesh_metadata(mesh: Any, max_res_mm: float) -> dict[str, Any]:
    axes: dict[str, list[float]] = {}
    for axis in "xyz":
        lines = [float(value) for value in mesh.GetLines(axis)]
        if len(lines) < 2 or not all(math.isfinite(value) for value in lines):
            raise GeometryError(f"CSXCAD {axis} mesh is invalid")
        deltas = [b - a for a, b in zip(lines, lines[1:])]
        if any(delta <= 0 for delta in deltas):
            raise GeometryError(f"CSXCAD {axis} mesh lines are not strictly increasing")
        axes[axis] = lines
    packed = json.dumps(axes, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {
        "unit": "mm",
        "cell_counts": {axis: len(lines) - 1 for axis, lines in axes.items()},
        "cell_count_total": math.prod(len(lines) - 1 for lines in axes.values()),
        "min_cell_mm": {axis: min(b - a for a, b in zip(lines, lines[1:]))
                        for axis, lines in axes.items()},
        "max_cell_mm": {axis: max(b - a for a, b in zip(lines, lines[1:]))
                        for axis, lines in axes.items()},
        "max_res_mm": max_res_mm,
        "mesh_hash_sha256": hashlib.sha256(packed.encode("utf-8")).hexdigest(),
        "lines": axes,
    }


def simulate_scenario(spec: dict[str, Any], spec_hash: str, geometry: dict[str, Any],
                      output_dir: Path, overrides: dict[str, Any] | None = None,
                      *, input_hash: str | None = None,
                      mesh_resolution_factor: float = 1.0) -> dict[str, Any]:
    """Run one solver case and return only solver-derived metrics/evidence."""
    overrides = overrides or {}
    if (isinstance(mesh_resolution_factor, bool)
            or not isinstance(mesh_resolution_factor, (int, float))
            or not math.isfinite(float(mesh_resolution_factor))
            or mesh_resolution_factor <= 0):
        raise ValueError("mesh_resolution_factor must be positive and finite")
    mesh_resolution_factor = float(mesh_resolution_factor)
    config = {
        "solver_setup_version": SOLVER_SETUP_VERSION,
        "geometry_hash_sha256": geometry["geometry_hash_sha256"],
        "scenario": geometry["scenario"], "frequency_hz": geometry["antenna"]["frequency_hz"],
        "max_time_steps": MAX_TIME_STEPS, "end_criteria": END_CRITERIA,
        "max_s11_roundoff_db": MAX_S11_ROUNDOFF_DB,
        "frequency_samples": FREQUENCY_SAMPLE_COUNT, "boundary": "PML_8 on all six faces",
        "resonance_definition": "input_reactance_zero_crossing_nearest_target",
        "mesh_rule": "lambda/20 fine reference with explicit coarse/fine factor and 1.4 smoothing ratio",
        "mesh_resolution_factor": mesh_resolution_factor,
        "excitation": EXCITATION_CONFIG, "port": PORT_CONFIG,
        "overrides": overrides,
    }
    requested_hash = expected_input_hash(spec_hash, geometry, overrides,
                                         mesh_resolution_factor=mesh_resolution_factor)
    if input_hash is not None and input_hash != requested_hash:
        raise ValueError("input_hash does not match geometry and solver configuration")
    input_hash = requested_hash
    evidence_base = {"input_hash_sha256": input_hash,
                     "spec_hash_sha256": spec_hash,
                     "geometry_hash_sha256": geometry["geometry_hash_sha256"],
                     "geometry_method": geometry["geometry_method"],
                     "materials": geometry["electromagnetic_materials"],
                     "assumptions": geometry["material_approximations"],
                     "convergence": {"status": "NOT_RUN", "converged": False}}
    if geometry.get("mechanical_clashes"):
        return {"status": "INVALID_INPUT", "detail": "; ".join(geometry["mechanical_clashes"]),
                "metrics": None, "evidence": evidence_base}
    runtime = runtime_status()
    if not runtime["available"]:
        return {"status": "NOT_AVAILABLE", "detail": runtime["reason"],
                "metrics": None, "evidence": {**evidence_base, "runtime": runtime}}

    import numpy as np
    CSXCAD = importlib.import_module("CSXCAD")
    openems_package = importlib.import_module("openEMS")
    sim_dir = (output_dir.resolve() / "simulations" / geometry["scenario"] / input_hash[:16]).resolve()
    sim_dir.mkdir(parents=True, exist_ok=True)
    csx = CSXCAD.ContinuousStructure()
    fdtd = openems_package.openEMS(NrTS=MAX_TIME_STEPS, EndCriteria=END_CRITERIA)
    frequency_hz = geometry["antenna"]["frequency_hz"]
    excitation_center = frequency_hz * (EXCITATION_MIN_RATIO + EXCITATION_MAX_RATIO) / 2
    excitation_cutoff = frequency_hz * (EXCITATION_MAX_RATIO - EXCITATION_MIN_RATIO) / 2
    fdtd.SetGaussExcite(excitation_center, excitation_cutoff)
    fdtd.SetBoundaryCond(["PML_8"] * 6)
    fdtd.SetCSX(csx)
    mesh = csx.GetGrid()
    mesh.SetDeltaUnit(1e-3)
    add_primitives(csx, geometry, spec)

    frequency_start = FREQUENCY_MIN_RATIO * frequency_hz
    frequency_stop = FREQUENCY_MAX_RATIO * frequency_hz
    frequencies = np.linspace(frequency_start, frequency_stop, FREQUENCY_SAMPLE_COUNT)
    fine_grid_wavelength_mm = C0_M_S / frequency_stop * 1000
    domain_wavelength_mm = C0_M_S / frequency_start * 1000
    max_res_mm = (fine_grid_wavelength_mm * MESH_BASE_MAX_CELL_WAVELENGTH_FRACTION
                  * mesh_resolution_factor)
    primitive_boxes = geometry["primitives"]
    x_edges = [-0.5 * domain_wavelength_mm, 0.5 * domain_wavelength_mm]
    y_edges = [-0.5 * domain_wavelength_mm, 0.5 * domain_wavelength_mm]
    z_edges = [-domain_wavelength_mm / 3, domain_wavelength_mm / 2]
    for primitive in primitive_boxes:
        for axis, target in enumerate((x_edges, y_edges, z_edges)):
            target.extend((primitive["start_mm"][axis], primitive["stop_mm"][axis]))
    feed_x, feed_y = geometry["antenna"]["feed_point_mm"]
    trace_width = geometry["antenna"]["trace_width_mm"]
    # Keep the lumped port cross-section edges explicit in the mesh. Using
    # only the smaller physical feed gap lets mesh smoothing collapse the
    # snapped port's XY extent to a zero-area cell.
    x_edges.append(feed_x)
    y_edges.extend((feed_y - trace_width / 2, feed_y, feed_y + trace_width / 2))
    z_edges.extend((geometry["antenna"]["ground_plane_z_mm"], geometry["antenna"]["trace_z_mm"][0],
                    geometry["antenna"]["trace_z_mm"][1]))
    for axis, lines in zip("xyz", (x_edges, y_edges, z_edges)):
        mesh.SetLines(axis, sorted(set(float(value) for value in lines)))
        mesh.SmoothMeshLines(axis, max_res_mm, 1.4)
    mesh_metadata = _mesh_metadata(mesh, max_res_mm)
    if mesh_metadata["cell_count_total"] <= 0:
        raise GeometryError("CSXCAD returned an empty mesh")

    all_starts = [p["start_mm"] for p in primitive_boxes]
    all_stops = [p["stop_mm"] for p in primitive_boxes]
    air_padding_mm = domain_wavelength_mm / 6
    nf_start = [min(point[axis] for point in all_starts) - air_padding_mm for axis in range(3)]
    nf_stop = [max(point[axis] for point in all_stops) + air_padding_mm for axis in range(3)]
    nf2ff = fdtd.CreateNF2FFBox("riose_nf2ff", nf_start, nf_stop)
    port = fdtd.AddLumpedPort(1, 50.0,
                              [feed_x, feed_y - trace_width / 2,
                               geometry["antenna"]["trace_z_mm"][1]],
                              [feed_x, feed_y + trace_width / 2,
                               geometry["antenna"]["ground_plane_z_mm"]],
                              "z", 1.0, priority=30, edges2grid="xy")
    xml_path = sim_dir / "antenna.xml"
    fdtd.Write2XML(str(xml_path))
    if not xml_path.is_file():
        return {"status": "FAILED", "detail": "openEMS could not serialize CSXCAD/FDTD setup",
                "metrics": None, "evidence": {**evidence_base, "runtime": runtime,
                                               "mesh": mesh_metadata}}
    geometry_path = sim_dir / "geometry.json"
    geometry_path.write_text(json.dumps(geometry, indent=2, sort_keys=True, allow_nan=False) + "\n",
                             encoding="utf-8")
    run_exception = None
    try:
        with _working_directory(sim_dir):
            fdtd.Run(str(sim_dir), cleanup=True, dump_statistics=True, verbose=1,
                     numThreads=max(1, min(os.cpu_count() or 1, 4)))
    except Exception as exc:
        run_exception = f"{type(exc).__name__}: {exc}"
    stats_path = sim_dir / "openEMS_run_stats.txt"
    convergence = (parse_run_statistics(stats_path.read_text(encoding="utf-8", errors="replace").splitlines())
                   if stats_path.is_file() else parse_run_statistics([]))
    evidence = {**evidence_base, "runtime": runtime, "mesh": mesh_metadata,
                "convergence": convergence,
                "artifacts": {"setup_xml_sha256": _sha256(xml_path),
                              "geometry_json_sha256": _sha256(geometry_path),
                              "run_statistics_sha256": _sha256(stats_path) if stats_path.is_file() else None}}
    if run_exception:
        return {"status": "FAILED", "detail": f"openEMS execution failed: {run_exception}",
                "metrics": None, "evidence": evidence}
    if not convergence["converged"]:
        return {"status": "NON_CONVERGED", "detail": convergence.get("reason", "openEMS energy did not converge"),
                "metrics": None, "evidence": evidence}

    try:
        port.CalcPort(str(sim_dir), frequencies)
        s11_complex = np.asarray(port.uf_ref) / np.asarray(port.uf_inc)
        zin = np.asarray(port.uf_tot) / np.asarray(port.if_tot)
        s11_db, s11_roundoff_clamped = _normalize_s11_magnitude_db(
            20 * np.log10(np.abs(s11_complex)))
        evidence["s11_passivity_roundoff_clamped"] = s11_roundoff_clamped
        s11_rows = [{"frequency_hz": float(frequency), "s11_db": float(db)}
                    for frequency, db in zip(frequencies, s11_db)]
        s11_rows = parse_s11_rows(s11_rows)
        resonance_hz, zin_at_resonance = _reactance_resonance(
            frequencies, zin, frequency_hz)
        nf_result = nf2ff.CalcNF2FF(str(sim_dir), resonance_hz,
                                    np.linspace(0, 180, 91), np.linspace(0, 360, 181))
        directivity_linear = float(np.asarray(nf_result.Dmax).reshape(-1)[0])
        directivity_dbi = 10 * math.log10(directivity_linear)
        radiated_w = float(np.asarray(nf_result.Prad).reshape(-1)[0])
        accepted_curve = np.asarray(port.P_acc, dtype=float)
        accepted_w = float(np.interp(resonance_hz, frequencies, accepted_curve))
        power = power_metrics(accepted_w, radiated_w, directivity_dbi)
        if power["gain_dbi"] is None:
            raise ValueError("cannot derive gain from zero radiated power")
        summary = summarize_s11(s11_rows, impedance_ohm=zin_at_resonance)
        summary["resonant_frequency_hz"] = resonance_hz
        target_index = min(range(len(s11_rows)),
                           key=lambda index: abs(s11_rows[index]["frequency_hz"] - frequency_hz))
        target_impedance = complex(zin[target_index])
        target_s11_db = s11_rows[target_index]["s11_db"]
        summary.update({
            "s11_at_resonance_db": 20 * math.log10(abs(
                (zin_at_resonance - 50.0) / (zin_at_resonance + 50.0))),
            "target_frequency_hz": frequency_hz,
            "s11_at_target_db": target_s11_db,
            "input_impedance_real_at_target_ohm": float(target_impedance.real),
            "input_impedance_imag_at_target_ohm": float(target_impedance.imag),
            "vswr_at_target": vswr_from_s11_db(target_s11_db),
        })
        if not math.isfinite(float(summary["vswr_min"])):
            summary["vswr_min"] = None
        summary.update(power)
        summary["directivity_dbi"] = directivity_dbi
        summary["resonance_definition"] = "linearly interpolated input-reactance zero crossing nearest the target frequency"
        summary["accepted_power_w"] = accepted_w
        summary["radiated_power_w"] = radiated_w
        s11_output = []
        for index, row in enumerate(s11_rows):
            gamma_db = row["s11_db"]
            vswr = vswr_from_s11_db(gamma_db)
            z_value = complex(zin[index])
            s11_output.append({"frequency_hz": row["frequency_hz"], "s11_db": gamma_db,
                               "s11_real": float(np.real(s11_complex[index])),
                               "s11_imag": float(np.imag(s11_complex[index])),
                               "input_impedance_real_ohm": float(z_value.real),
                               "input_impedance_imag_ohm": float(z_value.imag),
                               "vswr": vswr if math.isfinite(vswr) else None})
        pattern_rows = []
        field_norm = np.asarray(nf_result.E_norm).squeeze()
        theta_values = np.asarray(nf_result.theta).reshape(-1)
        phi_values = np.asarray(nf_result.phi).reshape(-1)
        if field_norm.shape != (len(theta_values), len(phi_values)):
            raise ValueError("openEMS NF2FF field shape does not match angular axes")
        for theta_index, theta in enumerate(theta_values):
            for phi_index, phi in enumerate(phi_values):
                field = float(abs(field_norm[theta_index, phi_index]))
                directivity_value = (directivity_dbi + 20 * math.log10(field / float(np.max(np.abs(field_norm))))) if field > 0 else -300.0
                pattern_rows.append({"theta_deg": math.degrees(float(theta)),
                                     "phi_deg": math.degrees(float(phi)),
                                     "gain_dbi": directivity_value + 10 * math.log10(power["efficiency_fraction"])})
        pattern_rows = parse_pattern_rows(pattern_rows)
        s11_path = sim_dir / "s11_curve.csv"
        pattern_path = sim_dir / "radiation_pattern.csv"
        _write_rows(s11_path, s11_output)
        _write_rows(pattern_path, pattern_rows)
    except (ValueError, TypeError, IndexError, ZeroDivisionError, FloatingPointError) as exc:
        return {"status": "FAILED", "detail": f"invalid/missing openEMS RF result: {exc}",
                "metrics": None, "evidence": evidence}
    evidence["artifacts"].update({"s11_curve_sha256": _sha256(s11_path),
                                 "radiation_pattern_sha256": _sha256(pattern_path)})
    metrics = {**summary, "s11_curve_path": str(s11_path.relative_to(output_dir.resolve())),
               "radiation_pattern_path": str(pattern_path.relative_to(output_dir.resolve())),
               "radiation_pattern_samples": len(pattern_rows)}
    return {"status": "COMPLETED", "detail": "openEMS completed and convergence was proven from run statistics",
            "metrics": metrics, "s11_curve": s11_output,
            "radiation_pattern": pattern_rows, "evidence": evidence}


def expected_input_hash(spec_hash: str, geometry: dict[str, Any],
                        overrides: dict[str, Any] | None = None, *,
                        mesh_resolution_factor: float = 1.0) -> str:
    """Return the stable identity used for this exact solver configuration."""
    if (isinstance(mesh_resolution_factor, bool)
            or not isinstance(mesh_resolution_factor, (int, float))
            or not math.isfinite(float(mesh_resolution_factor))
            or mesh_resolution_factor <= 0):
        raise ValueError("mesh_resolution_factor must be positive and finite")
    config = {
        "solver_setup_version": SOLVER_SETUP_VERSION,
        "geometry_hash_sha256": geometry["geometry_hash_sha256"],
        "scenario": geometry["scenario"], "frequency_hz": geometry["antenna"]["frequency_hz"],
        "max_time_steps": MAX_TIME_STEPS, "end_criteria": END_CRITERIA,
        "frequency_samples": FREQUENCY_SAMPLE_COUNT, "boundary": "PML_8 on all six faces",
        "mesh_rule": "lambda/20 fine reference with explicit coarse/fine factor and 1.4 smoothing ratio",
        "mesh_resolution_factor": float(mesh_resolution_factor),
        "excitation": EXCITATION_CONFIG, "port": PORT_CONFIG,
        "overrides": overrides or {},
    }
    return hashlib.sha256(json.dumps({"spec_hash": spec_hash, **config}, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()
