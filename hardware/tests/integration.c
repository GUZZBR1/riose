#include "lis2dw12_model.h"
#include "sx1262_model.h"
#include "tag_firmware.h"

#include <assert.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

enum { DAY_MS = 24 * 60 * 60 * 1000 };

typedef struct {
    sx1262_model_t radio;
    lis2dw12_model_t imu;
    tag_firmware_t *firmware;
    uint32_t now_ms;
    uint32_t imu_bus_failures;
    uint32_t spi_bus_failures;
    uint32_t reset_count;
    uint32_t standby_commands;
    uint32_t sleep_commands;
    uint32_t tx_commands;
    uint32_t rx_commands;
    bool saw_tx_done_irq;
    bool saw_timeout_irq;
    uint8_t last_packet[TAG_TELEMETRY_MAX_SIZE];
    size_t last_packet_len;
    uint16_t power_mv;
} virtual_tag_t;

static void record_packet(virtual_tag_t *tag)
{
    const uint8_t *fifo = tag->radio.fifo;
    const size_t len = TAG_TELEMETRY_MAX_SIZE;
    memcpy(tag->last_packet, fifo, len);
    tag->last_packet_len = len;
}

static int virtual_spi_transfer(void *context, const uint8_t *tx, size_t tx_len,
                                uint8_t *rx, size_t rx_len)
{
    virtual_tag_t *tag = (virtual_tag_t *)context;
    if (tag->spi_bus_failures > 0u) {
        --tag->spi_bus_failures;
        return -1;
    }
    if (tx != NULL && tx_len > 0u) {
        switch (tx[0]) {
        case 0x80u: ++tag->standby_commands; break; /* SetStandby */
        case 0x84u: ++tag->sleep_commands; break;   /* SetSleep */
        case 0x83u: ++tag->tx_commands; break;      /* SetTx */
        case 0x82u: ++tag->rx_commands; break;      /* SetRx */
        default: break;
        }
    }
    const int result = sx1262_model_transfer(&tag->radio, tx, tx_len, rx, rx_len);
    if (result == 0 && tx != NULL && tx_len > 0u && tx[0] == 0x0eu)
        record_packet(tag);
    if (result == 0 && tx != NULL && tx_len == 4u && tx[0] == 0x12u && rx != NULL) {
        const uint16_t irq = (uint16_t)(((uint16_t)rx[2] << 8u) | rx[3]);
        tag->saw_tx_done_irq |= (irq & SX1262_IRQ_TX_DONE) != 0u;
        tag->saw_timeout_irq |= (irq & SX1262_IRQ_TIMEOUT) != 0u;
    }
    return result;
}

static int virtual_radio_reset(void *context)
{
    virtual_tag_t *tag = (virtual_tag_t *)context;
    const uint32_t latency = tag->radio.tx_latency_ms;
    sx1262_model_reset(&tag->radio);
    tag->radio.tx_latency_ms = latency;
    tag->radio.now_ms = tag->now_ms;
    ++tag->reset_count;
    return 0;
}

static int virtual_imu_read(void *context, tag_imu_sample_t *sample)
{
    virtual_tag_t *tag = (virtual_tag_t *)context;
    uint8_t bytes[6];
    if (tag->imu_bus_failures > 0u) {
        --tag->imu_bus_failures;
        lis2dw12_fail_next_i2c(&tag->imu, 1u);
    }
    lis2dw12_tick(&tag->imu, 20u);
    if (lis2dw12_i2c_read(&tag->imu, LIS2DW12_REG_OUT_X_L,
                          bytes, sizeof(bytes)) != LIS2DW12_OK) {
        return -1;
    }
    const unsigned fs_code = (tag->imu.registers[LIS2DW12_REG_CTRL6] >> 4u) & 3u;
    const int32_t full_scale_g = (int32_t)(2u << fs_code);
    const int16_t x = (int16_t)((uint16_t)bytes[0] | ((uint16_t)bytes[1] << 8u));
    const int16_t y = (int16_t)((uint16_t)bytes[2] | ((uint16_t)bytes[3] << 8u));
    const int16_t z = (int16_t)((uint16_t)bytes[4] | ((uint16_t)bytes[5] << 8u));
    sample->x_mg = (int16_t)(((int32_t)x * full_scale_g * 1000) / 32768);
    sample->y_mg = (int16_t)(((int32_t)y * full_scale_g * 1000) / 32768);
    sample->z_mg = (int16_t)(((int32_t)z * full_scale_g * 1000) / 32768);
    sample->interrupt_flags = lis2dw12_irq_pending(&tag->imu) ? 0x02u : 0u;
    if (sample->interrupt_flags != 0u) {
        uint8_t source = 0u;
        (void)lis2dw12_i2c_read(&tag->imu, LIS2DW12_REG_WAKE_UP_SRC, &source, 1u);
    }
    return 0;
}

