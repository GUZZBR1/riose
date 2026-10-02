# CPU SX1262 peripheral model

This is a standalone C peripheral model for testing the tag firmware's SPI
driver without radio hardware. Every `sx1262_model_transfer()` call is one
complete transaction with chip select held for the entire TX buffer. Its
signature matches the firmware HAL callback:

```c
int tag_spi_transfer(void *ctx, const uint8_t *tx, size_t tx_len,
                     uint8_t *rx, size_t rx_len);
/* tag_hal_t hal = { .ctx = &radio, .spi_transfer = sx1262_model_transfer }; */
```

The model is intentionally transport-only: it accepts SX126x command opcodes
and arguments, so firmware performs real command encoding. There is no hidden
Python implementation of firmware behavior.

## Implemented commands

`GET_STATUS (C0)`, `SET_SLEEP (84)`, `SET_STANDBY (80)`, `SET_TX (83)`,
`CALIBRATE_IMAGE (98)`, `SET_PA_CONFIG (95)`, `SET_RF_FREQUENCY (86)`, `SET_PACKET_TYPE (8A)`,
`SET_MODULATION_PARAMS (8B)`, `SET_PACKET_PARAMS (8C)`, `SET_TX_PARAMS (8E)`,
`SET_BUFFER_BASE_ADDRESS (8F)`, `WRITE_BUFFER (0E)`, `READ_BUFFER (1E)`,
`SET_DIO_IRQ_PARAMS (08)`, `GET_IRQ_STATUS (12)`, and
`CLEAR_IRQ_STATUS (02)`. LoRa modem parameters are range checked. The model
tracks a 256-byte FIFO, standby/sleep/TX modes, frequency synthesizer word,
power, image-calibration bytes, PA configuration and packet configuration.
For SX1262, the driver must send `SET_PA_CONFIG (95 04 07 00 01)` before
`SET_TX_PARAMS`; model acceptance is protocol evidence only, not measured RF
output. The separate `hardware/tests/sx1262_driver_config.c` test records and
checks the complete 915-MHz/+14-dBm SPI command sequence byte-for-byte.

`SET_TX` schedules completion using `tx_latency_ms` (30 ms default). An
optional SX126x 24-bit timeout value is converted from 15.625-us ticks; timeout
raises `SX1262_IRQ_TIMEOUT`, successful transmission raises
`SX1262_IRQ_TX_DONE`. Advance virtual time with `sx1262_model_advance()` or
let SPI transactions advance at the current `now_ms`. Configure the IRQ mask
through `SET_DIO_IRQ_PARAMS`; `sx1262_model_irq()` reports the modeled DIO
assertion. Malformed/unsupported commands increment `fault_count`, set
`fault`, and return SX126x invalid-command status (0x08).

## SPI response byte layout

TX begins with the SX126x opcode. For command responses the modeled status is
placed at `rx[1]`, matching the status byte sampled after the opcode phase.
`GET_IRQ_STATUS` returns its MSB/LSB at `rx[2]`/`rx[3]`. `READ_BUFFER` uses the
real offset + dummy-byte framing and returns the first FIFO byte at `rx[3]`.
For a firmware HAL that uses equal TX/RX lengths, send the same number of
dummy bytes as the requested response length. This model does not emulate
electrical timing, BUSY pin edges, RF propagation, CAD, receive demodulation,
or chip reset pin timing. Reset is represented by `sx1262_model_reset()`.

## Build and run

```sh
cmake -S hardware/models/sx1262 -B build/sx1262
cmake --build build/sx1262
ctest --test-dir build/sx1262 --output-on-failure
```

The smoke test configures LoRa and a 915-MHz frequency word, writes and reads
the FIFO, starts TX over the same callback signature as the firmware HAL,
advances time through `TX_DONE`, reads and clears the IRQ, and checks malformed
command handling.

Wokwi Custom Chip integration can wrap this model in a C/WASM chip; the
standalone core has no Wokwi SDK dependency. No Wokwi executable is required
for build or test.
