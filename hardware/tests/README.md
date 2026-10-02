# C hardware integration harness

Status: **SIMULATED**. `integration.c` connects the production C tag FSM's `tag_hal_t` callbacks to the SX1262 SPI peripheral model and LIS2DW12 register model. The firmware still emits real SX126x commands through `spi_transfer`; the adapter does not replace the firmware with Python or imitate its state machine. I2C samples are read from `OUT_X_L..OUT_Z_H` and converted to mg before being returned to `imu_read`.

## Build and run

```sh
cmake -S hardware/tests -B /tmp/hardware-tests-build
cmake --build /tmp/hardware-tests-build
ctest --test-dir /tmp/hardware-tests-build --output-on-failure
```

CTest also runs the lower-level host firmware cycle and standalone SX1262/LIS2DW12 model tests. A 24-hour virtual sleep advances directly to the next beacon or radio timer deadline, preserving modeled TX/RX timeouts while avoiding millions of meaningless 10-ms MCU sleep iterations.

## Exporting a firmware trace for the Python power model

The integration harness is silent about files by default. Opt in with either
an argument or an environment variable; both run a separate deterministic
nominal virtual cycle and write JSONL records with the same
`riose.firmware.trace/v1` schema (`sequence`, `timestamp_us`, state/event/source
and IDs, result, and `value0..2`). Every line has `status=SIMULATED`.

```sh
/tmp/hardware-tests-build/hardware_integration \
  --trace-output /tmp/riose-firmware-trace.jsonl
# Equivalent:
RIOSE_TRACE_OUTPUT=/tmp/riose-firmware-trace.jsonl \
  /tmp/hardware-tests-build/hardware_integration
```

Use `--trace-scenario NORMAL|ACTIVE|ALERT|WORST_REASONABLE_CASE` to export a
trace for one deterministic firmware profile. `--long-run-days 1|7|30
--scenario ...` runs the matching accelerated firmware profile and prints a
versioned JSON summary. The long-run interface validates scheduling and FSM
stability; it does not retain a multi-day event trace or represent field data.
CTest covers all four trace profiles and the 12 scenario/duration combinations.

Convert those point events into the power tool's interval JSONL, then analyze
the resulting schedule:

```sh
python3 hardware/spice/trace_adapter.py /tmp/riose-firmware-trace.jsonl \
  --loads results/mvp2/power/assumed_load_profile.json \
  --output /tmp/riose-power-schedule.jsonl
python3 hardware/spice/mvp2_power.py /tmp/riose-power-schedule.jsonl
```

The load profile is a JSON object keyed by `state:<STATE>`,
`event:<EVENT>`, or `pair:<START_EVENT>:<END_EVENT>`. Every entry supplies a
component, `load_current_ma`, `current_status: "ASSUMED"`, and a source. Point
events and event pairs whose timestamps collapse to the trace's 1 ms
resolution also require `fallback_duration_s`, `duration_status: "ASSUMED"`,
and `duration_source`. Every current entry also requires a nonempty `source`.
Pair intervals such as `TX_START` → `TX_DONE`
otherwise use the elapsed firmware trace timestamps. The adapter refuses
unpaired intervals, missing durations, or non-ASSUMED current data; it does
not invent missing loads. The test profile in
`hardware/spice/mvp2_tests/test_trace_adapter.py` exists only to test parser
interoperability and is not an ear-tag power estimate. No current in this
firmware trace is measured.
The orchestrator generates the load profile from `hardware/spec.yaml` and
passes it through `--loads`. It maps MCU awake states, SLEEP, IMU reads, TX,
and RX. State transitions within the same millisecond are zero-duration
markers and are skipped rather than expanded into overlapping fallback dwell.
A terminal state uses its `MCU_SLEEP.value0` scheduled wait when present; only
if that closing event is absent does the adapter use an explicitly configured
`ASSUMED` fallback. Those fallbacks are model hypotheses and do not claim the
firmware actually remained in that state for that duration.

## Integration coverage

The integration executable covers:

