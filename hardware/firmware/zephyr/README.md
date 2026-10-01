# Zephyr board adapter (unverified here)

This app adapts the existing portable C firmware core to Zephyr `native_sim`
device APIs. It uses SPI for SX1262 commands, I2C register access for a
LIS2DW12-compatible IMU, GPIO for reset/DIO/IMU interrupt signals, and Zephyr
kernel uptime/sleep. It does not fork or replace `../src/`.

The current workspace has no `west` executable, Zephyr source tree, or Zephyr
SDK. **No Zephyr configure, build, or run result is claimed.** The validated
build remains the independent CMake host harness under `../CMakeLists.txt`.

`boards/native_sim.overlay` maps the native simulator's emulated buses and GPIO
to the HAL aliases. Native_sim supplies emulated SPI, I2C, and GPIO controllers,
but a functioning run also requires Zephyr bus-emulator responder drivers for
the SX1262 and LIS2DW12-compatible devices. This firmware adapter deliberately
does not implement a second peripheral model. The overlay and responder
integration therefore need validation when the Zephyr environment/model glue
is available.

## Build when Zephyr is installed

From a Zephyr workspace with `ZEPHYR_BASE` exported and dependencies installed:

```sh
west build -b native_sim -d build/tag-native \
  /path/to/riose/hardware/firmware/zephyr -- \
  -DDTS_ROOT=/path/to/riose/hardware/firmware/zephyr
west build -d build/tag-native -t run
```
The initial start-up will fail explicitly if a sensor bus responder does not
return LIS2DW12 `WHO_AM_I=0x44`.

For a physical board, replace the DTS overlay and configure GPIO polarity/pins,
SPI timing, I2C address, oscillator/antenna, radio regional parameters, and
interrupt wiring for that board. The 915 MHz default is a prototype setting,
not a regulatory approval or validated RF design.

Zephyr native_sim has documented SPI, I2C and GPIO emulation support; the bus
emulators still require peripheral-specific responder implementations:
[native_sim board documentation](https://docs.zephyrproject.org/latest/boards/native/native_sim/doc/index.html),
[bus-connected device emulator documentation](https://docs.zephyrproject.org/latest/hardware/emulator/bus_emulators.html).
