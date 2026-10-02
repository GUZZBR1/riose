#include "tag_firmware.h"
#include "sx1262.h"

#include <string.h>

static uint32_t now_ms(const tag_firmware_t *fw)
{
    return fw->hal.clock_ms(fw->hal.context);
}

void tag_trace_emit(const tag_hal_t *hal, tag_state_t state,
                    tag_trace_event_t event, tag_trace_source_t source,
                    int32_t result, uint32_t value0, uint32_t value1,
                    uint32_t value2)
{
    if (hal == NULL || hal->trace_event == NULL) return;
    const tag_trace_record_t record = {
        .timestamp_us = hal->clock_us != NULL
            ? hal->clock_us(hal->context)
            : hal->clock_ms != NULL
                ? (uint64_t)hal->clock_ms(hal->context) * 1000u : 0u,
        .state = state,
        .event = event,
        .source = source,
        .result = result,
        .value0 = value0,
        .value1 = value1,
        .value2 = value2,
    };
    hal->trace_event(hal->context, &record);
}

void tag_trace_emit_packet(const tag_hal_t *hal, tag_state_t state,
                           const uint8_t *packet, size_t length,
                           uint32_t sequence, uint32_t behavior)
{
    if (hal == NULL || hal->trace_event == NULL || packet == NULL ||
        length == 0u || length > TAG_TELEMETRY_MAX_SIZE) return;
    static const char hex[] = "0123456789abcdef";
    tag_trace_record_t record = {
        .timestamp_us = hal->clock_us != NULL
            ? hal->clock_us(hal->context)
            : hal->clock_ms != NULL
                ? (uint64_t)hal->clock_ms(hal->context) * 1000u : 0u,
        .state = state,
        .event = TAG_TRACE_PACKET_CREATED,
        .source = TAG_TRACE_SOURCE_FIRMWARE,
        .result = 0,
        .value0 = (uint32_t)length,
        .value1 = sequence,
        .value2 = behavior,
    };
    for (size_t i = 0; i < length; ++i) {
        record.packet_hex[i * 2u] = hex[packet[i] >> 4u];
        record.packet_hex[i * 2u + 1u] = hex[packet[i] & 0x0fu];
    }
    hal->trace_event(hal->context, &record);
}

static void set_state(tag_firmware_t *fw, tag_state_t state)
{
    if (fw->state == state) return;
    fw->state = state;
    fw->hal.trace_state = state;
    tag_trace_emit(&fw->hal, state, TAG_TRACE_STATE,
                   TAG_TRACE_SOURCE_FIRMWARE, 0, (uint32_t)state,
                   (uint32_t)fw->behavior, fw->sequence);
    if (fw->hal.state_trace != NULL)
        fw->hal.state_trace(fw->hal.context, state);
}

static void fail(tag_firmware_t *fw)
{
    fw->tx_irq_deadline_ms = 0u;
    fw->rx_irq_deadline_ms = 0u;
    fw->failures++;
    tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_ERROR,
                   TAG_TRACE_SOURCE_FIRMWARE, -1, fw->failures,
                   (uint32_t)fw->behavior, 0u);
    set_state(fw, TAG_STATE_ERROR_RECOVERY);
    fw->recovery_at_ms = now_ms(fw) + 1000u;
}

