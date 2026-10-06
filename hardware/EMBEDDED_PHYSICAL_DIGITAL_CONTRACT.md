# Embedded and physical-digital contracts

Status: **SIMULATED / SOFTWARE-INTEGRATION CONTRACT**. The interfaces below
connect software models and simulators. They do not assert calibrated sensors,
an assembled device, a measured radio link, or field accuracy.

## Cross-simulator mapping

| Concept | Firmware / sensor | Renode | Gazebo MVP3 | RF / analysis |
|---|---|---|---|---|
| Identity | `tag_id` is an unsigned 32-bit value in bytes 2–5 of the 24-byte little-endian telemetry packet. | Captured SX1262 payload preserves the packet identity. | Model/entity names and scenario identity are separate; they are not automatically copied into packet identity. | Logical event joins use packet `tag_id`; no Sionna/FREQUENCIA receive identity is attached by MVP3. |
| Time | Firmware monotonic uptime is milliseconds in telemetry; firmware trace timestamps are microseconds. These are software clocks. | TX trace timestamps are Renode virtual-time nanoseconds. The converter floors them to microseconds; sub-microsecond precision is discarded. | Gazebo simulation time is seconds. Offline RESD replay rebases to the first sample and then uses Renode replay time. Live mode advances paused Gazebo batches against Renode barriers; this is a simulation clock mapping. | Solver scenario clocks and results remain separately scoped. They are not inferred from a firmware or Gazebo timestamp. |
| Acceleration | LIS2DW12 `CTRL1=0x14`, ±2 g, signed left-aligned 14-bit outputs; X/Y/Z are converted to integer mg using 0.244 mg/LSB. | RESD acceleration is provided in x/y/z micro-g to the virtual LIS2DW12. Wake behavior is an explicit approximate model. | IMU linear acceleration arrives in m/s² and is divided by standard gravity `9.80665 m/s²` to produce g; the converter preserves reported x/y/z component order. | RF simulation does not consume sensor acceleration in MVP3. |
| Position / orientation | No position/orientation is present in the firmware telemetry packet. | Not captured by the SX1262 transaction trace; adapter emits no pose. | Gazebo world poses are in meters with quaternion x/y/z/w. IMU axes remain the sensor-frame axes; `gazebo_to_resd` does not apply a world/body rotation. | MVP3 logical RF has `pose=None` unless an explicit caller supplies an independently joined pose. No propagation result is inferred. |
| Radio event | Firmware trace marks TX_START/TX_DONE; a completed TX is a logical firmware/radio event. | SX1262 command/IRQ and TX records are modeled with Renode virtual time. RX ends in timeout; no received payload, RSSI, SNR, or RF waveform is created. | Anchor acceptance visualizes a logical completed packet. It is not a receiver result. | Distinguish `NOT_TRANSMITTED`, `NOT_RECEIVED`, and `NO_PATH` in any future adapter; missing channel values stay null/status-tagged. |
| Provenance | Host/model and Zephyr simulator traces are marked `SIMULATED`. | Virtual peripherals and RESD playback are `SIMULATED`. | Gazebo world, IMU capture and lockstep are `SIMULATED`; mechanics/materials are `ASSUMED`. | openEMS/Sionna/ngspice outputs are solver/model evidence only; physical validation requires independent measurements. |

## Stable contracts and boundaries

- Firmware HAL (`hardware/firmware/include/tag_firmware.h`) isolates the state
  machine from SPI, IMU, IRQ, monotonic-time and sleep providers.
- LIS2DW12 sample conversion is tied to the `CTRL1=0x14`, ±2 g high-performance
  configuration. A different mode or full scale requires changing both the
  register configuration and the conversion contract/test.
- `riose.renode.sx1262_tx_trace/v1` records logical model TX start/completion,
  captured payload, PLL word and configured power. `riose.firmware.trace/v1`
  uses microseconds and preserves explicit `SIMULATED` provenance.
- Gazebo-to-RESD conversion is an offline sample contract; live lockstep is a
  separate Gazebo-master, paused-batch contract. Neither is a shared wall clock.
- The 915 MHz firmware setting is an assumed prototype setting, not a selected
  regional band. Antenna solver inputs/materials and tag mechanics remain
  `ASSUMED` unless a specific record says otherwise.
- `GUZZBR1/frequencia` remains an external simulator dependency. This upstream
  base contains no FREQUENCIA consumer/adapter, and this mini-MVP adds none.
  Any future integration must exchange versioned input/output manifests and
  retain request/scenario/tag identities, clocks, hashes, backend, seed and
  environment outside the firmware runtime.

## Evidence classifications

`SIMULATED` describes generated/model data, `ASSUMED` describes selected but
unmeasured design inputs, and `NOT_TESTED`/`NOT_AVAILABLE` describe missing
execution evidence. A successful C/pytest/Robot test demonstrates only the
software contract under test. Numerical convergence is not accuracy;
`PHY_RECEIVED` or application delivery must never be inferred from a logical
TX or `TX_DONE` event; physical/field validation requires real measurements.