static bool virtual_imu_irq_pending(void *context)
{
    return lis2dw12_irq_pending(&((virtual_tag_t *)context)->imu);
}

static bool virtual_radio_irq_pending(void *context)
{
    return sx1262_model_irq(&((virtual_tag_t *)context)->radio);
}

static uint32_t virtual_clock_ms(void *context)
{
    return ((virtual_tag_t *)context)->now_ms;
}

static void virtual_sleep_ms(void *context, uint32_t duration_ms)
{
    virtual_tag_t *tag = (virtual_tag_t *)context;
    uint32_t delta = duration_ms;
    /* During MCU sleep, leap to the firmware's next scheduled beacon. This
     * keeps a 24-hour firmware run to beacon-scale work, while TX/RX deadlines
     * still advance in 1-ms steps through the same peripheral models. */
    if (tag->radio.tx_pending || tag->radio.rx_pending) {
        uint32_t event_at = tag->radio.tx_due_ms;
        const uint32_t timeout_at = tag->radio.tx_started_ms + tag->radio.tx_timeout_ms;
        if ((int32_t)(timeout_at - event_at) < 0) event_at = timeout_at;
        const uint32_t until_event = event_at - tag->now_ms;
        if ((int32_t)until_event > (int32_t)delta) delta = until_event;
    }
    if (tag->firmware != NULL && tag->firmware->state == TAG_STATE_SLEEP &&
        tag->radio.mode == SX1262_MODE_SLEEP) {
        const uint32_t until_beacon = tag->firmware->next_beacon_ms - tag->now_ms;
        if ((int32_t)until_beacon > (int32_t)delta) delta = until_beacon;
    }
    tag->now_ms += delta;
    lis2dw12_tick(&tag->imu, delta);
    sx1262_model_advance(&tag->radio, tag->now_ms);
}

static tag_hal_t virtual_hal(virtual_tag_t *tag)
{
    const tag_hal_t hal = {
        .context = tag,
        .spi_transfer = virtual_spi_transfer,
        .radio_reset = virtual_radio_reset,
        .imu_read = virtual_imu_read,
        .imu_irq_pending = virtual_imu_irq_pending,
        .radio_irq_pending = virtual_radio_irq_pending,
        .clock_ms = virtual_clock_ms,
        .sleep_ms = virtual_sleep_ms,
    };
    return hal;
}

static void virtual_tag_init(virtual_tag_t *tag, tag_firmware_t *firmware,
                             tag_config_t *config, uint32_t latency_ms)
{
    memset(tag, 0, sizeof(*tag));
    tag->firmware = firmware;
    tag->power_mv = config->battery_mv;
    sx1262_model_init(&tag->radio);
    tag->radio.tx_latency_ms = latency_ms;
    lis2dw12_init(&tag->imu, NULL, NULL);
    const uint8_t ctrl1 = 0x30u; /* 25-Hz ODR; output generation enabled. */
    const uint8_t wake_route = 0x08u;
    const uint8_t wake_threshold = 0x04u;
    assert(lis2dw12_i2c_write(&tag->imu, LIS2DW12_REG_CTRL1, &ctrl1, 1u) == LIS2DW12_OK);
    assert(lis2dw12_i2c_write(&tag->imu, LIS2DW12_REG_CTRL4_INT1_PAD_CTRL,
                              &wake_route, 1u) == LIS2DW12_OK);
    assert(lis2dw12_i2c_write(&tag->imu, LIS2DW12_REG_WAKE_UP_THS,
                              &wake_threshold, 1u) == LIS2DW12_OK);
    const tag_hal_t hal = virtual_hal(tag);
    assert(tag_firmware_init(firmware, &hal, config) == 0);
}

