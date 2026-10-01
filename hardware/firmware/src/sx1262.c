#include "sx1262.h"

#include <limits.h>

static int transfer(const tag_hal_t *hal, const uint8_t *tx, size_t n,
                    uint8_t *rx)
{
    if (hal == NULL || hal->spi_transfer == NULL || n == 0u || n > 260u)
        return -1;
    uint8_t discard[260];
    if (rx == NULL) rx = discard;
    if (hal->spi_transfer(hal->context, tx, n, rx, n) != 0) return -1;
    /* SX126x status command bits are 0x08 (invalid) and 0x0a (failed).
     * Timeout from a completed SetTx is also an error to the firmware. */
    if (n > 1u) {
        const uint8_t command_status = (uint8_t)(rx[1] & 0x0eu);
        if (command_status == 0x06u || command_status == 0x08u ||
            command_status == 0x0au) return -1;
    }
    return 0;
}

static int command(const tag_hal_t *hal, uint8_t opcode,
                   const uint8_t *args, size_t length)
{
    uint8_t tx[260] = {0};
    if (length > sizeof(tx) - 1u) return -1;
    tx[0] = opcode;
    for (size_t i = 0; i < length; ++i) tx[i + 1u] = args[i];
    return transfer(hal, tx, length + 1u, NULL);
}

static uint32_t frequency_word(uint32_t frequency_hz)
{
    /* SX126x PLL step is 32 MHz / 2^25. Rounded to nearest integer word. */
    const uint64_t numerator = (uint64_t)frequency_hz * (1ull << 25) + 16000000ull;
    return (uint32_t)(numerator / 32000000ull);
}

int sx1262_configure(const tag_hal_t *hal, uint32_t frequency_hz,
                     int8_t tx_power_dbm)
{
    if (hal == NULL || frequency_hz < 150000000u || frequency_hz > 960000000u ||
        tx_power_dbm < -9 || tx_power_dbm > 22) return -1;
    const uint8_t standby[] = {0x00u};
    const uint8_t packet_type[] = {0x01u}; /* LoRa */
    const uint32_t word = frequency_word(frequency_hz);
    const uint8_t rf_frequency[] = {
        (uint8_t)(word >> 24), (uint8_t)(word >> 16),
        (uint8_t)(word >> 8), (uint8_t)word
    };
    const uint8_t modulation[] = {0x07u, 0x04u, 0x01u, 0x00u}; /* SF7, 125kHz, CR4/5 */
    const uint8_t packet[] = {0x00u, 0x08u, 0x00u, 0x18u, 0x01u, 0x00u};
    const uint8_t tx_params[] = {(uint8_t)tx_power_dbm, 0x04u}; /* 200 us ramp */
    const uint8_t buffer_base[] = {0x00u, 0x80u};
    const uint8_t irq_params[] = {0x02u,0x03u, 0x02u,0x03u, 0x00u,0x00u, 0x00u,0x00u};
    if (command(hal, 0x80u, standby, sizeof(standby)) != 0 ||
        command(hal, 0x8au, packet_type, sizeof(packet_type)) != 0 ||
        command(hal, 0x86u, rf_frequency, sizeof(rf_frequency)) != 0 ||
        command(hal, 0x8bu, modulation, sizeof(modulation)) != 0 ||
        command(hal, 0x8cu, packet, sizeof(packet)) != 0 ||
        command(hal, 0x8eu, tx_params, sizeof(tx_params)) != 0 ||
        command(hal, 0x8fu, buffer_base, sizeof(buffer_base)) != 0 ||
        command(hal, 0x08u, irq_params, sizeof(irq_params)) != 0) return -1;
    return 0;
}

int sx1262_write_buffer(const tag_hal_t *hal, uint8_t offset,
                        const uint8_t *data, size_t length)
{
    uint8_t tx[260];
    if (data == NULL || length == 0u || length > 255u) return -1;
    tx[0] = 0x0eu; /* WriteBuffer */
    tx[1] = offset;
    for (size_t i = 0; i < length; ++i) tx[i + 2u] = data[i];
    return transfer(hal, tx, length + 2u, NULL);
}

static int set_timeout(const tag_hal_t *hal, uint8_t opcode, uint32_t timeout_ms)
{
    /* Radio timeout units are 15.625 us; zero is continuous RX/TX. */
    uint64_t units = (uint64_t)timeout_ms * 64u;
    if (units > 0xffffffu) units = 0xffffffu;
    const uint8_t args[] = {(uint8_t)(units >> 16),
                            (uint8_t)(units >> 8), (uint8_t)units};
    return command(hal, opcode, args, sizeof(args));
}

int sx1262_set_tx(const tag_hal_t *hal, uint32_t timeout_ms)
{
    return set_timeout(hal, 0x83u, timeout_ms);
}

int sx1262_set_rx(const tag_hal_t *hal, uint32_t timeout_ms)
{
    return set_timeout(hal, 0x82u, timeout_ms);
}

int sx1262_get_irq_status(const tag_hal_t *hal, uint16_t *irq_status)
{
    const uint8_t tx[] = {0x12u, 0x00u, 0x00u, 0x00u};
    uint8_t rx[sizeof(tx)] = {0};
    if (irq_status == NULL || transfer(hal, tx, sizeof(tx), rx) != 0) return -1;
    *irq_status = (uint16_t)(((uint16_t)rx[2] << 8) | rx[3]);
    return 0;
}

int sx1262_clear_irq_status(const tag_hal_t *hal, uint16_t irq_status)
{
    const uint8_t args[] = {(uint8_t)(irq_status >> 8), (uint8_t)irq_status};
    return command(hal, 0x02u, args, sizeof(args));
}
