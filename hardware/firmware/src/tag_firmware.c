#include "tag_firmware.h"
#include "sx1262.h"

#include <string.h>

static uint32_t now_ms(const tag_firmware_t *fw)
{
    return fw->hal.clock_ms(fw->hal.context);
}

static void fail(tag_firmware_t *fw)
{
    fw->failures++;
    fw->state = TAG_STATE_ERROR_RECOVERY;
    fw->recovery_at_ms = now_ms(fw) + 1000u;
}

tag_config_t tag_default_config(uint32_t tag_id)
{
    tag_config_t cfg = {
        .tag_id = tag_id,
        .rf_frequency_hz = 915000000u,
        .tx_power_dbm = 10,
        .normal_beacon_ms = TAG_DEFAULT_BEACON_MS,
        .active_beacon_ms = 15000u,
        .alert_beacon_ms = 5000u,
        .low_battery_beacon_ms = 900000u,
        .low_battery_threshold_mv = 2200u,
        .battery_mv = 3000u,
    };
    return cfg;
}

int tag_firmware_init(tag_firmware_t *fw, const tag_hal_t *hal,
                      const tag_config_t *config)
{
    if (fw == NULL || hal == NULL || config == NULL ||
        hal->spi_transfer == NULL || hal->radio_reset == NULL ||
        hal->imu_read == NULL || hal->radio_irq_pending == NULL ||
        hal->clock_ms == NULL || hal->sleep_ms == NULL) {
        return -1;
    }
    memset(fw, 0, sizeof(*fw));
    fw->hal = *hal;
    fw->config = *config;
    fw->state = TAG_STATE_BOOT;
    fw->behavior = TAG_BEHAVIOR_NORMAL;
    fw->initialized = true;
    return 0;
}

static void sample_imu(tag_firmware_t *fw)
{
    if (fw->hal.imu_read(fw->hal.context, &fw->last_imu) != 0) {
        fail(fw);
        return;
    }
    const int64_t x = fw->last_imu.x_mg;
    const int64_t y = fw->last_imu.y_mg;
    const int64_t z = (int64_t)fw->last_imu.z_mg - 1000;
    const int64_t energy = x * x + y * y + z * z;
    if ((fw->last_imu.interrupt_flags & 0x02u) != 0u || energy > 1800000) {
        fw->still_tracking = false;
        fw->behavior = TAG_BEHAVIOR_ALERT;
        fw->state = TAG_STATE_ALERT;
    } else if (energy > 180000) {
        fw->still_tracking = false;
        fw->behavior = TAG_BEHAVIOR_ACTIVE;
        fw->state = TAG_STATE_RF_TX;
    } else if (energy < 2500) {
        if (!fw->still_tracking) {
            fw->still_tracking = true;
            fw->still_since_ms = now_ms(fw);
        }
        if ((uint32_t)(now_ms(fw) - fw->still_since_ms) >= 1800000u) {
            fw->behavior = TAG_BEHAVIOR_ALERT;
            fw->state = TAG_STATE_ALERT;
        } else {
            fw->behavior = TAG_BEHAVIOR_STILL;
            fw->state = TAG_STATE_SLEEP;
        }
    } else {
        fw->still_tracking = false;
        fw->behavior = TAG_BEHAVIOR_NORMAL;
        fw->state = TAG_STATE_RF_TX;
    }
}

static void transmit(tag_firmware_t *fw)
{
    /* The radio is put in hardware sleep whenever the MCU sleeps. Wake it
     * into standby before touching the FIFO or starting a new TX. */
    if (sx1262_set_standby(&fw->hal) != 0) {
        fail(fw);
        return;
    }
    const size_t len = tag_encode_telemetry(fw->tx_packet,
        sizeof(fw->tx_packet), fw->config.tag_id, fw->sequence++, now_ms(fw),
        &fw->last_imu, fw->config.battery_mv, fw->behavior);
    if (len == 0u || sx1262_write_buffer(&fw->hal, 0u, fw->tx_packet, len) != 0 ||
        sx1262_set_tx(&fw->hal, 1000u) != 0) {
        fail(fw);
        return;
    }
    fw->tx_packet_len = (uint8_t)len;
    fw->next_beacon_ms = now_ms(fw) + fw->config.normal_beacon_ms;
    if (fw->behavior == TAG_BEHAVIOR_ALERT) {
        fw->next_beacon_ms = now_ms(fw) + fw->config.alert_beacon_ms;
    } else if (fw->config.battery_mv < fw->config.low_battery_threshold_mv) {
        fw->next_beacon_ms = now_ms(fw) + fw->config.low_battery_beacon_ms;
    } else if (fw->behavior == TAG_BEHAVIOR_ACTIVE) {
        fw->next_beacon_ms = now_ms(fw) + fw->config.active_beacon_ms;
    }
    fw->packets_sent++;
    fw->state = TAG_STATE_RF_TX;
}