static bool step_until_state(tag_firmware_t *firmware, tag_state_t target,
                             uint32_t max_steps)
{
    for (uint32_t i = 0; i < max_steps; ++i) {
        if (firmware->state == target) return true;
        tag_firmware_step(firmware);
    }
    return firmware->state == target;
}

static bool step_until_packet_and_sleep(tag_firmware_t *firmware,
                                        uint32_t prior_packets,
                                        uint32_t max_steps)
{
    for (uint32_t i = 0; i < max_steps; ++i) {
        if (firmware->packets_sent > prior_packets && firmware->state == TAG_STATE_SLEEP)
            return true;
        tag_firmware_step(firmware);
    }
    return firmware->packets_sent > prior_packets && firmware->state == TAG_STATE_SLEEP;
}

static void test_boot_packet_sleep_and_wake(void)
{
    virtual_tag_t tag;
    tag_firmware_t firmware;
    tag_config_t config = tag_default_config(0x12345678u);
    config.battery_mv = 2180u; /* static low-battery telemetry; no policy is implied */
    config.normal_beacon_ms = 100u;
    config.active_beacon_ms = 50u;
    config.alert_beacon_ms = 25u;
    virtual_tag_init(&tag, &firmware, &config, 7u);

    assert(firmware.state == TAG_STATE_BOOT);
    tag_firmware_step(&firmware);
    assert(firmware.state == TAG_STATE_SELF_TEST);
    tag_firmware_step(&firmware);
    assert(firmware.state == TAG_STATE_SLEEP);
    assert(tag.reset_count == 1u);
    assert(tag.radio.mode == SX1262_MODE_SLEEP);
    assert(tag.radio.rf_frequency_word != 0u);

    const uint8_t irq_route_off = 0u;
    assert(lis2dw12_i2c_write(&tag.imu, LIS2DW12_REG_CTRL4_INT1_PAD_CTRL,
                              &irq_route_off, 1u) == LIS2DW12_OK);
    lis2dw12_set_motion(&tag.imu, LIS2DW12_MOTION_WALKING);
    assert(step_until_packet_and_sleep(&firmware, 0u, 1000u));
    assert(firmware.packets_sent >= 1u);
    assert(tag.tx_commands >= 1u && tag.rx_commands >= 1u);
    assert(tag.standby_commands >= 2u); /* self-test config and radio wake */
    assert(tag.sleep_commands >= 2u);   /* after self-test and RX completion */
    assert(tag.radio.mode == SX1262_MODE_SLEEP);
    assert(firmware.state == TAG_STATE_SLEEP);
    assert(tag.last_packet_len == 24u);
    assert(tag_telemetry_crc_valid(tag.last_packet, tag.last_packet_len));
    assert(memcmp(tag.last_packet + 2, "\x78\x56\x34\x12", 4u) == 0);
    assert(tag.last_packet[20] == (uint8_t)(config.battery_mv & 0xffu));
    assert(tag.last_packet[21] == (uint8_t)(config.battery_mv >> 8u));
    assert(config.battery_mv < config.low_battery_threshold_mv);
    assert(firmware.next_beacon_ms == config.low_battery_beacon_ms);

    /* A LIS2DW12 wake IRQ must bring firmware out of hardware sleep and produce
     * an alert packet; the adapter consumes the sensor's latched source. */
    const uint8_t irq_route_on = 0x08u;
    assert(lis2dw12_i2c_write(&tag.imu, LIS2DW12_REG_CTRL4_INT1_PAD_CTRL,
                              &irq_route_on, 1u) == LIS2DW12_OK);
    lis2dw12_set_motion(&tag.imu, LIS2DW12_MOTION_RUNNING);
    lis2dw12_tick(&tag.imu, 100u);
    assert(lis2dw12_irq_pending(&tag.imu));
    const uint32_t prior_packets = firmware.packets_sent;
    tag_firmware_step(&firmware); /* SLEEP -> IMU_MONITORING from wake IRQ */
    assert(firmware.state == TAG_STATE_IMU_MONITORING);
    tag_firmware_step(&firmware); /* sample, classify alert, wake, transmit */
    assert(firmware.packets_sent == prior_packets + 1u);
    assert(firmware.behavior == TAG_BEHAVIOR_ALERT);
    assert(firmware.state == TAG_STATE_RF_TX);
    assert(tag.radio.mode == SX1262_MODE_TX);
    assert(tag.standby_commands >= 3u);
    assert(tag_telemetry_crc_valid(tag.last_packet, tag.last_packet_len));
    assert(tag.last_packet[1] == TAG_BEHAVIOR_ALERT);
    assert(!lis2dw12_irq_pending(&tag.imu));
}

