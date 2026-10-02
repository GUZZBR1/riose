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
#define TAG_IMU_FLAG_WAKE_UP 0x02u

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

/* Stable machine-readable events for simulated execution traces. Timestamps
 * are virtual microseconds; values are event-specific and never measurements. */
typedef enum {
    TAG_TRACE_BOOT = 1,
    TAG_TRACE_MCU_INIT,
    TAG_TRACE_STATE,
    TAG_TRACE_IMU_READ,
    TAG_TRACE_PACKET_CREATED,
    TAG_TRACE_RADIO_STANDBY,
    TAG_TRACE_TX_START,
    TAG_TRACE_TX_DONE,
    TAG_TRACE_RX_START,
    TAG_TRACE_RX_DONE,
    TAG_TRACE_RADIO_SLEEP,
    TAG_TRACE_ERROR,
    TAG_TRACE_RECOVERY,
    TAG_TRACE_MCU_SLEEP,
    TAG_TRACE_WAKE,
    TAG_TRACE_SPI,
    TAG_TRACE_IRQ,
    TAG_TRACE_TIMEOUT,
    TAG_TRACE_WATCHDOG,
    TAG_TRACE_REBOOT
} tag_trace_event_t;

typedef enum {
    TAG_TRACE_SOURCE_FIRMWARE = 1,
    TAG_TRACE_SOURCE_SX1262 = 2,
    TAG_TRACE_SOURCE_HAL = 3
} tag_trace_source_t;

typedef struct {
    uint64_t timestamp_us;
    tag_state_t state;
    tag_trace_event_t event;
    tag_trace_source_t source;
    int32_t result;
    uint32_t value0;
    uint32_t value1;
    uint32_t value2;
    char packet_hex[TAG_TELEMETRY_MAX_SIZE * 2u + 1u];
} tag_trace_record_t;

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
    /* Optional active-high SX126x BUSY pin. The common driver bounds waits. */
    int (*radio_busy)(void *context);
    int (*imu_read)(void *context, tag_imu_sample_t *sample);
    bool (*imu_irq_pending)(void *context);
    bool (*radio_irq_pending)(void *context);
    uint32_t (*clock_ms)(void *context);
    void (*sleep_ms)(void *context, uint32_t duration_ms);
    /* Optional interrupt/event wait. Returns after an event or timeout. */
    void (*wait_for_event)(void *context, uint32_t timeout_ms);
    /* Optional low-overhead state marker for logic-analyzer captures. */
    void (*state_trace)(void *context, tag_state_t state);
    /* Optional structured trace sink. It must not block or retain record. */
    void (*trace_event)(void *context, const tag_trace_record_t *record);
    /* Current FSM state lets lower-level drivers annotate bus events. */
    tag_state_t trace_state;
    /* Optional monotonic microsecond clock; otherwise clock_ms is scaled. */
    uint64_t (*clock_us)(void *context);
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
    uint32_t tx_irq_deadline_ms;
    uint32_t rx_irq_deadline_ms;
} tag_firmware_t;

tag_config_t tag_default_config(uint32_t tag_id);
int tag_firmware_init(tag_firmware_t *firmware, const tag_hal_t *hal,
                      const tag_config_t *config);
void tag_firmware_step(tag_firmware_t *firmware);
tag_state_t tag_firmware_state(const tag_firmware_t *firmware);
void tag_trace_emit(const tag_hal_t *hal, tag_state_t state,
                   tag_trace_event_t event, tag_trace_source_t source,
                   int32_t result, uint32_t value0, uint32_t value1,
                   uint32_t value2);
void tag_trace_emit_packet(const tag_hal_t *hal, tag_state_t state,
                           const uint8_t *packet, size_t length,
                           uint32_t sequence, uint32_t behavior);

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
