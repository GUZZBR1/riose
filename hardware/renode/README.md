# RIOSE Renode virtual hardware

Status: **SIMULATED / IMPLEMENTATION SCAFFOLD**. These files add a headless
Renode platform and custom bus responders for the protocol subset used by the
current firmware. No analog, RF propagation, energy, or silicon behavior is
represented here.

## Platform support finding

Renode upstream currently provides a `platforms/cpus/stm32l071.repl` Cortex-M0+
SoC model, but no STM32L031 platform was found. This scaffold reuses that L071
peripheral set to exercise an L0-family firmware path. The L071 platform has
192 KiB flash and 20 KiB SRAM in its memory map, while the candidate
STM32L031K6 has 32 KiB flash and 8 KiB SRAM. It must not be used to claim the
L031 memory limits, exact clock tree, or exact peripheral revision. Its GPIO,
SPI, I2C, timers, EXTI, watchdog, RTC and power-controller models are still
software abstractions. STOP/deep-sleep current and real wake latency are not
modeled. The existing Zephyr `native_sim` path remains the fast software-only
test path.

The SX1262 responder implements the SPI command subset used by the current
firmware: status, standby/sleep, LoRa configuration, buffer bases, FIFO,
IRQ-mask routing, TX completion, and bounded RX timeout. It rejects unsupported
commands and fixed-length command frames with a fault counter/status. `HoldBusy`,
`SuppressIRQ`, and `DropSPI` are fault hooks. TX completion and RX timeout use
Renode's virtual clock (64 kHz, matching the SX126x 15.625-us timeout tick), so
firmware polling does not advance radio time by an arbitrary amount per byte.
TX completion is a deterministic logical event; no RF waveform or peer is
modeled, so RX ends in timeout and never synthesizes `RX_DONE`. When a malformed
streamed command is detected at chip-select release, its status is available to
a following `GET_STATUS`; the byte already shifted during that same SPI frame
cannot be changed retroactively. The C callback can report the error in the
same returned transfer buffer because it receives the complete frame at once.

The LIS2DW12 responder implements address-pointer I2C register accesses,
WHO_AM_I, motion-profile sample data, wake-source clearing, and INT1 routing.
`FailI2C` produces a one-transaction bad read (not a standards-accurate
electrical NACK), and `HoldIRQ` suppresses its interrupt pin. Both responders
are scoped approximations, not electrical models.

## SX1262 comparison with the C model

`hardware/models/sx1262` remains the firmware-host reference for command bytes,
configuration state, FIFO contents, IRQ status, and logical TX/RX outcomes.
The Renode and C models share the supported firmware command subset and test
matching TX_DONE, TX timeout, RX timeout, FIFO, IRQ routing, and malformed-frame
vectors. Renode uses 15.625-us virtual ticks; the C model exposes integer
milliseconds and rounds timeouts up to a millisecond. Equal TX and timeout
deadlines produce TIMEOUT in both models. The C model's continuous RX case is
bounded to one virtual second for deterministic host tests; Renode uses the same
bound. Both complete TX according to the earlier TX-latency or radio-timeout
deadline, including when virtual time advances past both deadlines at once.

Known intentional gaps are explicit: the C API has no BUSY pin or reset-pin
timing, while Renode models BUSY during TX/RX and an active-low reset input;
Renode additionally exposes fault hooks for stuck BUSY, missing IRQ, and dropped
SPI response. Neither model generates received RF payloads, CRC outcomes, RF
power, analog behavior, or propagation. These outputs are logical simulations,
not measured radio behavior. `hardware/renode/tests/platform-smoke.robot` calls
the SPI peripheral byte-by-byte and checks configuration state, FIFO round-trip,
virtual-time TX_DONE and timeout, IRQ read/clear and routing, malformed frames,
reset, and fault hooks. Those direct peripheral tests do not prove the STM32 SPI
controller's chip-select waveform or a complete firmware recovery cycle.
`hardware/models/sx1262` contains matching CPU-only model scenarios.

## Headless use

Renode and `renode-test` are optional local tools; this workspace does not
vendor them. Install a Renode release and ensure `renode` and `renode-test`
are on `PATH`. The RIOSE platform compiles the custom C# model in the STM32
CPU's `preinit` block so the types are available before Renode resolves the
radio and IMU entries. Keep the suite's default setup and teardown from
`renode-test`; they connect the Robot remote library. Build the existing
Zephyr firmware for the STM32L0 target and set `RIOSE_ZEPHYR_ELF` to its ELF.

```sh
python3 hardware/renode/scripts/check_tools.py
renode --console --disable-xwt -e 'include @hardware/renode/riose_stm32l0.resc'
renode-test hardware/renode/tests/platform-smoke.robot
```

The repository target `make hardware-renode-test` runs the tool probe and
headless smoke suite when both Renode commands are installed; otherwise it
prints an explicit `SKIPPED` line so this optional tool does not block the
core firmware gate. The CI invokes the same target. The current Robot suite
proves platform/peripheral registration only; its firmware-load case remains
skipped unless `RIOSE_ZEPHYR_ELF` points to a compatible STM32L0 ELF.

For no-GUI execution in CI, use the console/headless switches above. The
Robot smoke test can load the platform without firmware; its second case is
skipped unless an ELF path is provided. A valid firmware ELF must be compiled
for a compatible STM32L0 memory map and peripheral base addresses. The current
board profile and Renode surrogate mismatch must be reviewed before wiring this
into required CI.