static void test_imu_failure_recovery(void)
{
    virtual_tag_t tag;
    tag_firmware_t firmware;
    tag_config_t config = tag_default_config(7u);
    config.normal_beacon_ms = 100u;
    virtual_tag_init(&tag, &firmware, &config, 5u);
    tag_firmware_step(&firmware);
    tag_firmware_step(&firmware);
    assert(firmware.state == TAG_STATE_SLEEP);
    tag.imu_bus_failures = 1u;
    tag_firmware_step(&firmware); /* SLEEP -> IMU_MONITORING */
    tag_firmware_step(&firmware); /* initial due sample fails */
    assert(firmware.state == TAG_STATE_ERROR_RECOVERY);
    assert(firmware.failures == 1u);
    assert(step_until_state(&firmware, TAG_STATE_SLEEP, 500u));
    assert(tag.reset_count >= 2u);
}

static void test_radio_fault_recovery(void)
{
    virtual_tag_t tag;
    tag_firmware_t firmware;
    tag_config_t config = tag_default_config(8u);
    config.normal_beacon_ms = 100u;
    virtual_tag_init(&tag, &firmware, &config, 5u);
    tag_firmware_step(&firmware);
    tag_firmware_step(&firmware);
    assert(firmware.state == TAG_STATE_SLEEP);
    lis2dw12_set_motion(&tag.imu, LIS2DW12_MOTION_WALKING);
    tag.spi_bus_failures = 1u;
    assert(step_until_state(&firmware, TAG_STATE_ERROR_RECOVERY, 100u));
    assert(firmware.failures == 1u);
    assert(step_until_state(&firmware, TAG_STATE_SLEEP, 500u));
    assert(tag.reset_count >= 2u);
}

static void test_missing_tx_done_timeout(void)
{
    virtual_tag_t tag;
    tag_firmware_t firmware;
    tag_config_t config = tag_default_config(9u);
    config.normal_beacon_ms = 100u;
    virtual_tag_init(&tag, &firmware, &config, 1500u); /* beyond SetTx timeout */
    tag_firmware_step(&firmware);
    tag_firmware_step(&firmware);
    assert(firmware.state == TAG_STATE_SLEEP);
    lis2dw12_set_motion(&tag.imu, LIS2DW12_MOTION_WALKING);
    assert(step_until_state(&firmware, TAG_STATE_ERROR_RECOVERY, 2500u));
    assert(firmware.failures >= 1u);
    assert(tag.saw_timeout_irq);
    assert(!tag.saw_tx_done_irq);
}

static lis2dw12_motion_t motion_for_time(uint32_t time_ms)
{
    const uint32_t h = time_ms / (6u * 60u * 60u * 1000u);
    switch (h) {
    case 0u: return LIS2DW12_MOTION_STATIONARY;
    case 1u: return LIS2DW12_MOTION_WALKING;
    case 2u: return LIS2DW12_MOTION_RUNNING;
    case 3u: return LIS2DW12_MOTION_ABNORMAL;
    default: return LIS2DW12_MOTION_STATIONARY;
    }
}