- boot/self-test, SX1262 command configuration, packet FIFO, 24-byte telemetry CRC, tag ID and configured battery value;
- TX_DONE, bounded RX timeout, radio `SetSleep`, and wake back into standby before another transmission;
- LIS2DW12 IRQ wake and the alert telemetry path;
- injected one-shot I2C and SPI failures followed by firmware recovery;
- absent/late TX_DONE represented by a TX latency beyond the firmware timeout;
- 24-hour mixed motion profiles, stationary periods, and prolonged ACTIVE/ALERT states to validate bounded high-rate bursts;
- configured low-battery telemetry profile (2180 mV) and its extended 900-second beacon interval.

The wake line is disabled for the long mixed and stationary runs so these measurements isolate scheduled cadence and classifier behavior. A separate integration scenario enables wake routing and verifies interrupt handling. The long mixed run reports deadline versus escalation/event transmissions separately.

## Observed run

The default normal cadence is 900 s (96 transmissions/day). ACTIVE transmits each 60 s and ALERT each 10 s, but only during a two-minute burst when each state is entered; if the state remains active, the tag returns to the 15-minute heartbeat. A three-hour stationary period below the configured four-hour stillness alarm produced 12 packets. A three-hour forced ACTIVE period produced 14 packets. A full 24-hour stationary profile crossed the assumed four-hour threshold and produced 108 packets. The mixed 24-hour movement profile produced 128 packets. These deterministic results cover the software cadence policy only; they do not establish biological alarm thresholds or actual battery use.

### Explicit duty-cycle profiles

`integration.c` also runs five isolated profiles with exact TX-count assertions. The short bursts count transmissions in the half-open interval `[event start, event start + 120 s)`, so a packet exactly at the two-minute boundary is excluded from the burst count.

| Profile | Configuration and window | Observed TX | Meaning |
|---|---|---:|---|
| NORMAL | Stationary 24 h; stillness alarm moved beyond the run; 900-s normal cadence | 96 | Exact baseline: one initial beacon and then every 15 minutes. |
| ACTIVE burst | Forced ACTIVE for 2 min; 60-s active cadence | 2 | TX at 0 and 60 s. The boundary sample is outside this count. |
| ALERT burst | ALERT from the start; 10-s alert cadence | 12 | TX from 0 through 110 s. A TX at 120 s belongs to the post-burst path. |
| Repeated ACTIVE events | Default 15-min normal cadence; each forced episode lasts 2 min; then stationary; 24 h | 85 events, 255 TX | 3.54 events/hour. Each event yields two burst TX plus a due TX at the 2-min boundary. |
| Pathological ALERT | ALERT held continuously for 3 h; 10-s alert cadence and then 900-s normal cadence | 24 | 13 TX through the 120-s boundary, then 11 sparse heartbeats. |

The repeated-event case represents an aggressive but cadence-limited schedule: event starts are 17 minutes apart (2-minute event window plus a 15-minute normal interval), not arbitrarily injected at a higher rate than the firmware can sample. The pathological ALERT case shows the finite alert burst returning to sparse heartbeats even while ALERT remains latched. Both are simulated software profiles and use the configured classifier/timers; neither is a physiological threshold or measured radio current.

These results are deterministic software simulation results, not measurements of a physical sensor, radio, battery, or animal.

## Limits and blockers

- Battery voltage is a static `tag_config_t` input. The low-battery policy and serialized voltage can be tested, but the HAL has no ADC/fuel-gauge, power-good, brownout-reset, or low-voltage lockout interface. A real brownout/recovery test is therefore unsupported by the current firmware API. The separate ngspice model is an assumed circuit sensitivity model and does not change this limitation.
- The harness advances logical sensor time and radio timers. It does not model MCU current, analog supply droop, RF propagation, SPI/I2C electrical faults, or temperature.
- Motion waveforms and the four-hour stillness alarm threshold are software assumptions, not cattle physiology or field validation.
- RX completion is represented by the deterministic SX1262 timeout path; no downlink packet is generated in this integration run.
