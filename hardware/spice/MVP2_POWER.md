# MVP 2 trace-driven power analysis

This module is isolated from the MVP 1 `energy_model.py` and its generated
results. It consumes current-bearing intervals and creates a time-aligned
ngspice deck. Every output is `SIMULATED`; the accompanying component and
converter placeholders are `ASSUMED`. No parameter may be reported as
`MEASURED` by this module.

## Input contract

CSV, JSONL/NDJSON, or JSON array/object input rows use these fields:

| Field | Meaning |
|---|---|
| `timestamp_s` | Start of interval relative to trace start |
| `event` | Firmware event label, e.g. `TX_START` |
| `state` | FSM state during interval |
| `component` | Load owner, e.g. `mcu`, `imu`, `sx1262` |
| `duration_s` | Positive interval length |
| `load_current_ma` | Rail current for that component during the interval |

Intervals from simultaneous components add. Gaps use the configured assumed
idle current. Event charge is integrated from each component interval;
unattributed idle is included in total charge. `mAh/day` is emitted only when
the caller declares `--period-s`, a non-empty `--period-source`, and
`--period-status` (`DATASHEET`, `ASSUMED`, or `SIMULATED`). Periods must be
finite, positive seconds. The output preserves this provenance and labels
daily consumption as an extrapolation.
The terminal `MCU_SLEEP` payload closes a trace window; it does not imply that
the trace repeats daily. Daily charge extrapolates only the declared repeat
period and is not an autonomy claim. When a nominal battery capacity in mAh
has valid provenance, `ideal_capacity_division` reports nominal capacity
divided by simulated mAh/day as `THEORETICAL_IDEAL_CAPACITY_DIVISION`; it is
nominal-only arithmetic, not usable capacity or an autonomy prediction. The
output includes capacity and consumption provenance, the formula, and a caveat.
The caveat states that this mathematical division does not represent usable
capacity, aging, temperature, discharge curve, cutoff, real efficiency, or
predicted product autonomy. The nominal TLL-5902 capacity source is rated at
1 mA to 2.0 V and is not evidence of usable capacity under this rail's load.
Trace-derived schedules retain common window metadata so the idle
tail is included once. Radio start/end markers must be correctly ordered and
paired. Every observed FSM state and TX/RX interval must have a load-profile
entry; incomplete profiles fail conversion instead of dropping part of the
firmware sequence.

## Run

```sh
python hardware/spice/mvp2_power.py path/to/trace.jsonl \
  --period-s 900 --period-source "declared 15-minute event interval" \
  --period-status SIMULATED --period-unit s \
  --output results/mvp2/power
```

The command writes `summary.json`, timeline `power.csv`, `event_energy.csv`,
`power_trace.cir`, and one-factor-at-a-time `sweep.json`. When ngspice is on
PATH, a successful run also writes `electrical_trace.csv` with time, rail
voltage, and battery current, and reports rail extrema, peak input current,
droop from the assumed regulator setpoint, recovery, and margin above the
assumed functional voltage limit. Missing ngspice, convergence errors, missing
measurements, and malformed waveforms have explicit non-success status. A
failed run does not retain an electrical CSV. Without ngspice, trace energy
aggregation and deck generation still complete with status `NOT_AVAILABLE`.
Event charge rows report energy at the assumed regulator output voltage; the
summary separates TX, wake-window, sleep-window, and component contributions.

The orchestrator derives an assumptions file from `hardware/spec.yaml` for
each run. The standalone command defaults to the legacy MVP 1 illustrative
assumptions unless `--assumptions` is supplied. The deck uses an averaged ideal voltage source for the regulator, an assumed
output resistance/capacitor for rail transients, and a separate battery ESR
branch driven by load power converted through assumed efficiency. Event energy
and rail energy are derived at the assumed regulator output voltage and remain
`SIMULATED`. It is a
screening model, not a switching TPS62840 model, electrochemical cell model,
or electrical validation. Temperature sweep rows are tagged as assumptions
only and do not claim a temperature-dependent component model. Missing
Renode/ngspice outputs remain gate blockers in the integrated report.

## Tests

```sh
python -m unittest discover -s hardware/spice/mvp2_tests -v
```

Tests cover interval aggregation, trace-window alignment, complete state/radio
coverage, malformed marker rejection, energy metrics, invalid electrical
parameters, netlist generation, sweep metadata, and missing convergence output.
They do not require ngspice.