static void test_accelerated_24h(void)
{
    virtual_tag_t tag;
    tag_firmware_t firmware;
    tag_config_t config = tag_default_config(1001u);
    config.normal_beacon_ms = 60000u;
    config.active_beacon_ms = 15000u;
    config.alert_beacon_ms = 5000u;
    virtual_tag_init(&tag, &firmware, &config, 4u);
    /* This long run validates scheduled sensing/beacons across profiles. The
     * separate wake test above exercises IRQ routing; disabling INT1 here
     * prevents every gait phase from being mislabeled as a panic alert. */
    const uint8_t irq_route_off = 0u;
    assert(lis2dw12_i2c_write(&tag.imu, LIS2DW12_REG_CTRL4_INT1_PAD_CTRL,
                              &irq_route_off, 1u) == LIS2DW12_OK);

    uint32_t max_state_transitions = 0u;
    bool seen_behavior[4] = {false, false, false, false};
    bool seen_motion[5] = {false, false, false, false, false};
    uint32_t tx_by_phase[5] = {0u, 0u, 0u, 0u, 0u};
    uint32_t tx_due_by_phase[5] = {0u, 0u, 0u, 0u, 0u};
    uint32_t tx_escalation_by_phase[5] = {0u, 0u, 0u, 0u, 0u};
    tag_state_t prior = firmware.state;
    for (uint32_t steps = 0; tag.now_ms < DAY_MS && steps < 1000000u; ++steps) {
        const lis2dw12_motion_t motion = motion_for_time(tag.now_ms);
        lis2dw12_set_motion(&tag.imu, motion);
        seen_motion[motion] = true;
        const uint32_t packets_before = firmware.packets_sent;
        const bool due_before = (int32_t)(tag.now_ms - firmware.next_beacon_ms) >= 0;
        tag_firmware_step(&firmware);
        if (firmware.packets_sent > packets_before) {
            const uint32_t hour = tag.now_ms / (60u * 60u * 1000u);
            const unsigned phase = hour < 6u ? 0u : hour < 12u ? 1u :
                                   hour < 18u ? 2u : hour < 21u ? 3u : 4u;
            ++tx_by_phase[phase];
            if (due_before) ++tx_due_by_phase[phase];
            else ++tx_escalation_by_phase[phase];
        }
        seen_behavior[firmware.behavior] = true;
        if (firmware.state != prior) {
            ++max_state_transitions;
            prior = firmware.state;
        }
        assert(firmware.state != TAG_STATE_ERROR_RECOVERY);
    }
    if (tag.now_ms < DAY_MS)
        fprintf(stderr, "24h short now=%u state=%d next=%u packets=%u\n",
                tag.now_ms, firmware.state, firmware.next_beacon_ms, firmware.packets_sent);
    assert(tag.now_ms >= DAY_MS);
    assert(firmware.packets_sent > 100u);
    assert(tag.radio.tx_count == firmware.packets_sent);
    assert(firmware.failures == 0u);
    assert(max_state_transitions > 100u);
    assert(seen_motion[LIS2DW12_MOTION_STATIONARY]);
    assert(seen_motion[LIS2DW12_MOTION_WALKING]);
    assert(seen_motion[LIS2DW12_MOTION_RUNNING]);
    assert(seen_motion[LIS2DW12_MOTION_ABNORMAL]);
    assert(seen_behavior[TAG_BEHAVIOR_STILL]);
    assert(seen_behavior[TAG_BEHAVIOR_NORMAL]);
    assert(seen_behavior[TAG_BEHAVIOR_ACTIVE]);
    assert(seen_behavior[TAG_BEHAVIOR_ALERT]);
    assert(tag_telemetry_crc_valid(tag.last_packet, tag.last_packet_len));
    printf("24h mixed (INT1 disabled): simulated=%" PRIu32
           " ms TX=%" PRIu32 " stationary=%" PRIu32 " walking=%" PRIu32
           " running=%" PRIu32 " abnormal=%" PRIu32 " late-stationary=%" PRIu32
           " failures=%" PRIu32 "\n", tag.now_ms, firmware.packets_sent,
           tx_by_phase[0], tx_by_phase[1], tx_by_phase[2], tx_by_phase[3],
           tx_by_phase[4], firmware.failures);
    printf("24h TX origin: deadline=%" PRIu32 " escalation/event=%" PRIu32
           "\n", tx_due_by_phase[0] + tx_due_by_phase[1] + tx_due_by_phase[2] +
           tx_due_by_phase[3] + tx_due_by_phase[4],
           tx_escalation_by_phase[0] + tx_escalation_by_phase[1] +
           tx_escalation_by_phase[2] + tx_escalation_by_phase[3] +
           tx_escalation_by_phase[4]);
}

