# Virtual cattle tag firmware (C)

Status: **SIMULATED** with a portable C11 host harness. The firmware is real C
code; host callbacks stand in for board SPI, IMU, IRQ, clock, and sleep drivers.
It is isolated under `hardware/` and does not replace the Python RF system.

The embedded core is `src/tag_firmware.c`, with SX1262 protocol commands in
`src/sx1262.c`. Board ports implement `tag_hal_t` from `include/tag_firmware.h`.
The core initializes the transceiver (standby, LoRa packet/modulation/frequency,
power, packet format, FIFO bases and IRQ mapping), writes the encoded payload to
the FIFO, starts TX, observes TX_DONE/timeout and opens a bounded RX window.
There is no Python implementation of the tag state machine.

## Build and run

```sh
cmake -S hardware/firmware -B build/hardware-firmware
cmake --build build/hardware-firmware
ctest --test-dir build/hardware-firmware --output-on-failure
./build/hardware-firmware/tag_host_demo
```

The small host callback harness exercises boot/self-test, radio configuration,
motion classification, 24-byte packet encoding and CRC, TX_DONE, RX timeout,
and return to sleep. It is a protocol stub, not a claim that silicon or RF
propagation was emulated. A dedicated SX1262 peripheral model and sensor model
can be attached through the HAL in this workspace.

## Interfaces and protocol

`tag_firmware_init()` and `tag_firmware_step()` drive the `BOOT`, `SELF_TEST`,
`SLEEP`, `IMU_MONITORING`, `RF_TX`, `RF_RX`, `ALERT`, and `ERROR_RECOVERY`
states. The HAL has a full-duplex SPI transfer callback, reset, IMU sample and
interrupt, radio IRQ, monotonic time, and sleep. SX1262 command bytes are sent
from C over SPI (`0x80`, `0x98`, `0x8a`, `0x86`, `0x8b`, `0x8c`, `0x95`,
`0x8e`, `0x8f`, `0x08`, `0x0e`, `0x83`, `0x12`, `0x02`, `0x82`). LoRa defaults are SF7/BW125/CR4/5 at
915 MHz and 10 dBm. The setup performs the 902–928 MHz image calibration and
configures the SX1262 high-power PA with `SetPaConfig(04 07 00 01)` before
`SetTxParams`; a driver-level test also verifies the +14 dBm command sequence.
This proves command encoding and model acceptance only. It does not prove
conducted output power: matching network, supply, layout, RF switch, antenna,
region, and legal band plan must be validated on the actual board. Parameters
and the 915 MHz calibration mapping follow [Semtech's SX126x reference driver](https://github.com/Lora-net/LoRaMac-node/blob/master/src/radio/sx126x/sx126x.c)
and [SX1261/2 product datasheet](https://www.semtech.com/products/wireless-rf/lora-connect/sx1262).

Telemetry is little-endian: version (1), behavior (1), tag ID (4), sequence
(4), uptime ms (4), acceleration XYZ mg (6), battery mV (2), CRC-16/CCITT-FALSE
(2). Total is 24 bytes. A valid CRC detects accidental corruption; it is not
authentication or encryption.

This source remains HAL-portable and is integrated with Zephyr `native_sim` and
a Zephyr target adapter for the ST NUCLEO-L031K6. The native C-model cycle and
the ARM target image compile successfully; the image has not been flashed.
Wokwi and custom-chip integration remain experimental future work. A compile
does not validate pin-level electrical behavior, actual radio output, sleep
current, or battery life.
