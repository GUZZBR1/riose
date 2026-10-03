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
PATH, a successful run also writes `electrical_trace.csv` with the simulation
and netlist identity, fault profile, time, rail voltage, battery-terminal
voltage, battery current, and `SIMULATED` status, and reports rail extrema, peak input current,
droop from the assumed regulator setpoint, recovery, and margin above the
assumed functional voltage limit. Missing ngspice, convergence errors, missing
measurements, and malformed waveforms have explicit non-success status. A
failed run does not retain an electrical CSV. Without ngspice, trace energy
aggregation and deck generation still complete with status `NOT_AVAILABLE`.
Event charge rows report energy at the assumed regulator output voltage; the
summary separates TX, wake-window, sleep-window, and component contributions.

The orchestrator derives an assumptions file from `hardware/spec.yaml` for
each run. The standalone command defaults to the legacy MVP 1 illustrative
assumptions unless `--assumptions` is supplied. The averaged regulator source
is headroom-limited by the battery node after cell ESR and a sourced ASSUMED
dropout value, so cell voltage/ESR changes can alter the rail. The named
`--fault-profile` cases apply synthetic ASSUMED injections: voltage drop during
trace-derived TX intervals, 40 ohm cell ESR stress, or a 0.8 V/100 Hz regulator
output perturbation while load current exceeds 10 mA. These are stress probes,
not device characterization or TPS62840 stability claims. Each profile is
included in the netlist, summary, and CSV; each output is cleared and validated
before reuse, with hashes binding the CSV to the deck and waveform. Profiles
skip parameter sweeps so their result remains a single attributable execution.
The Issue #7 host power supervisor consumes the timestamped rail CSV and only
reports recovery after an observed threshold crossing, rail recovery, and a
post-reinitialization beacon. The threshold value/provenance comes from
`hardware/spec.yaml` and remains ASSUMED. This is a screening model, not a
switching-regulator model, electrochemical cell model, or electrical
validation. Without an explicitly supplied `temperature_model`, temperature
sweep rows retain `NOT_MODELED_NO_TEMPERATURE_DEPENDENCY`. Missing Renode/ngspice outputs
remain gate blockers in the integrated report.

## Declared temperature sensitivity

An assumptions file can include an optional `temperature_model` with kind
`LINEAR_PARAMETER_SENSITIVITY`. Supply `reference_temperature_c`,
`minimum_temperature_c`, and `maximum_temperature_c` as records containing
`value`, `unit: "degC"`, `status` (`ASSUMED`, `DATASHEET`, or `SIMULATED`), and a
nonempty `source`. The reference anchors the existing electrical parameters;
the declared valid range must contain the reference and all three sweep points
(-10, 25, and 50 degrees C). Extrapolation is rejected.

The model's `coefficients` map accepts the following sourced records, using the
same `value`/`unit`/`status`/`source` format:

| Parameter | Coefficient unit |
|---|---|
| `battery_esr_ohm` | `ohm/degC` |
| `regulator_efficiency` | `fraction/degC` |
| `regulator_dropout_v` | `V/degC` |
| `output_capacitance_f` | `F/degC` |

For each supplied parameter, the sweep evaluates
`parameter(T) = parameter(reference) + coefficient * (T - reference)` and
validates the resulting electrical parameters before generating a deck.
Parameters omitted from `coefficients` stay at their reference value. At least
one coefficient must be nonzero. The temperature cases then execute ngspice
individually; the aggregate status can be `PASS` only after every case passes.
Simulation failures and missing ngspice keep their existing explicit statuses.
Each case and its deck preserve the model definition, coefficient provenance,
reference parameters, formula, and resolved values. Results carry
`SIMULATED_PARAMETER_SENSITIVITY_NOT_CHARACTERIZED` and are not evidence of a
measured or validated temperature response. Load currents and nominal battery
capacity do not acquire a temperature dependency through this electrical model.

The default profile supplies no temperature coefficients: the project has no
characterized temperature response to insert. A caller must provide and label
its own assumptions or sourced coefficients; unit-test coefficients are
synthetic fixtures only. This support does not establish physical temperature
behavior or remove a missing-temperature-model gate for default integrated runs.

## Tests

```sh
python -m unittest discover -s hardware/spice/mvp2_tests -v
```

Tests cover interval aggregation, trace-window alignment, complete state/radio
coverage, malformed marker rejection, energy metrics, invalid electrical
parameters, coupled fault-profile netlists, sweep metadata, and missing
convergence output. The unit suite does not require ngspice; causal runs require
an actual ngspice invocation and current-run waveform validation.