static void test_healthy_stationary_below_alarm_threshold(void)
{
    const uint32_t healthy_window_ms = 3u * 60u * 60u * 1000u;
    virtual_tag_t tag;
    tag_firmware_t firmware;
    tag_config_t config = tag_default_config(1003u);
    virtual_tag_init(&tag, &firmware, &config, 4u);
    const uint8_t irq_route_off = 0u;
    assert(lis2dw12_i2c_write(&tag.imu, LIS2DW12_REG_CTRL4_INT1_PAD_CTRL,
                              &irq_route_off, 1u) == LIS2DW12_OK);
    for (uint32_t steps = 0; tag.now_ms < healthy_window_ms && steps < 20000u; ++steps) {
        lis2dw12_set_motion(&tag.imu, LIS2DW12_MOTION_STATIONARY);
        tag_firmware_step(&firmware);
        assert(firmware.state != TAG_STATE_ERROR_RECOVERY);
    }
    assert(tag.now_ms >= healthy_window_ms);
    assert(healthy_window_ms < config.still_alert_after_ms);
    assert(firmware.behavior == TAG_BEHAVIOR_STILL);
    printf("3h healthy stationary: TX=%" PRIu32 " (60-s period, alert threshold=%"
           PRIu32 " ms)\n", firmware.packets_sent, config.still_alert_after_ms);
    assert(firmware.packets_sent >= 178u && firmware.packets_sent <= 181u);
}

static void test_stationary_24h_beacon_baseline(void)
{
    virtual_tag_t tag;
    tag_firmware_t firmware;
    tag_config_t config = tag_default_config(1002u);
    virtual_tag_init(&tag, &firmware, &config, 4u);
    const uint8_t irq_route_off = 0u;
    assert(lis2dw12_i2c_write(&tag.imu, LIS2DW12_REG_CTRL4_INT1_PAD_CTRL,
                              &irq_route_off, 1u) == LIS2DW12_OK);
    for (uint32_t steps = 0; tag.now_ms < DAY_MS && steps < 500000u; ++steps) {
        lis2dw12_set_motion(&tag.imu, LIS2DW12_MOTION_STATIONARY);
        tag_firmware_step(&firmware);
        assert(firmware.state != TAG_STATE_ERROR_RECOVERY);
    }
    assert(tag.now_ms >= DAY_MS);
    printf("24h stationary alert profile: simulated=%" PRIu32
           " ms TX=%" PRIu32 " threshold_ms=%" PRIu32
           " alert_period_ms=%" PRIu32 " final_behavior=%u\n",
           tag.now_ms, firmware.packets_sent, config.still_alert_after_ms,
           config.alert_beacon_ms, (unsigned)firmware.behavior);
    assert(firmware.packets_sent > 1400u);
    assert(firmware.behavior == TAG_BEHAVIOR_ALERT);
}

int main(void)
{
    test_boot_packet_sleep_and_wake();
    test_imu_failure_recovery();
    test_radio_fault_recovery();
    test_missing_tx_done_timeout();
    test_accelerated_24h();
    test_healthy_stationary_below_alarm_threshold();
    test_stationary_24h_beacon_baseline();
    puts("Hardware integration: 7 scenarios passed");
    puts("Power coverage: battery voltage is a static telemetry input only; brownout is unsupported by tag_hal_t.");
    return 0;
}
