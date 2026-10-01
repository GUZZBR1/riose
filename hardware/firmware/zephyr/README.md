# Zephyr firmware adapter

The app adapts the portable C firmware core to Zephyr. On `native_sim`, the HAL
passes firmware-generated SX1262 SPI command frames to the real C peripheral
model and reads the LIS2DW12 register model; Zephyr supplies kernel timing and
sleep. On a physical board target, `src/main.c` binds the HAL to SPI, I2C, and
GPIO devices. Neither path forks or replaces `../src/`.

Build/run was verified against Zephyr v4.2.1 with the host toolchain on
`native_sim/native/64`. This native path executes the C FSM and the SX1262 and
LIS2DW12 C models. It is a software simulation, not analog bus emulation or a
physical-board build. The production-board `src/main.c` adapter remains
unverified in this environment.

`boards/native_sim_bus_emul.overlay` is an optional bus-emulator wiring template.
The validated native_sim path uses the same standalone C peripheral models as
the host integration harness, so it does not claim electrical bus emulation.
The physical-board path still needs a board-specific overlay and real drivers.

## Build when Zephyr is installed

From a Zephyr workspace with `ZEPHYR_BASE` exported and dependencies installed:

```sh
west build -b native_sim/native/64 -d build/tag-native \
  /path/to/riose/hardware/firmware/zephyr
west build -d build/tag-native -t run
```
The native_sim C models provide deterministic responses. The run exits after
one firmware TX/RX/sleep cycle with a `SIMULATED native_sim cycle PASS` log.
A hardware-target run requires an actual LIS2DW12 responder/device returning
`WHO_AM_I=0x44`.

For a physical board, replace the DTS overlay and configure GPIO polarity/pins,
SPI timing, I2C address, oscillator/antenna, radio regional parameters, and
interrupt wiring for that board. The 915 MHz default is a prototype setting,
not a regulatory approval or validated RF design.

Zephyr native_sim has documented SPI, I2C and GPIO emulation support; the bus
emulators still require peripheral-specific responder implementations:
[native_sim board documentation](https://docs.zephyrproject.org/latest/boards/native/native_sim/doc/index.html),
[bus-connected device emulator documentation](https://docs.zephyrproject.org/latest/hardware/emulator/bus_emulators.html).