tag_config_t tag_default_config(uint32_t tag_id)
{
    tag_config_t cfg = {
        .tag_id = tag_id,
        .rf_frequency_hz = 915000000u,
        .tx_power_dbm = 10,
        .normal_beacon_ms = TAG_DEFAULT_BEACON_MS,
        .active_beacon_ms = 60000u,
        .active_burst_ms = 120000u,
        .alert_beacon_ms = 10000u,
        .alert_burst_ms = 120000u,
        .low_battery_beacon_ms = 900000u,
        .still_alert_after_ms = 14400000u,
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
    fw->hal.trace_state = TAG_STATE_BOOT;
    fw->behavior = TAG_BEHAVIOR_NORMAL;
    fw->initialized = true;
    if (fw->hal.state_trace != NULL)
        fw->hal.state_trace(fw->hal.context, TAG_STATE_BOOT);
    tag_trace_emit(&fw->hal, TAG_STATE_BOOT, TAG_TRACE_BOOT,
                   TAG_TRACE_SOURCE_FIRMWARE, 0, fw->config.tag_id,
                   fw->config.rf_frequency_hz, 0u);
    tag_trace_emit(&fw->hal, TAG_STATE_BOOT, TAG_TRACE_MCU_INIT,
                   TAG_TRACE_SOURCE_FIRMWARE, 0, 0u, 0u, 0u);
    return 0;
}

static void sample_imu(tag_firmware_t *fw)
{
    if (fw->hal.imu_read(fw->hal.context, &fw->last_imu) != 0) {
        tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_IMU_READ,
                       TAG_TRACE_SOURCE_HAL, -1, 0u, 0u, 0u);
        fail(fw);
        return;
    }
    tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_IMU_READ,
                   TAG_TRACE_SOURCE_HAL, 0,
                   (uint32_t)(int32_t)fw->last_imu.x_mg,
                   (uint32_t)(int32_t)fw->last_imu.y_mg,
                   (uint32_t)(int32_t)fw->last_imu.z_mg);
    const tag_behavior_t previous_behavior = fw->behavior;
    const int64_t x = fw->last_imu.x_mg;
    const int64_t y = fw->last_imu.y_mg;
    const int64_t z = (int64_t)fw->last_imu.z_mg - 1000;
    const int64_t energy = x * x + y * y + z * z;
    if ((fw->last_imu.interrupt_flags & TAG_IMU_FLAG_WAKE_UP) != 0u ||
        energy > 1800000) {
        fw->still_tracking = false;
        fw->behavior = TAG_BEHAVIOR_ALERT;
        set_state(fw, TAG_STATE_ALERT);
    } else if (energy > 180000) {
        fw->still_tracking = false;
        fw->behavior = TAG_BEHAVIOR_ACTIVE;
        set_state(fw, TAG_STATE_RF_TX);
    } else if (energy < 2500) {
        if (!fw->still_tracking) {
            fw->still_tracking = true;
            fw->still_since_ms = now_ms(fw);
        }
        if ((uint32_t)(now_ms(fw) - fw->still_since_ms) >=
            fw->config.still_alert_after_ms) {
            fw->behavior = TAG_BEHAVIOR_ALERT;
            set_state(fw, TAG_STATE_ALERT);
        } else {
            fw->behavior = TAG_BEHAVIOR_STILL;
            set_state(fw, TAG_STATE_SLEEP);
        }
    } else {
        fw->still_tracking = false;
        fw->behavior = TAG_BEHAVIOR_NORMAL;
        set_state(fw, TAG_STATE_RF_TX);
    }
    /* Escalate quickly for a bounded window, then send sparse heartbeats
     * while the condition persists. This prevents a latched alarm (notably
     * the stillness alarm) from holding the radio in a high-duty-cycle loop. */
    if (fw->behavior == TAG_BEHAVIOR_ALERT &&
        previous_behavior != TAG_BEHAVIOR_ALERT) {
        fw->alert_burst_until_ms = now_ms(fw) + fw->config.alert_burst_ms;
    } else if (fw->behavior != TAG_BEHAVIOR_ALERT) {
        fw->alert_burst_until_ms = 0u;
    }
    if (fw->behavior == TAG_BEHAVIOR_ACTIVE &&
        previous_behavior != TAG_BEHAVIOR_ACTIVE) {
        fw->active_burst_until_ms = now_ms(fw) + fw->config.active_burst_ms;
    } else if (fw->behavior != TAG_BEHAVIOR_ACTIVE) {
        fw->active_burst_until_ms = 0u;
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
    tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_RADIO_STANDBY,
                   TAG_TRACE_SOURCE_SX1262, 0, 0u, 0u, 0u);
    const size_t len = tag_encode_telemetry(fw->tx_packet,
        sizeof(fw->tx_packet), fw->config.tag_id, fw->sequence++, now_ms(fw),
        &fw->last_imu, fw->config.battery_mv, fw->behavior);
    if (len == 0u) {
        fail(fw);
        return;
    }
    fw->tx_packet_len = (uint8_t)len;
    tag_trace_emit_packet(&fw->hal, fw->state, fw->tx_packet, len,
                          fw->sequence - 1u, (uint32_t)fw->behavior);
    if (sx1262_write_buffer(&fw->hal, 0u, fw->tx_packet, len) != 0 ||
        sx1262_set_tx(&fw->hal, 1000u) != 0) {
        fail(fw);
        return;
    }
    fw->next_beacon_ms = now_ms(fw) + fw->config.normal_beacon_ms;
    const uint32_t now = now_ms(fw);
    const bool alert_burst = fw->behavior == TAG_BEHAVIOR_ALERT &&
        fw->config.alert_burst_ms != 0u &&
        (int32_t)(now - fw->alert_burst_until_ms) < 0;
    const bool active_burst = fw->behavior == TAG_BEHAVIOR_ACTIVE &&
        fw->config.active_burst_ms != 0u &&
        (int32_t)(now - fw->active_burst_until_ms) < 0;
    if (alert_burst) {
        fw->next_beacon_ms = now + fw->config.alert_beacon_ms;
    } else if (fw->config.battery_mv < fw->config.low_battery_threshold_mv) {
        fw->next_beacon_ms = now_ms(fw) + fw->config.low_battery_beacon_ms;
    } else if (active_burst) {
        fw->next_beacon_ms = now_ms(fw) + fw->config.active_beacon_ms;
    }
    fw->packets_sent++;
    fw->tx_irq_deadline_ms = now_ms(fw) + 1000u + SX1262_TX_IRQ_GRACE_MS;
    set_state(fw, TAG_STATE_RF_TX);
    tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_TX_START,
                   TAG_TRACE_SOURCE_SX1262, 0, (uint32_t)len,
                   (uint32_t)(int32_t)fw->config.tx_power_dbm,
                   fw->config.rf_frequency_hz);
}

