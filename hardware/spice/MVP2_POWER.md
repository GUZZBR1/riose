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
the caller declares `--period-s`; it extrapolates that explicit repeating
window and is not an autonomy claim. Capacity division is intentionally not
performed.

## Run

```sh
python hardware/spice/mvp2_power.py path/to/trace.jsonl \
  --period-s 900 --output results/mvp2/power
```

The command writes `summary.json`, timeline `power.csv`, `event_energy.csv`,
`power_trace.cir`, and one-factor-at-a-time `sweep.json`. When ngspice is on
PATH, the deck runs in batch mode and logs rail extrema, estimated battery
voltage sag, peak input current, and a raw waveform. Without ngspice, the
trace aggregation and deck generation still complete and the summary says
`NOT_AVAILABLE`.

The orchestrator derives an assumptions file from `hardware/spec.yaml` for
each run. The standalone command defaults to the legacy MVP 1 illustrative
assumptions unless `--assumptions` is supplied. The deck uses an averaged ideal voltage source for the regulator, an assumed
output resistance/capacitor for rail transients, and a separate battery ESR
branch driven by load power converted through assumed efficiency. It is a
screening model, not a switching TPS62840 model, electrochemical cell model,
or electrical validation. Temperature sweep rows are tagged as assumptions
only and do not claim a temperature-dependent component model. Missing
Renode/ngspice outputs remain gate blockers in the integrated report.

## Tests

```sh
python -m unittest discover -s hardware/spice/mvp2_tests -v
```

Tests cover interval aggregation, declared-period extrapolation, netlist
generation, and sweep metadata. They do not require ngspice.
