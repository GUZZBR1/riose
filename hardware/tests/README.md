# C hardware integration harness

Status: **SIMULATED**. `integration.c` connects the production C tag FSM's `tag_hal_t` callbacks to the SX1262 SPI peripheral model and LIS2DW12 register model. The firmware still emits real SX126x commands through `spi_transfer`; the adapter does not replace the firmware with Python or imitate its state machine. I2C samples are read from `OUT_X_L..OUT_Z_H` and converted to mg before being returned to `imu_read`.

## Build and run

```sh
cmake -S hardware/tests -B /tmp/hardware-tests-build
cmake --build /tmp/hardware-tests-build
ctest --test-dir /tmp/hardware-tests-build --output-on-failure
```

CTest also runs the lower-level host firmware cycle and standalone SX1262/LIS2DW12 model tests. A 24-hour virtual sleep advances directly to the next beacon or radio timer deadline, preserving modeled TX/RX timeouts while avoiding millions of meaningless 10-ms MCU sleep iterations.

## Integration coverage

The integration executable covers:

- boot/self-test, SX1262 command configuration, packet FIFO, 24-byte telemetry CRC, tag ID and configured battery value;
- TX_DONE, bounded RX timeout, radio `SetSleep`, and wake back into standby before another transmission;
- LIS2DW12 IRQ wake and the alert telemetry path;
- injected one-shot I2C and SPI failures followed by firmware recovery;
- absent/late TX_DONE represented by a TX latency beyond the firmware timeout;
- 24-hour mixed motion profiles and a healthy stationary period under the configured stillness alarm threshold;
- configured low-battery telemetry profile (2180 mV) and its extended 900-second beacon interval.

The wake line is disabled for the long mixed and stationary runs so these measurements isolate scheduled cadence and classifier behavior. A separate integration scenario enables wake routing and verifies interrupt handling. The long mixed run reports deadline versus escalation/event transmissions separately.

## Observed run

On the current C-only model build, the 24-hour mixed profile produced 7,344 TX packets: 1,680 during the first stationary block, 360 walking, 984 running, 2,160 abnormal, and 2,160 during the final stationary block. All 7,344 were transmitted at the firmware's beacon deadline; there were no direct escalation/event transmissions with INT1 disabled. No firmware failures occurred. The classifier remained in ALERT through the final stationary block; this is a simulated behavior that merits further review.

A three-hour stationary profile below the default four-hour stillness alarm produced 180 packets at a 60-second cadence. A full 24-hour stationary profile produced 14,640 packets: the default stillness threshold is 14,400,000 ms (four hours), after which the ALERT cadence is five seconds. This is the configured simulated alarm policy, not evidence that four hours of inactivity is clinically abnormal. The higher rate is visible in the output and should inform future energy and false-alarm experiments.

These results are deterministic software simulation results, not measurements of a physical sensor, radio, battery, or animal.

## Limits and blockers

- Battery voltage is a static `tag_config_t` input. The low-battery policy and serialized voltage can be tested, but the HAL has no ADC/fuel-gauge, power-good, brownout-reset, or low-voltage lockout interface. A real brownout/recovery test is therefore unsupported by the current firmware API; no voltage trace is fabricated here.
- The harness advances logical sensor time and radio timers. It does not model MCU current, analog supply droop, RF propagation, SPI/I2C electrical faults, or temperature.
- Motion waveforms and the four-hour stillness alarm threshold are software assumptions, not cattle physiology or field validation.
- RX completion is represented by the deterministic SX1262 timeout path; no downlink packet is generated in this integration run.