void tag_firmware_step(tag_firmware_t *fw)
{
    if (fw == NULL || !fw->initialized) return;
    switch (fw->state) {
    case TAG_STATE_BOOT:
        set_state(fw, TAG_STATE_SELF_TEST);
        break;
    case TAG_STATE_SELF_TEST:
        if (fw->hal.radio_reset(fw->hal.context) != 0 ||
            fw->hal.imu_read(fw->hal.context, &fw->last_imu) != 0 ||
            sx1262_configure(&fw->hal, fw->config.rf_frequency_hz,
                             fw->config.tx_power_dbm) != 0 ||
            sx1262_set_sleep(&fw->hal) != 0) {
            fail(fw);
        } else {
            set_state(fw, TAG_STATE_SLEEP);
            fw->next_beacon_ms = now_ms(fw);
        }
        break;
    case TAG_STATE_SLEEP:
        if (fw->hal.imu_irq_pending != NULL &&
            fw->hal.imu_irq_pending(fw->hal.context)) {
            tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_WAKE,
                           TAG_TRACE_SOURCE_HAL, 0, 1u, 0u, 0u);
            set_state(fw, TAG_STATE_IMU_MONITORING);
            break;
        }
        if ((int32_t)(now_ms(fw) - fw->next_beacon_ms) >= 0) {
            tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_WAKE,
                           TAG_TRACE_SOURCE_HAL, 0, 0u, 0u, 0u);
            set_state(fw, TAG_STATE_IMU_MONITORING);
            break;
        }
        const uint32_t remaining_ms = fw->next_beacon_ms - now_ms(fw);
        if (fw->hal.wait_for_event != NULL) {
            tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_MCU_SLEEP,
                           TAG_TRACE_SOURCE_HAL, 0, remaining_ms, 1u, 0u);
            fw->hal.wait_for_event(fw->hal.context, remaining_ms);
        } else {
            /* Keep the fast host harness responsive; hardware HALs should
             * implement wait_for_event to sleep until IRQ or beacon timeout. */
            const uint32_t poll_ms = remaining_ms < 10u ? remaining_ms : 10u;
            tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_MCU_SLEEP,
                           TAG_TRACE_SOURCE_HAL, 0, poll_ms, 0u, 0u);
            fw->hal.sleep_ms(fw->hal.context, poll_ms);
        }
        break;
    case TAG_STATE_IMU_MONITORING:
        {
        const bool beacon_due = (int32_t)(now_ms(fw) - fw->next_beacon_ms) >= 0;
        const tag_behavior_t previous_behavior = fw->behavior;
        sample_imu(fw);
        if (fw->state == TAG_STATE_ERROR_RECOVERY) break;
        const bool escalation = fw->behavior > previous_behavior &&
                                fw->behavior >= TAG_BEHAVIOR_ACTIVE;
        if (fw->config.battery_mv < fw->config.low_battery_threshold_mv &&
            fw->behavior != TAG_BEHAVIOR_ALERT &&
            !beacon_due) {
            /* Keep sensing after wake, but suppress ad-hoc transmissions
             * until the extended low-battery beacon interval expires. */
            set_state(fw, TAG_STATE_SLEEP);
            break;
        }
        if (beacon_due || escalation) {
            transmit(fw);
        } else {
            set_state(fw, TAG_STATE_SLEEP);
        }
        break;
        }
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
            tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_IRQ,
                           TAG_TRACE_SOURCE_SX1262, 0, irq, 0u, 0u);
            if ((irq & SX1262_IRQ_TX_DONE) != 0u) {
                fw->tx_irq_deadline_ms = 0u;
                tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_TX_DONE,
                               TAG_TRACE_SOURCE_SX1262, 0, irq,
                               fw->tx_packet_len, 0u);
                set_state(fw, TAG_STATE_RF_RX);
            } else if ((irq & SX1262_IRQ_TIMEOUT) != 0u) {
                tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_TIMEOUT,
                               TAG_TRACE_SOURCE_SX1262, -1, irq,
                               fw->tx_packet_len, 0u);
                fail(fw);
            } else {
                fail(fw);
            }
        } else {
            if (fw->tx_irq_deadline_ms != 0u &&
                (int32_t)(now_ms(fw) - fw->tx_irq_deadline_ms) >= 0) {
                /* DIO1 may be disconnected or suppressed even though the
                 * radio completed its own timeout. Never wait for IRQ forever. */
                fail(fw);
            } else {
                fw->hal.sleep_ms(fw->hal.context, 1u);
            }
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
            fw->rx_irq_deadline_ms = now_ms(fw) + 100u + SX1262_TX_IRQ_GRACE_MS;
            tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_RX_START,
                           TAG_TRACE_SOURCE_SX1262, 0, 100u, 0u, 0u);
        }
        uint16_t irq = 0u;
        if (fw->hal.radio_irq_pending(fw->hal.context)) {
            if (sx1262_get_irq_status(&fw->hal, &irq) != 0 ||
                sx1262_clear_irq_status(&fw->hal, irq) != 0) {
                fail(fw);
                break;
            }
            tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_IRQ,
                           TAG_TRACE_SOURCE_SX1262, 0, irq, 0u, 0u);
            if ((irq & (SX1262_IRQ_RX_DONE | SX1262_IRQ_TIMEOUT)) != 0u) {
                if ((irq & SX1262_IRQ_TIMEOUT) != 0u) {
                    tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_TIMEOUT,
                                   TAG_TRACE_SOURCE_SX1262, -1, irq, 0u, 0u);
                }
                tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_RX_DONE,
                               TAG_TRACE_SOURCE_SX1262, 0, irq, 0u, 0u);
                fw->rx_started = false;
                fw->rx_irq_deadline_ms = 0u;
                if (sx1262_set_sleep(&fw->hal) != 0) {
                    fail(fw);
                } else {
                    tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_RADIO_SLEEP,
                                   TAG_TRACE_SOURCE_SX1262, 0, 0u, 0u, 0u);
                    set_state(fw, TAG_STATE_SLEEP);
                }
            } else {
                fail(fw);
            }
        } else {
            if (fw->rx_irq_deadline_ms != 0u &&
                (int32_t)(now_ms(fw) - fw->rx_irq_deadline_ms) >= 0) {
                fail(fw);
            } else {
                fw->hal.sleep_ms(fw->hal.context, 1u);
            }
        }
        break;
    }
    case TAG_STATE_ERROR_RECOVERY:
        if ((int32_t)(now_ms(fw) - fw->recovery_at_ms) >= 0) {
            tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_RECOVERY,
                           TAG_TRACE_SOURCE_FIRMWARE, 0, fw->failures,
                           (uint32_t)TAG_STATE_SELF_TEST, 0u);
            set_state(fw, TAG_STATE_SELF_TEST);
        } else {
            tag_trace_emit(&fw->hal, fw->state, TAG_TRACE_MCU_SLEEP,
                           TAG_TRACE_SOURCE_HAL, 0, 10u, 0u, 0u);
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
