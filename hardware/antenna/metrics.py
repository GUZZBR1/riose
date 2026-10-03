"""Pure parsers and derived metrics for solver-produced RF results.

Rows use mappings with explicit column names and SI units. These functions do
not run a solver or infer missing data. ``gain_dbi`` derived from accepted
power efficiency and directivity is antenna gain (non-realized): it excludes
feed mismatch loss.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any


def _number(value: Any, name: str, *, positive: bool = False,
            nonnegative: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    if positive and number <= 0:
        raise ValueError(f"{name} must be greater than zero")
    if nonnegative and number < 0:
        raise ValueError(f"{name} must be nonnegative")
    return number


def _rows(rows: Iterable[Mapping[str, Any]], required: tuple[str, ...], label: str):
    if isinstance(rows, (str, bytes, Mapping)):
        raise ValueError(f"{label} must be an iterable of row mappings")
    parsed = []
    try:
        iterator = iter(rows)
    except TypeError as exc:
        raise ValueError(f"{label} must be an iterable of row mappings") from exc
    for index, row in enumerate(iterator):
        if not isinstance(row, Mapping):
            raise ValueError(f"{label} row {index} must be a mapping")
        missing = [key for key in required if key not in row]
        if missing:
            raise ValueError(f"{label} row {index} missing columns: {', '.join(missing)}")
        parsed.append(row)
    if not parsed:
        raise ValueError(f"{label} must contain at least one row")
    return parsed


def parse_s11_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, float]]:
    """Validate ``frequency_hz,s11_db`` rows and return sorted normalized data."""
    result = []
    for index, row in enumerate(_rows(rows, ("frequency_hz", "s11_db"), "S11 data")):
        frequency = _number(row["frequency_hz"], f"frequency_hz at row {index}", positive=True)
        s11 = _number(row["s11_db"], f"s11_db at row {index}")
        if s11 > 0:
            raise ValueError(f"s11_db at row {index} must be <= 0 dB")
        result.append({"frequency_hz": frequency, "s11_db": s11})
    result.sort(key=lambda item: item["frequency_hz"])
    if len({item["frequency_hz"] for item in result}) != len(result):
        raise ValueError("S11 frequencies must be unique")
    return result


def vswr_from_s11_db(s11_db: float) -> float:
    """Convert a nonpositive S11 magnitude in dB to VSWR."""
    db = _number(s11_db, "s11_db")
    if db > 0:
        raise ValueError("s11_db must be <= 0 dB")
    magnitude = 10.0 ** (db / 20.0)
    if magnitude >= 1.0:
        return math.inf
    return (1.0 + magnitude) / (1.0 - magnitude)


def summarize_s11(rows: Iterable[Mapping[str, Any]], *, impedance_ohm: complex | None = None) -> dict[str, float | None]:
    """Return sampled minimum-S11 resonance and matching quantities.

    Resonance is the sampled frequency with minimum S11 dB; no interpolation
    is performed. Optional complex input impedance is reported at that sample.
    """
    data = parse_s11_rows(rows)
    minimum = min(data, key=lambda item: (item["s11_db"], item["frequency_hz"]))
    result: dict[str, float | None] = {
        "resonant_frequency_hz": minimum["frequency_hz"],
        "s11_min_db": minimum["s11_db"],
        "vswr_min": vswr_from_s11_db(minimum["s11_db"]),
        "input_impedance_real_ohm": None,
        "input_impedance_imag_ohm": None,
    }
    if impedance_ohm is not None:
        try:
            z = complex(impedance_ohm)
        except (TypeError, ValueError) as exc:
            raise ValueError("impedance_ohm must be a finite complex number") from exc
        if not math.isfinite(z.real) or not math.isfinite(z.imag):
            raise ValueError("impedance_ohm must be a finite complex number")
        result["input_impedance_real_ohm"] = z.real
        result["input_impedance_imag_ohm"] = z.imag
    return result


def power_metrics(accepted_power_w: float, radiated_power_w: float,
                  directivity_dbi: float | None = None) -> dict[str, float | None]:
    """Compute accepted-power radiation efficiency and optional non-realized gain."""
    accepted = _number(accepted_power_w, "accepted_power_w", positive=True)
    radiated = _number(radiated_power_w, "radiated_power_w", nonnegative=True)
    if radiated > accepted:
        raise ValueError("radiated_power_w cannot exceed accepted_power_w")
    efficiency = radiated / accepted
    gain = None
    if directivity_dbi is not None:
        directivity = _number(directivity_dbi, "directivity_dbi")
        if efficiency > 0:
            gain = directivity + 10.0 * math.log10(efficiency)
    return {"efficiency_fraction": efficiency, "gain_dbi": gain}


def parse_pattern_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, float]]:
    """Validate angular pattern rows ``theta_deg,phi_deg,gain_dbi``.

    Angles are degrees with theta in [0, 180] and phi in [0, 360].
    """
    parsed = []
    for index, row in enumerate(_rows(rows, ("theta_deg", "phi_deg", "gain_dbi"), "pattern data")):
        theta = _number(row["theta_deg"], f"theta_deg at row {index}")
        phi = _number(row["phi_deg"], f"phi_deg at row {index}")
        gain = _number(row["gain_dbi"], f"gain_dbi at row {index}")
        if not 0 <= theta <= 180:
            raise ValueError(f"theta_deg at row {index} must be in [0, 180]")
        if not 0 <= phi <= 360:
            raise ValueError(f"phi_deg at row {index} must be in [0, 360]")
        parsed.append({"theta_deg": theta, "phi_deg": phi, "gain_dbi": gain})
    return parsed
