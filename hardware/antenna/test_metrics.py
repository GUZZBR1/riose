import math

import pytest

from hardware.antenna.metrics import parse_pattern_rows, parse_s11_rows, power_metrics, summarize_s11, vswr_from_s11_db


# TEST_FIXTURE: synthetic numerical data only; never a RIOSE solver result.
S11_ROWS = [
    {"frequency_hz": 920e6, "s11_db": -4.0},
    {"frequency_hz": 910e6, "s11_db": -12.0},
    {"frequency_hz": 915e6, "s11_db": -8.0},
]


def test_s11_rows_sort_and_report_sampled_minimum_resonance():
    parsed = parse_s11_rows(S11_ROWS)
    assert [row["frequency_hz"] for row in parsed] == [910e6, 915e6, 920e6]
    metrics = summarize_s11(S11_ROWS, impedance_ohm=48 - 3j)
    assert metrics["resonant_frequency_hz"] == 910e6
    assert metrics["s11_min_db"] == -12
    assert metrics["input_impedance_real_ohm"] == 48
    assert metrics["input_impedance_imag_ohm"] == -3
    assert metrics["vswr_min"] == pytest.approx(vswr_from_s11_db(-12))


@pytest.mark.parametrize("rows", [[], [{"frequency_hz": 0, "s11_db": -3}],
                                    [{"frequency_hz": 1, "s11_db": 1}],
                                    [{"frequency_hz": 1, "s11_db": float("nan")}],
                                    [{"frequency_hz": 1, "s11_db": -1},
                                     {"frequency_hz": 1, "s11_db": -2}]])
def test_s11_rejects_invalid_input(rows):
    with pytest.raises(ValueError):
        parse_s11_rows(rows)


def test_vswr_and_power_derived_metrics():
    assert vswr_from_s11_db(0) == math.inf
    with pytest.raises(ValueError):
        vswr_from_s11_db(1)
    metrics = power_metrics(2.0, 1.0, directivity_dbi=3.0)
    assert metrics["efficiency_fraction"] == 0.5
    assert metrics["gain_dbi"] == pytest.approx(3 - 10 * math.log10(2))
    assert power_metrics(2, 0, 3)["gain_dbi"] is None


@pytest.mark.parametrize("args", [(0, 0), (1, -1), (1, 2), (float("nan"), 0)])
def test_power_metrics_reject_invalid_power(args):
    with pytest.raises(ValueError):
        power_metrics(*args)


def test_pattern_rows_validate_angles_and_preserve_rows():
    rows = [{"theta_deg": 90, "phi_deg": 360, "gain_dbi": 1.25}]
    assert parse_pattern_rows(rows) == rows
    # openEMS persists the 2π endpoint as float32 radians in its NF2FF HDF5.
    float32_two_pi = math.degrees(6.2831854820251465)
    assert float32_two_pi > 360
    normalized = parse_pattern_rows([{"theta_deg": 90, "phi_deg": float32_two_pi, "gain_dbi": 1.25}])
    assert normalized[0]["phi_deg"] == 360
    with pytest.raises(ValueError, match="theta_deg"):
        parse_pattern_rows([{"theta_deg": 181, "phi_deg": 0, "gain_dbi": 0}])
    with pytest.raises(ValueError, match="phi_deg"):
        parse_pattern_rows([{"theta_deg": 90, "phi_deg": 360.01, "gain_dbi": 0}])
    with pytest.raises(ValueError, match="missing columns"):
        parse_pattern_rows([{"theta_deg": 90, "phi_deg": 0}])
