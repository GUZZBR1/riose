# Physical power calibration

**Status: NOT MEASURED.** No physical MCU, SX1262, LIS2DW12, candidate rail,
battery, current analyzer, or oscilloscope is connected to the current
workspace. This procedure is ready for bench use; the blank CSV is a schema,
not evidence. Do not copy the simulated values into its rows.

## Candidate assembly

Evaluate the present firmware against this candidate chain:

- STM32L031K6 MCU platform (the existing Zephyr target is NUCLEO-L031K6);
- SX1262 radio module configured for the chosen legal regional band and +14
  dBm test case;
- LIS2DW12 accelerometer on I2C;
- TPS62840 buck configured for a 3.3 V rail;
- Tadiran TLL-5902 3.6 V primary Li-SOCl2 cell.

These are the selected **bench candidates**, not final product choices. A
Nucleo board is useful for firmware bring-up, but its debugger, LEDs and board
regulator can distort sleep-current results. Measure MCU-only if using the
IDD jumper, then separately measure current entering the complete tag rail.
For the whole-tag test, isolate USB/debugger power and insert the analyzer in
the battery path. Never charge the primary TLL-5902. Check the exact module
pinout, supply range, antenna and local radio rules before wiring or TX.

## Required captures

Log battery current, battery voltage and the 3.3 V rail synchronously. Put a
GPIO marker or firmware trace marker on each state transition; avoid UART log
traffic during low-current captures. Capture current at enough bandwidth to
resolve the 120 ms TX charge and separately use an oscilloscope/current probe
with bandwidth suitable for the short wake and switching transients. A target
of at least 1 ksample/s can help integrate TX energy, but does not establish
the true sub-millisecond peak or converter ripple. Choose range/burden to also
resolve sleep current. A low-rate multimeter cannot establish the TX peak or
integrated charge. Save the untouched instrument export and record its range,
sample rate, burden voltage and calibration date.

Record each condition below, at minimum three repeats, with a distinct `run_id`
per capture, including instrument, firmware SHA, board revision, antenna/load,
TX power, ambient temperature, cell voltage and rail minimum. The firmware policy can be run at accelerated
logical time for event-rate cases; retain physical wake/TX/RX dwell time. State
explicitly which delays were accelerated. Do not call an accelerated test a
24-hour battery measurement unless charge is computed from measured per-state
current and the actual 24-hour state-duration/event schedule.

| Scenario | Firmware stimulus | Capture and report |
|---|---|---|
| `NORMAL_24H` | stationary/normal, default 900 s heartbeat | Full 24-hour current trace; charge in mAh, 96 expected scheduled beacons, state dwell, rail minimum |
| `ACTIVE_BURST_2M` | enter ACTIVE, hold for 120 s | sleep/IMU wake, 60 s active beacon cadence, TX peak and integrated charge |
| `ALERT_BURST_2M` | enter ALERT, hold for 120 s | 10 s beacon cadence, TX peak and integrated charge |
| `WORST_EVENTS_PER_HOUR` | repeat ACTIVE episodes at six/hour, each 2 min | measured event count, total TX, full-profile charge and rail minima |
| `PATHOLOGICAL_ALERT_HOURS` | sustained alert for at least 3 h, then longer if safe | confirm bounded initial burst returns to heartbeat; charge and any resets |

Also isolate these electrical/software phases: deep sleep with radio asleep;
IMU monitoring; MCU wake and classification; SX1262 TX at +14 dBm; SX1262 RX
window; TX-to-RX sequence; 3.3 V rail during TX; battery-side peak current;
and brownout/reset response during a controlled supply sweep. Use a current-
limited bench source for rail sweeps before risking the primary cell. Note that
the battery datasheet's 100 mA pulse rating has conditions; passing a single
peak-current comparison is not a battery-life or pulse-capability validation.

## Capture and analysis

Use `measurements.template.csv` as the capture schema. Rows are synchronized
samples in chronological order; `timestamp_s` is monotonic from zero and
`state` labels the interval starting at that sample. `tx_count` is a cumulative
counter, not a per-sample delta. Each distinct `(scenario, run_id)` is analyzed
as one capture, so repeats can share one input CSV. The script assigns an
interval's trapezoidal charge to the preceding sample's state; the accuracy of
state attribution is limited by the sample period at transitions. Preserve the
raw CSV and original instrument export, and fill in the provenance fields.
Analyze with:

```sh
python3 hardware/physical/analyze_capture.py measurements.csv \
  --output results/physical-power.json
```

The script integrates user-supplied battery current with the trapezoidal rule
and reports elapsed charge, mean current, peak sampled current, rail minimum
and state dwell for each capture. Its
`USER_SUPPLIED_MEASURED_CAPTURE_NOT_INDEPENDENTLY_AUTHENTICATED` status does
not mean the data were independently verified. It does not extrapolate an abbreviated capture to
a day or calculate battery life. For the simulator update, use measured
state currents and durations plus the production firmware's measured TX
counts/duty schedules; retain source, setup, uncertainty and status with each
parameter. Keep simulated and measured profiles separate.

## Current workspace blocker

The environment audit found no `/dev/ttyACM*`, `/dev/ttyUSB*`, `/dev/spidev*`,
GPIO/I2C/SPI device, programmer, cross compiler, or measurement instrument.
So the required physical readings, firmware flash, regulator validation and
brownout test cannot be performed here. Zephyr `native_sim` and the ngspice
average-load deck remain software/model evidence only. `src/main.c` also needs
a board overlay and SX1262 BUSY handshake before it is ready for hardware;
see the Zephyr adapter notes. This blocker should be cleared with the assembled
bench candidate and instrument connected, then the capture workflow above can
be run. See [`../reports/power-model.md`](../reports/power-model.md) for the
current ASSUMED/SIMULATED numbers and their limits.
