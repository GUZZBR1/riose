#ifndef TAG_FIRMWARE_H
#define TAG_FIRMWARE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TAG_TELEMETRY_MAX_SIZE 24u
#define TAG_DEFAULT_BEACON_MS 900000u

typedef enum {
    TAG_STATE_BOOT = 0,
    TAG_STATE_SELF_TEST,
    TAG_STATE_SLEEP,
    TAG_STATE_IMU_MONITORING,
    TAG_STATE_RF_TX,
    TAG_STATE_RF_RX,
    TAG_STATE_ALERT,
    TAG_STATE_ERROR_RECOVERY
} tag_state_t;

typedef enum {
    TAG_BEHAVIOR_STILL = 0,
    TAG_BEHAVIOR_NORMAL = 1,
    TAG_BEHAVIOR_ACTIVE = 2,
    TAG_BEHAVIOR_ALERT = 3
} tag_behavior_t;

typedef struct {
    int16_t x_mg;
    int16_t y_mg;
    int16_t z_mg;
    uint8_t interrupt_flags;
} tag_imu_sample_t;

/* Platform functions are supplied by a board driver or a native test harness.
 * spi_transfer clocks tx_len bytes and captures rx_len bytes; the lengths
 * must match for SPI full-duplex transfers. */
typedef struct {
    void *context;
    int (*spi_transfer)(void *context, const uint8_t *tx, size_t tx_len,
                        uint8_t *rx, size_t rx_len);
    int (*radio_reset)(void *context);
    int (*imu_read)(void *context, tag_imu_sample_t *sample);
    bool (*imu_irq_pending)(void *context);
    bool (*radio_irq_pending)(void *context);
    uint32_t (*clock_ms)(void *context);
    void (*sleep_ms)(void *context, uint32_t duration_ms);
} tag_hal_t;

typedef struct {
    uint32_t tag_id;
    uint32_t rf_frequency_hz;
    int8_t tx_power_dbm;
    uint32_t normal_beacon_ms;
    uint32_t active_beacon_ms;
    uint32_t active_burst_ms;
    uint32_t alert_beacon_ms;
    uint32_t alert_burst_ms;
    uint32_t low_battery_beacon_ms;
    uint32_t still_alert_after_ms;
    uint16_t low_battery_threshold_mv;
    uint16_t battery_mv;
} tag_config_t;

typedef struct {
    tag_hal_t hal;
    tag_config_t config;
    tag_state_t state;
    tag_behavior_t behavior;
    tag_imu_sample_t last_imu;
    uint32_t sequence;
    uint32_t next_beacon_ms;
    uint32_t recovery_at_ms;
    uint8_t tx_packet[TAG_TELEMETRY_MAX_SIZE];
    uint8_t tx_packet_len;
    uint32_t packets_sent;
    uint32_t failures;
    uint32_t still_since_ms;
    uint32_t active_burst_until_ms;
    uint32_t alert_burst_until_ms;
    bool initialized;
    bool rx_started;
    bool still_tracking;
} tag_firmware_t;

tag_config_t tag_default_config(uint32_t tag_id);
int tag_firmware_init(tag_firmware_t *firmware, const tag_hal_t *hal,
                      const tag_config_t *config);
void tag_firmware_step(tag_firmware_t *firmware);
tag_state_t tag_firmware_state(const tag_firmware_t *firmware);

/* Compact little-endian wire packet: version, flags, tag id, sequence,
 * uptime-ms, accel xyz in mg, battery mV, CRC-16/CCITT-FALSE. */
size_t tag_encode_telemetry(uint8_t *out, size_t capacity, uint32_t tag_id,
                            uint32_t sequence, uint32_t timestamp_ms,
                            const tag_imu_sample_t *imu, uint16_t battery_mv,
                            tag_behavior_t behavior);
bool tag_telemetry_crc_valid(const uint8_t *packet, size_t length);

#ifdef __cplusplus
}
#endif
#endif
