#include <errno.h>
#include <stdint.h>

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include "lis2dw12_model.h"
#include "sx1262_model.h"
#include "tag_firmware.h"

LOG_MODULE_REGISTER(cattle_tag_sim, LOG_LEVEL_INF);

/* native_sim deliberately keeps the Zephyr idle thread alive after main(). */
extern void nsi_exit(int exit_code);

static sx1262_model_t radio;
static lis2dw12_model_t imu;

static uint32_t now_ms(void)
{
    return k_uptime_get_32();
}

static int spi_transfer(void *context, const uint8_t *tx, size_t tx_len,
                        uint8_t *rx, size_t rx_len)
{
    ARG_UNUSED(context);
    sx1262_model_advance(&radio, now_ms());
    return sx1262_model_transfer(&radio, tx, tx_len, rx, rx_len);
}

static int radio_reset(void *context)
{
    ARG_UNUSED(context);
    sx1262_model_reset(&radio);
    radio.now_ms = now_ms();
    return 0;
}

static int imu_read(void *context, tag_imu_sample_t *sample)
{
    ARG_UNUSED(context);
    uint8_t bytes[6];
    lis2dw12_tick(&imu, 20u);
    if (lis2dw12_i2c_read(&imu, LIS2DW12_REG_OUT_X_L, bytes, sizeof(bytes)) != LIS2DW12_OK) {
        return -EIO;
    }
    const unsigned fs_code = (imu.registers[LIS2DW12_REG_CTRL6] >> 4u) & 3u;
    const int32_t full_scale_g = (int32_t)(2u << fs_code);
    const int16_t axes[] = {
        (int16_t)((uint16_t)bytes[0] | ((uint16_t)bytes[1] << 8u)),
        (int16_t)((uint16_t)bytes[2] | ((uint16_t)bytes[3] << 8u)),
        (int16_t)((uint16_t)bytes[4] | ((uint16_t)bytes[5] << 8u)),
    };
    sample->x_mg = (int16_t)(((int32_t)axes[0] * full_scale_g * 1000) / 32768);
    sample->y_mg = (int16_t)(((int32_t)axes[1] * full_scale_g * 1000) / 32768);
    sample->z_mg = (int16_t)(((int32_t)axes[2] * full_scale_g * 1000) / 32768);
    sample->interrupt_flags = lis2dw12_irq_pending(&imu) ? 0x02u : 0u;
    return 0;
}

static bool imu_irq_pending(void *context)
{
    ARG_UNUSED(context);
    return lis2dw12_irq_pending(&imu);
}

static bool radio_irq_pending(void *context)
{
    ARG_UNUSED(context);
    sx1262_model_advance(&radio, now_ms());
    return sx1262_model_irq(&radio);
}

static uint32_t clock_ms(void *context)
{
    ARG_UNUSED(context);
    return now_ms();
}

static void sleep_ms(void *context, uint32_t duration_ms)
{
    ARG_UNUSED(context);
    k_sleep(K_MSEC(duration_ms));
    const uint32_t time = now_ms();
    lis2dw12_tick(&imu, duration_ms);
    sx1262_model_advance(&radio, time);
}

int main(void)
{
    sx1262_model_init(&radio);
    radio.tx_latency_ms = 8u;
    lis2dw12_init(&imu, NULL, NULL);
    lis2dw12_set_motion(&imu, LIS2DW12_MOTION_GRAZING);

    const tag_hal_t hal = {
        .spi_transfer = spi_transfer,
        .radio_reset = radio_reset,
        .imu_read = imu_read,
        .imu_irq_pending = imu_irq_pending,
        .radio_irq_pending = radio_irq_pending,
        .clock_ms = clock_ms,
        .sleep_ms = sleep_ms,
    };
    tag_config_t config = tag_default_config(0x12345678u);
    config.normal_beacon_ms = 100u;
    config.active_beacon_ms = 50u;
    config.alert_beacon_ms = 25u;

    tag_firmware_t firmware;
    if (tag_firmware_init(&firmware, &hal, &config) != 0) {
        LOG_ERR("firmware HAL initialization failed");
        return -EINVAL;
    }

    for (uint32_t step = 0; step < 1000u; ++step) {
        tag_firmware_step(&firmware);
        if (firmware.packets_sent > 0u && firmware.state == TAG_STATE_SLEEP) {
            break;
        }
    }
    const bool valid = firmware.packets_sent == 1u && firmware.failures == 0u &&
                       tag_telemetry_crc_valid(radio.fifo, TAG_TELEMETRY_MAX_SIZE) &&
                       radio.mode == SX1262_MODE_SLEEP;
    if (!valid) {
        LOG_ERR("native_sim cycle failed: sent=%u failures=%u state=%d radio_mode=%d",
                firmware.packets_sent, firmware.failures, firmware.state, radio.mode);
        nsi_exit(-EIO);
    }
    LOG_INF("SIMULATED native_sim cycle PASS: TX=%u packet=%uB CRC valid; SX1262 asleep",
            firmware.packets_sent, TAG_TELEMETRY_MAX_SIZE);
    nsi_exit(0);
    return 0;
}
