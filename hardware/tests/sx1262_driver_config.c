#include "sx1262_model.h"
#include "sx1262.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

enum { LOG_CAPACITY = 16, TX_CAPACITY = 12 };

typedef struct {
    sx1262_model_t radio;
    uint8_t bytes[LOG_CAPACITY][TX_CAPACITY];
    size_t lengths[LOG_CAPACITY];
    size_t count;
} capture_t;

static int capture_transfer(void *context, const uint8_t *tx, size_t tx_len,
                            uint8_t *rx, size_t rx_len)
{
    capture_t *capture = context;
    assert(capture->count < LOG_CAPACITY);
    assert(tx_len <= TX_CAPACITY);
    memcpy(capture->bytes[capture->count], tx, tx_len);
    capture->lengths[capture->count++] = tx_len;
    return sx1262_model_transfer(&capture->radio, tx, tx_len, rx, rx_len);
}

static void expect(const capture_t *capture, size_t index,
                   const uint8_t *expected, size_t expected_len)
{
    assert(index < capture->count);
    assert(capture->lengths[index] == expected_len);
    assert(memcmp(capture->bytes[index], expected, expected_len) == 0);
}

int main(void)
{
    capture_t capture = {0};
    sx1262_model_init(&capture.radio);
    const tag_hal_t hal = {.context = &capture, .spi_transfer = capture_transfer};

    /* The default 915-MHz/+14-dBm firmware setting must emit a complete
     * SX1262 setup sequence, consumed by the command-level peripheral model. */
    assert(sx1262_configure(&hal, 915000000u, 14) == 0);
    assert(capture.radio.fault_count == 0u);
    assert(capture.radio.image_calibration[0] == 0xe1u);
    assert(capture.radio.image_calibration[1] == 0xe9u);
    assert(capture.radio.pa_config[0] == 0x04u);
    assert(capture.radio.pa_config[1] == 0x07u);
    assert(capture.radio.pa_config[2] == 0x00u); /* deviceSel: SX1262 */
    assert(capture.radio.pa_config[3] == 0x01u); /* required PA LUT */
    assert(capture.radio.tx_power_dbm == 14u);
    assert(capture.radio.ramp_time == 0x04u);

    const uint8_t standby[] = {0x80, 0x00};
    const uint8_t image_cal[] = {0x98, 0xe1, 0xe9};
    const uint8_t dio2_rf_switch[] = {0x9d, 0x01};
    const uint8_t packet_type[] = {0x8a, 0x01};
    const uint8_t frequency[] = {0x86, 0x39, 0x30, 0x00, 0x00};
    const uint8_t modulation[] = {0x8b, 0x07, 0x04, 0x01, 0x00};
    const uint8_t packet[] = {0x8c, 0x00, 0x08, 0x00, 0x18, 0x01, 0x00};
    const uint8_t pa_config[] = {0x95, 0x04, 0x07, 0x00, 0x01};
    const uint8_t tx_params[] = {0x8e, 0x0e, 0x04};
    const uint8_t buffer_base[] = {0x8f, 0x00, 0x80};
    const uint8_t irq[] = {0x08, 0x02, 0x03, 0x02, 0x03, 0x00, 0x00, 0x00, 0x00};
    const uint8_t *expected[] = {standby, image_cal, dio2_rf_switch, packet_type, frequency,
        modulation, packet, pa_config, tx_params, buffer_base, irq};
    const size_t lengths[] = {sizeof(standby), sizeof(image_cal), sizeof(dio2_rf_switch), sizeof(packet_type),
        sizeof(frequency), sizeof(modulation), sizeof(packet), sizeof(pa_config),
        sizeof(tx_params), sizeof(buffer_base), sizeof(irq)};
    assert(capture.count == sizeof(expected) / sizeof(expected[0]));
    for (size_t i = 0; i < capture.count; ++i)
        expect(&capture, i, expected[i], lengths[i]);

    assert(capture.radio.dio2_rf_switch_enabled);
    puts("SX1262 driver config: PASS (915 MHz image calibration, DIO2 RF switch, SX1262 HP PA, +14 dBm)");
    return 0;
}
