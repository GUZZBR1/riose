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

The SX1262 responder implements deterministic SPI command framing for status,
standby/sleep, IRQ setup/read/clear, FIFO read/write, TX completion and RX
timeout. `HoldBusy`, `SuppressIRQ` and `DropSPI` are fault hooks. TX completion
is advanced by subsequent SPI traffic rather than a modeled RF oscillator or
Renode timer; exact elapsed TX timing is therefore not yet trustworthy.
The LIS2DW12 responder implements address-pointer I2C register accesses, WHO_AM_I,
motion-profile sample data, wake-source clearing and INT1 routing. `FailI2C`
produces a one-transaction bad read (not a standards-accurate electrical NACK),
and `HoldIRQ` suppresses its interrupt pin. Both responders are scoped
approximations; compare them with `hardware/models/{sx1262,lis2dw12}` C models
before treating them as equivalent. The C models remain the reference behavior.

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

## Firmware wake-up scenario

The Robot smoke test loads the platform without firmware. Its firmware case is
skipped unless RIOSE_ZEPHYR_ELF points to an ELF compiled for the NUCLEO-L031K6
profile. That case advances 100 ms of guest virtual time, injects a routed
LIS2DW12 wake event, and checks that firmware consumes the interrupt. Renode's
emulation RunFor command advances guest time deterministically without waiting
for the same amount of host wall time. This does not validate electrical timing
or STOP current behavior.

Build the physical Zephyr profile in a configured Zephyr workspace, then run:

    west build -b nucleo_l031k6 -d build/tag-nucleo-l031k6 hardware/firmware/zephyr
    export RIOSE_ZEPHYR_ELF="$PWD/build/tag-nucleo-l031k6/zephyr/zephyr.elf"
    make hardware-renode-test

The platform wires the MCU model's GPIO, SPI, I2C, timer/RTC and interrupt
controllers to the protocol responders. The Robot case verifies startup and IMU
IRQ-driven return to sleep only. A full temporal trace, timer-driven wake, exact
L031 flash/RAM limits, clock-tree fidelity and STOP/deep-sleep electrical
behavior remain outside the evidence produced by this surrogate and require
additional target-specific validation before claiming full MCU equivalence.
native_sim remains a separate fast software/model test path and does not
represent Renode or electrical simulation.