void tag_firmware_step(tag_firmware_t *fw)
{
    if (fw == NULL || !fw->initialized) return;
    switch (fw->state) {
    case TAG_STATE_BOOT:
        fw->state = TAG_STATE_SELF_TEST;
        break;
    case TAG_STATE_SELF_TEST:
        if (fw->hal.radio_reset(fw->hal.context) != 0 ||
            fw->hal.imu_read(fw->hal.context, &fw->last_imu) != 0 ||
            sx1262_configure(&fw->hal, fw->config.rf_frequency_hz,
                             fw->config.tx_power_dbm) != 0 ||
            sx1262_set_sleep(&fw->hal) != 0) {
            fail(fw);
        } else {
            fw->state = TAG_STATE_SLEEP;
            fw->next_beacon_ms = now_ms(fw);
        }
        break;
    case TAG_STATE_SLEEP:
        if (fw->hal.imu_irq_pending != NULL &&
            fw->hal.imu_irq_pending(fw->hal.context)) {
            fw->state = TAG_STATE_IMU_MONITORING;
            break;
        }
        if ((int32_t)(now_ms(fw) - fw->next_beacon_ms) >= 0) {
            fw->state = TAG_STATE_IMU_MONITORING;
            break;
        }
        fw->hal.sleep_ms(fw->hal.context, 10u);
        break;
    case TAG_STATE_IMU_MONITORING:
        sample_imu(fw);
        if (fw->config.battery_mv < fw->config.low_battery_threshold_mv &&
            fw->behavior != TAG_BEHAVIOR_ALERT &&
            (int32_t)(now_ms(fw) - fw->next_beacon_ms) < 0) {
            /* Keep sensing after wake, but suppress ad-hoc transmissions
             * until the extended low-battery beacon interval expires. */
            fw->state = TAG_STATE_SLEEP;
            break;
        }
        if (fw->state == TAG_STATE_RF_TX || fw->state == TAG_STATE_ALERT) {
            transmit(fw);
        } else if (fw->state == TAG_STATE_SLEEP) {
            fw->next_beacon_ms = now_ms(fw) + fw->config.normal_beacon_ms;
        }
        break;
    case TAG_STATE_ALERT:
        fw->behavior = TAG_BEHAVIOR_ALERT;
        transmit(fw);
        break;
    case TAG_STATE_RF_TX: {
        uint16_t irq = 0u;
        if (fw->hal.radio_irq_pending(fw->hal.context)) {
            if (sx1262_get_irq_status(&fw->hal, &irq) != 0 ||
                sx1262_clear_irq_status(&fw->hal, irq) != 0) {
                fail(fw);
                break;
            }
            if ((irq & SX1262_IRQ_TX_DONE) != 0u) {
                fw->state = TAG_STATE_RF_RX;
            } else if ((irq & SX1262_IRQ_TIMEOUT) != 0u) {
                fail(fw);
            } else {
                fail(fw);
            }
        } else {
            fw->hal.sleep_ms(fw->hal.context, 1u);
        }
        break;
    }
    case TAG_STATE_RF_RX: {
        if (!fw->rx_started) {
            if (sx1262_set_rx(&fw->hal, 100u) != 0) {
                fail(fw);
                break;
            }
            fw->rx_started = true;
        }
        uint16_t irq = 0u;
        if (fw->hal.radio_irq_pending(fw->hal.context)) {
            if (sx1262_get_irq_status(&fw->hal, &irq) != 0 ||
                sx1262_clear_irq_status(&fw->hal, irq) != 0) {
                fail(fw);
                break;
            }
            if ((irq & (SX1262_IRQ_RX_DONE | SX1262_IRQ_TIMEOUT)) != 0u) {
                fw->rx_started = false;
                if (sx1262_set_sleep(&fw->hal) != 0) {
                    fail(fw);
                } else {
                    fw->state = TAG_STATE_SLEEP;
                }
            } else {
                fail(fw);
            }
        } else {
            fw->hal.sleep_ms(fw->hal.context, 1u);
        }
        break;
    }
    case TAG_STATE_ERROR_RECOVERY:
        if ((int32_t)(now_ms(fw) - fw->recovery_at_ms) >= 0) {
            fw->state = TAG_STATE_SELF_TEST;
        } else {
            fw->hal.sleep_ms(fw->hal.context, 10u);
        }
        break;
    default:
        fail(fw);
        break;
    }
}

tag_state_t tag_firmware_state(const tag_firmware_t *fw)
{
    return fw == NULL ? TAG_STATE_ERROR_RECOVERY : fw->state;
}

static void put_le16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v & 0xffu); p[1] = (uint8_t)(v >> 8);
}
static void put_le32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}
static uint16_t crc16(const uint8_t *p, size_t n)
{
    uint16_t crc = 0xffffu;
    for (size_t i = 0; i < n; ++i) {
        crc ^= (uint16_t)p[i] << 8;
        for (unsigned b = 0; b < 8; ++b)
            crc = (crc & 0x8000u) ? (uint16_t)((crc << 1) ^ 0x1021u) : (uint16_t)(crc << 1);
    }
    return crc;
}

size_t tag_encode_telemetry(uint8_t *out, size_t capacity, uint32_t tag_id,
                            uint32_t sequence, uint32_t timestamp_ms,
                            const tag_imu_sample_t *imu, uint16_t battery_mv,
                            tag_behavior_t behavior)
{
    const size_t len = 22u;
    if (out == NULL || imu == NULL || capacity < len) return 0u;
    out[0] = 1u;
    out[1] = (uint8_t)behavior;
    put_le32(out + 2, tag_id);
    put_le32(out + 6, sequence);
    put_le32(out + 10, timestamp_ms);
    put_le16(out + 14, (uint16_t)imu->x_mg);
    put_le16(out + 16, (uint16_t)imu->y_mg);
    put_le16(out + 18, (uint16_t)imu->z_mg);
    put_le16(out + 20, battery_mv);
    /* The on-air packet is 24 bytes; append CRC after the 22-byte payload. */
    if (capacity < 24u) return 0u;
    const uint16_t crc = crc16(out, len);
    put_le16(out + 22, crc);
    return 24u;
}

bool tag_telemetry_crc_valid(const uint8_t *packet, size_t length)
{
    if (packet == NULL || length != 24u) return false;
    const uint16_t got = (uint16_t)packet[22] | ((uint16_t)packet[23] << 8);
    return crc16(packet, 22u) == got;
}
