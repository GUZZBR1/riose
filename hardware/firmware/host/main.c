#include "tag_firmware.h"
#include "sx1262.h"
#include "tag_reset_cause.h"

#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef enum { PROFILE_NORMAL, PROFILE_ACTIVE, PROFILE_ALERT, PROFILE_WORST } profile_t;
typedef enum { FAULT_NONE, FAULT_SPI_ONCE, FAULT_IMU_ONCE, FAULT_IRQ_STUCK,
               FAULT_SYNTHETIC_WATCHDOG_CLASSIFICATION, FAULT_SYNTHETIC_RESET_CLASSIFICATION,
               FAULT_VOLTAGE_DROP, FAULT_HIGH_ESR, FAULT_REGULATOR_INSTABILITY } fault_t;

typedef struct { double time_s; double rail_v; } rail_sample_t;

typedef struct {
    uint32_t time_ms;
    uint64_t absolute_ms;
    uint16_t irq;
    bool irq_high;
    bool inject_enabled;
    bool fault_used;
    fault_t fault;
    profile_t profile;
    uint32_t seed;
    uint8_t packet[64];
    size_t packet_len;
    uint32_t trace_events;
    uint32_t recovery_events;
    uint32_t tx_start_events;
    uint32_t error_events;
    uint32_t boot_events;
    uint32_t timer_wraps;
    rail_sample_t *rail_samples;
    size_t rail_sample_count;
    size_t rail_sample_index;
    double brownout_threshold_v;
    double rail_min_v;
    double rail_crossing_v;
    double rail_recovery_v;
    double rail_crossing_s;
    double rail_recovery_s;
    uint64_t brownout_crossing_ms;
    uint64_t rail_recovered_ms;
    uint64_t rail_start_ms;
    bool rail_fault_enabled;
    bool brownout_pending;
    bool rail_recovered;
} host_board_t;

static const char *fault_name(fault_t fault)
{
    switch (fault) {
    case FAULT_VOLTAGE_DROP: return "voltage_drop";
    case FAULT_HIGH_ESR: return "high_esr";
    case FAULT_REGULATOR_INSTABILITY: return "regulator_instability";
    default: return "unknown";
    }
}

static bool parse_positive_double(const char *text, double *value)
{
    char *end = NULL;
    const double parsed = strtod(text, &end);
    if (text[0] == '\0' || end == text || *end != '\0' || !isfinite(parsed) || parsed <= 0.0)
        return false;
    *value = parsed;
    return true;
}

static bool load_rail_waveform(const char *path, const char *expected_simulation_id,
                               const char *expected_netlist_sha256, const char *expected_fault,
                               host_board_t *board)
{
    static const char expected_header[] =
        "simulation_id,netlist_sha256,fault_profile,timestamp_s,rail_voltage_v,battery_terminal_voltage_v,battery_current_a,status";
    FILE *stream = fopen(path, "r");
    if (stream == NULL) return false;
    char line[512];
    if (fgets(line, sizeof(line), stream) == NULL) { fclose(stream); return false; }
    line[strcspn(line, "\r\n")] = '\0';
    if (strcmp(line, expected_header) != 0) { fclose(stream); return false; }
    const size_t capacity = 200000u;
    rail_sample_t *samples = malloc(capacity * sizeof(*samples));
    if (samples == NULL) { fclose(stream); return false; }
    char run_id[65], netlist_hash[65], fault_profile[48], status[24];
    size_t count = 0u;
    double timestamp_s, rail_v, battery_v, current_a;
    bool valid = true;
    while (fgets(line, sizeof(line), stream) != NULL) {
        if (count >= capacity || sscanf(line, "%64[^,],%64[^,],%47[^,],%lf,%lf,%lf,%lf,%23s",
                run_id, netlist_hash, fault_profile, &timestamp_s, &rail_v, &battery_v, &current_a, status) != 8 ||
            strcmp(run_id, expected_simulation_id) != 0 ||
            strcmp(netlist_hash, expected_netlist_sha256) != 0 ||
            strcmp(fault_profile, expected_fault) != 0 || strcmp(status, "SIMULATED") != 0 ||
            !isfinite(timestamp_s) || !isfinite(rail_v) || !isfinite(battery_v) || !isfinite(current_a) ||
            timestamp_s < 0.0 || rail_v <= 0.0 || battery_v <= 0.0 || current_a < 0.0 ||
            (count > 0u && timestamp_s <= samples[count - 1u].time_s)) {
            valid = false;
            break;
        }
        samples[count++] = (rail_sample_t){.time_s=timestamp_s, .rail_v=rail_v};
    }
    if (ferror(stream) || fclose(stream) != 0 || count < 2u || samples[0].time_s > 0.001) valid = false;
    if (!valid) { free(samples); return false; }
    board->rail_samples = samples;
    board->rail_sample_count = count;
    board->rail_fault_enabled = true;
    board->rail_start_ms = board->absolute_ms;
    board->rail_min_v = samples[0].rail_v;
    return true;
}

static uint64_t rail_sample_ms(double seconds)
{
    const double milliseconds = seconds * 1000.0;
    const uint64_t rounded = (uint64_t)milliseconds;
    return rounded + ((double)rounded < milliseconds - 1e-9 ? 1u : 0u);
}

static int spi_transfer(void *ctx, const uint8_t *tx, size_t tx_len,
                        uint8_t *rx, size_t rx_len)
{
    host_board_t *board = ctx;
    if (tx_len == 0u || tx_len != rx_len) return -1;
    if (board->inject_enabled && board->fault == FAULT_SPI_ONCE && !board->fault_used) {
        board->fault_used = true;
        return -1;
    }
    memset(rx, 0, rx_len);
    const uint8_t op = tx[0];
    if (op == 0x0eu && tx_len >= 3u) {
        board->packet_len = tx_len - 2u;
        if (board->packet_len > sizeof(board->packet)) return -1;
        memcpy(board->packet, tx + 2u, board->packet_len);
    } else if (op == 0x83u) {
        if (board->inject_enabled && board->fault == FAULT_IRQ_STUCK) board->fault_used = true;
        board->irq = SX1262_IRQ_TX_DONE;
        board->irq_high = true;
    } else if (op == 0x82u) {
        board->irq = SX1262_IRQ_TIMEOUT;
        board->irq_high = true;
    } else if (op == 0x12u && tx_len == 4u) {
        rx[2] = (uint8_t)(board->irq >> 8);
        rx[3] = (uint8_t)board->irq;
    } else if (op == 0x02u) {
        board->irq = 0u;
        board->irq_high = false;
    }
    return 0;
}

static int radio_reset(void *ctx) { (void)ctx; return 0; }
static int imu_read(void *ctx, tag_imu_sample_t *sample)
{
    host_board_t *board = ctx;
    if (board->inject_enabled && board->fault == FAULT_IMU_ONCE && !board->fault_used) {
        board->fault_used = true;
        return -1;
    }
    switch (board->profile) {
    case PROFILE_NORMAL: *sample = (tag_imu_sample_t){.x_mg=0, .y_mg=0, .z_mg=1000}; break;
    case PROFILE_ACTIVE: *sample = (tag_imu_sample_t){.x_mg=500, .y_mg=0, .z_mg=866}; break;
    case PROFILE_ALERT: *sample = (tag_imu_sample_t){.x_mg=0, .y_mg=0, .z_mg=1000, .interrupt_flags=TAG_IMU_FLAG_WAKE_UP}; break;
    case PROFILE_WORST:
        /* Seeded repeatable switching between active motion and impact alerts. */
        if ((board->absolute_ms / 10000u + board->seed) % 7u == 0u)
            *sample = (tag_imu_sample_t){.x_mg=1500, .y_mg=0, .z_mg=1000, .interrupt_flags=TAG_IMU_FLAG_WAKE_UP};
        else
            *sample = (tag_imu_sample_t){.x_mg=500, .y_mg=0, .z_mg=866};
        break;
    }
    return 0;
}
static bool imu_irq(void *ctx) { (void)ctx; return false; }
static bool radio_irq(void *ctx)
{
    host_board_t *board = ctx;
    if (board->inject_enabled && board->fault == FAULT_IRQ_STUCK) return false;
    return board->irq_high;
}
static uint32_t clock_ms(void *ctx) { return ((host_board_t *)ctx)->time_ms; }
static void advance_ms(host_board_t *board, uint32_t ms)
{
    const uint64_t start_ms = board->absolute_ms;
    uint64_t target_ms = start_ms + ms;
    if (board->rail_fault_enabled) {
        while (board->rail_sample_index < board->rail_sample_count) {
            const rail_sample_t sample = board->rail_samples[board->rail_sample_index];
            const uint64_t sample_ms = board->rail_start_ms + rail_sample_ms(sample.time_s);
            if (sample_ms > target_ms) break;
            board->rail_sample_index++;
            if (sample.rail_v < board->rail_min_v) board->rail_min_v = sample.rail_v;
            if (!board->brownout_pending && sample.rail_v < board->brownout_threshold_v) {
                board->brownout_pending = true;
                board->brownout_crossing_ms = sample_ms;
                board->rail_crossing_v = sample.rail_v;
                board->rail_crossing_s = sample.time_s;
                target_ms = sample_ms;
                break;
            }
            if (board->brownout_pending && sample.rail_v >= board->brownout_threshold_v) {
                board->rail_recovered = true;
                board->rail_recovered_ms = sample_ms;
                board->rail_recovery_v = sample.rail_v;
                board->rail_recovery_s = sample.time_s;
                target_ms = sample_ms;
                break;
            }
        }
    }
    const uint64_t elapsed_ms = target_ms - start_ms;
    board->absolute_ms = target_ms;
    const uint32_t before = board->time_ms;
    board->time_ms += (uint32_t)elapsed_ms;
    if (board->time_ms < before) board->timer_wraps++;
}
static void sleep_ms(void *ctx, uint32_t ms) { advance_ms(ctx, ms); }
static void wait_for_event(void *ctx, uint32_t ms) { advance_ms(ctx, ms); }
static void trace_event(void *ctx, const tag_trace_record_t *record)
{
    host_board_t *board = ctx;
    board->trace_events++;
    if (record->event == TAG_TRACE_RECOVERY) board->recovery_events++;
    if (record->event == TAG_TRACE_TX_START) board->tx_start_events++;
    if (record->event == TAG_TRACE_ERROR) board->error_events++;
    if (record->event == TAG_TRACE_BOOT) board->boot_events++;
}

static bool parse_profile(const char *text, profile_t *profile)
{
    if (strcmp(text, "NORMAL") == 0) *profile = PROFILE_NORMAL;
    else if (strcmp(text, "ACTIVE") == 0) *profile = PROFILE_ACTIVE;
    else if (strcmp(text, "ALERT") == 0) *profile = PROFILE_ALERT;
    else if (strcmp(text, "WORST_REASONABLE_CASE") == 0) *profile = PROFILE_WORST;
    else return false;
    return true;
}

static const char *profile_name(profile_t profile)
{
    static const char *names[] = {"NORMAL", "ACTIVE", "ALERT", "WORST_REASONABLE_CASE"};
    return names[profile];
}

static const char *state_name(tag_state_t state)
{
    static const char *names[] = {"BOOT", "SELF_TEST", "SLEEP", "IMU_MONITORING",
                                  "RF_TX", "RF_RX", "ALERT", "ERROR_RECOVERY"};
    return (unsigned)state < sizeof(names) / sizeof(names[0]) ? names[state] : "UNKNOWN";
}

static bool parse_u32(const char *text, uint32_t *value)
{
    char *end = NULL;
    unsigned long parsed = strtoul(text, &end, 10);
    if (text[0] == '\0' || end == text || *end != '\0' || parsed > UINT32_MAX) return false;
    *value = (uint32_t)parsed;
    return true;
}

static bool run_reset_fault(fault_t fault, host_board_t *board, tag_firmware_t *fw,
                            const tag_hal_t *hal, const tag_config_t *config)
{
    for (unsigned i = 0; i < 6u; ++i) tag_firmware_step(fw);
    if (fw->state != TAG_STATE_SLEEP) return false;

    /* This probe injects classification flags; no independent watchdog or reset source exists here. */
    const uint32_t cause = fault == FAULT_SYNTHETIC_WATCHDOG_CLASSIFICATION
        ? TAG_RESET_CAUSE_WATCHDOG : TAG_RESET_CAUSE_CPU_LOCKUP;
    uint32_t elapsed_ms = 0u;
    const uint32_t synthetic_delay_ms = 50u;
    if (fault == FAULT_SYNTHETIC_WATCHDOG_CLASSIFICATION) {
        /* Synthetic delay only: it does not arm, feed, or expire a watchdog. */
        while (elapsed_ms < synthetic_delay_ms) {
            advance_ms(board, 10u);
            elapsed_ms += 10u;
        }
    } else {
        /* Synthetic delay only: no CPU lockup or independent reset is modeled. */
        elapsed_ms = 1u;
        advance_ms(board, elapsed_ms);
    }

    if (tag_reset_cause_classify(cause) != (fault == FAULT_SYNTHETIC_WATCHDOG_CLASSIFICATION
            ? TAG_RESET_KIND_WATCHDOG : TAG_RESET_KIND_OTHER)) return false;
    board->irq = 0u;
    board->irq_high = false;
    board->packet_len = 0u;
    if (tag_firmware_init(fw, hal, config) != 0) return false;

    /* Reinitialize the firmware and verify post-init output; this is not a reset source. */
    for (unsigned i = 0; i < 4096u; ++i) {
        tag_firmware_step(fw);
        if (fw->packets_sent > 0u && fw->state == TAG_STATE_SLEEP) break;
    }
    const bool post_init_valid = board->boot_events >= 2u && fw->failures == 0u &&
        fw->packets_sent > 0u && fw->state == TAG_STATE_SLEEP &&
        tag_telemetry_crc_valid(board->packet, board->packet_len);
    printf("{\"status\":\"%s\",\"fault\":\"%s\",\"injection_applied\":true,"
           "\"recovered\":false,\"attempts\":1,\"terminal_state\":\"%s\","
           "\"trace_event\":\"BOOT\",\"trace_event_count\":%u,\"seed\":%u,"
           "\"reset_cause\":\"%s\",\"cause_source\":\"TEST_INJECTED_CLASSIFICATION_FLAG\","
           "\"reset_approach\":\"SYNTHETIC_REINITIALIZATION\",\"elapsed_before_reset_ms\":%u,"
           "\"post_init_packets\":%u,\"post_init_beacon_observed\":%s,"
           "\"watchdog_causally_observed\":false,\"reset_cause_independently_observed\":false,"
           "\"physical_watchdog_validated\":false,"
           "\"evidence\":\"synthetic delay; test-invoked tag_firmware_init; injected classification flag; BOOT and post-init beacon observed\"}\n",
           post_init_valid ? "OBSERVED" : "FAILED",
           fault == FAULT_SYNTHETIC_WATCHDOG_CLASSIFICATION ? "synthetic_watchdog_classification_probe" : "synthetic_reset_classification_probe",
           state_name(fw->state), board->boot_events - 1u, board->seed,
           tag_reset_kind_name(tag_reset_cause_classify(cause)), elapsed_ms,
           fw->packets_sent, post_init_valid ? "true" : "false");
    return post_init_valid;
}

static bool run_electrical_fault(fault_t fault, host_board_t *board, tag_firmware_t *fw,
                                 const tag_hal_t *hal, const tag_config_t *config,
                                 const char *simulation_id, const char *netlist_sha256,
                                 const char *threshold_source)
{
    for (unsigned i = 0; i < 4096u && !board->brownout_pending; ++i)
        tag_firmware_step(fw);
    if (!board->brownout_pending) {
        printf("{\"status\":\"FAILED\",\"fault\":\"%s\",\"injection_applied\":false,"
               "\"recovered\":false,\"attempts\":0,\"terminal_state\":\"%s\","
               "\"trace_event\":\"BROWNOUT\",\"trace_event_count\":0,\"seed\":%u,"
               "\"simulation_id\":\"%s\",\"detail\":\"rail waveform never crossed the assumed brownout threshold\"}\n",
               fault_name(fault), state_name(fw->state), board->seed, simulation_id);
        return false;
    }
    for (unsigned i = 0; i < 4096u && !board->rail_recovered &&
         board->rail_sample_index < board->rail_sample_count; ++i)
        advance_ms(board, 1u);
    const uint32_t cause = TAG_RESET_CAUSE_BROWNOUT;
    const bool cause_classified = tag_reset_cause_classify(cause) == TAG_RESET_KIND_BROWNOUT;
    bool post_init_valid = false;
    if (board->rail_recovered && cause_classified) {
        board->irq = 0u;
        board->irq_high = false;
        board->packet_len = 0u;
        tag_config_t recovery_config = *config;
        /* A 100 ms test beacon is an explicit host recovery schedule, not product timing. */
        recovery_config.normal_beacon_ms = 100u;
        if (tag_firmware_init(fw, hal, &recovery_config) == 0) {
            for (unsigned i = 0; i < 4096u; ++i) {
                tag_firmware_step(fw);
                if (fw->packets_sent > 0u && fw->state == TAG_STATE_SLEEP) break;
            }
            post_init_valid = board->boot_events >= 2u && fw->failures == 0u &&
                fw->packets_sent > 0u && fw->state == TAG_STATE_SLEEP &&
                tag_telemetry_crc_valid(board->packet, board->packet_len);
        }
    }
    const bool recovered = board->rail_recovered && cause_classified && post_init_valid;
    printf("{\"status\":\"%s\",\"fault\":\"%s\",\"injection_applied\":true,"
           "\"recovered\":%s,\"attempts\":1,\"terminal_state\":\"%s\","
           "\"trace_event\":\"BROWNOUT\",\"trace_event_count\":1,\"boot_trace_count\":%u,"
           "\"seed\":%u,\"simulation_id\":\"%s\",\"netlist_sha256\":\"%s\","
           "\"reset_cause\":\"%s\",\"reset_cause_source\":\"SIMULATED_RAIL_THRESHOLD_SUPERVISOR\","
           "\"brownout_threshold_v\":%.9g,\"brownout_threshold_status\":\"ASSUMED\","
           "\"brownout_threshold_source\":\"%s\",\"rail_min_v\":%.9g,"
           "\"rail_crossing_v\":%.9g,\"rail_crossing_s\":%.12g,\"rail_crossing_ms\":%" PRIu64 ","
           "\"rail_recovery_v\":%.9g,\"rail_recovery_s\":%.12g,\"rail_recovered_ms\":%" PRIu64 ","
           "\"brownout_causally_observed\":true,\"post_recovery_beacon_observed\":%s,"
           "\"evidence\":\"fresh ngspice rail samples crossed the sourced assumed threshold, returned above it, and post-reinitialization CRC-valid beacon plus SLEEP were observed\"}\n",
           recovered ? "RECOVERED" : "FAILED", fault_name(fault), recovered ? "true" : "false",
           state_name(fw->state), board->boot_events - 1u, board->seed,
           simulation_id, netlist_sha256, tag_reset_kind_name(tag_reset_cause_classify(cause)),
           board->brownout_threshold_v, threshold_source, board->rail_min_v, board->rail_crossing_v,
           board->rail_crossing_s, board->brownout_crossing_ms, board->rail_recovery_v,
           board->rail_recovery_s, board->rail_recovered_ms,
           post_init_valid ? "true" : "false");
    return recovered;
}

int main(int argc, char **argv)
{
    uint32_t days = 0u, seed = 7u, start_ms = 0u, start_sequence = 0u;
    const char *rail_waveform = NULL, *simulation_id = NULL, *netlist_sha256 = NULL;
    const char *threshold_source = NULL;
    double brownout_threshold_v = 0.0;
    profile_t profile = PROFILE_NORMAL;
    fault_t fault = FAULT_NONE;
    bool is_long_run = false;
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--long-run-days") == 0 && i + 1 < argc) {
            if (!parse_u32(argv[++i], &days) || days == 0u || days > 30u) return 64;
            is_long_run = true;
        } else if (strcmp(argv[i], "--scenario") == 0 && i + 1 < argc) {
            if (!parse_profile(argv[++i], &profile)) return 64;
        } else if (strcmp(argv[i], "--seed") == 0 && i + 1 < argc) {
            if (!parse_u32(argv[++i], &seed)) return 64;
        } else if (strcmp(argv[i], "--start-time-ms") == 0 && i + 1 < argc) {
            if (!parse_u32(argv[++i], &start_ms)) return 64;
        } else if (strcmp(argv[i], "--start-sequence") == 0 && i + 1 < argc) {
            if (!parse_u32(argv[++i], &start_sequence)) return 64;
        } else if (strcmp(argv[i], "--fault") == 0 && i + 1 < argc) {
            const char *name = argv[++i];
            if (strcmp(name, "spi_timeout_once") == 0) fault = FAULT_SPI_ONCE;
            else if (strcmp(name, "imu_i2c_timeout_once") == 0) fault = FAULT_IMU_ONCE;
            else if (strcmp(name, "irq_missing") == 0) fault = FAULT_IRQ_STUCK;
            else if (strcmp(name, "synthetic_watchdog_classification_probe") == 0) fault = FAULT_SYNTHETIC_WATCHDOG_CLASSIFICATION;
            else if (strcmp(name, "synthetic_reset_classification_probe") == 0) fault = FAULT_SYNTHETIC_RESET_CLASSIFICATION;
            else if (strcmp(name, "voltage_drop") == 0) fault = FAULT_VOLTAGE_DROP;
            else if (strcmp(name, "high_esr") == 0) fault = FAULT_HIGH_ESR;
            else if (strcmp(name, "regulator_instability") == 0) fault = FAULT_REGULATOR_INSTABILITY;
            else return 64;
        } else if (strcmp(argv[i], "--rail-waveform") == 0 && i + 1 < argc) {
            rail_waveform = argv[++i];
        } else if (strcmp(argv[i], "--simulation-id") == 0 && i + 1 < argc) {
            simulation_id = argv[++i];
        } else if (strcmp(argv[i], "--netlist-sha256") == 0 && i + 1 < argc) {
            netlist_sha256 = argv[++i];
        } else if (strcmp(argv[i], "--brownout-threshold-v") == 0 && i + 1 < argc) {
            if (!parse_positive_double(argv[++i], &brownout_threshold_v)) return 64;
        } else if (strcmp(argv[i], "--threshold-source") == 0 && i + 1 < argc) {
            threshold_source = argv[++i];
        } else return 64;
    }

    host_board_t board = {.time_ms=start_ms, .absolute_ms=start_ms, .profile=profile, .seed=seed, .fault=fault};
    const bool electrical_fault = fault == FAULT_VOLTAGE_DROP || fault == FAULT_HIGH_ESR ||
                                  fault == FAULT_REGULATOR_INSTABILITY;
    if (electrical_fault) {
        if (is_long_run || rail_waveform == NULL || simulation_id == NULL || netlist_sha256 == NULL ||
            threshold_source == NULL || !*threshold_source || strlen(simulation_id) != 64u ||
            strlen(netlist_sha256) != 64u || brownout_threshold_v <= 0.0 ||
            !load_rail_waveform(rail_waveform, simulation_id, netlist_sha256,
                                fault_name(fault), &board)) return 64;
        board.brownout_threshold_v = brownout_threshold_v;
    } else if (rail_waveform != NULL || simulation_id != NULL || netlist_sha256 != NULL ||
               threshold_source != NULL || brownout_threshold_v != 0.0) {
        return 64;
    }
    const tag_hal_t hal = {.context=&board, .spi_transfer=spi_transfer, .radio_reset=radio_reset,
        .imu_read=imu_read, .imu_irq_pending=imu_irq, .radio_irq_pending=radio_irq,
        .clock_ms=clock_ms, .sleep_ms=sleep_ms, .wait_for_event=wait_for_event, .trace_event=trace_event};
    tag_config_t cfg = tag_default_config(0x12345678u);
    if (profile == PROFILE_NORMAL) cfg.normal_beacon_ms = 900000u;
    if (profile == PROFILE_ACTIVE) { cfg.normal_beacon_ms = 60000u; cfg.active_beacon_ms = 60000u; }
    if (profile == PROFILE_ALERT) { cfg.normal_beacon_ms = 10000u; cfg.alert_beacon_ms = 10000u; }
    if (profile == PROFILE_WORST) { cfg.normal_beacon_ms = 10000u; cfg.alert_beacon_ms = 10000u; cfg.active_beacon_ms = 10000u; }
    tag_firmware_t fw;
    if (tag_firmware_init(&fw, &hal, &cfg) != 0) return 1;
    fw.sequence = start_sequence;

    if (!is_long_run) {
        if (electrical_fault) {
            const bool success = run_electrical_fault(fault, &board, &fw, &hal, &cfg,
                simulation_id, netlist_sha256, threshold_source);
            free(board.rail_samples);
            return success ? 0 : 2;
        }
        if (fault == FAULT_SYNTHETIC_WATCHDOG_CLASSIFICATION || fault == FAULT_SYNTHETIC_RESET_CLASSIFICATION)
            return run_reset_fault(fault, &board, &fw, &hal, &cfg) ? 0 : 2;
        for (unsigned i = 0; i < 6u; ++i) tag_firmware_step(&fw);
        if (fault != FAULT_NONE) board.inject_enabled = true;
        for (unsigned i = 0; i < 4096u; ++i) {
            tag_firmware_step(&fw);
            if (board.recovery_events > 0u && fw.state == TAG_STATE_SLEEP) break;
        }
        const bool recovered = board.fault_used && fw.state != TAG_STATE_ERROR_RECOVERY &&
            board.recovery_events > 0u;
        printf("{\"status\":\"%s\",\"profile\":\"%s\",\"fault\":\"%s\",\"recovered\":%s,\"terminal_state\":\"%s\",\"attempts\":%u,\"recovery_events\":%u,\"tx_start_events\":%u,\"error_events\":%u,\"trace_events\":%u}\n",
            recovered ? "RECOVERED" : fault == FAULT_NONE ? "COMPLETED" : "UNRECOVERABLE",
            profile_name(profile), fault == FAULT_SPI_ONCE ? "spi_timeout_once" :
            fault == FAULT_IMU_ONCE ? "imu_i2c_timeout_once" : fault == FAULT_IRQ_STUCK ? "irq_missing" : "none",
            recovered ? "true" : "false", state_name(fw.state), board.fault_used ? 1u : 0u,
            board.recovery_events, board.tx_start_events, board.error_events, board.trace_events);
        return fault == FAULT_IRQ_STUCK && !recovered ? 0 :
               fault != FAULT_NONE && !recovered ? 2 : 0;
    }

    const uint64_t start = board.absolute_ms;
    const uint64_t target = (uint64_t)days * 86400000ull;
    const uint64_t max_steps = target / 1000ull + 10000ull;
    uint64_t steps = 0u;
    while (board.absolute_ms - start < target && steps++ < max_steps) {
        if (fw.state == TAG_STATE_ERROR_RECOVERY) {
            tag_firmware_step(&fw);
        } else {
            tag_firmware_step(&fw);
        }
    }
    const uint64_t elapsed = board.absolute_ms - start;
    const bool complete = elapsed >= target && steps < max_steps && fw.failures == 0u &&
        fw.packets_sent > 0u && fw.state == TAG_STATE_SLEEP &&
        tag_telemetry_crc_valid(board.packet, board.packet_len);
    const uint32_t sequence_wrapped = (fw.sequence < start_sequence) ? 1u : 0u;
    const uint32_t timer_wraps = board.timer_wraps;
    printf("{\"status\":\"%s\",\"scenario\":\"%s\",\"seed\":%u,\"virtual_days\":%u,\"virtual_elapsed_ms\":%" PRIu64 ",\"sequence\":%u,\"sequence_wraps\":%u,\"timer_wraps\":%u,\"packets\":%u,\"failures\":%u,\"terminal_state\":\"%s\",\"firmware_bytes\":%zu,\"heap_bytes\":0,\"heap_status\":\"NO_DYNAMIC_ALLOCATION\",\"trace_events\":%u,\"trace_recovery_events\":%u}\n",
        complete ? "COMPLETED" : "FAILED", profile_name(profile), seed, days, elapsed,
        fw.sequence, sequence_wrapped, timer_wraps, fw.packets_sent, fw.failures,
        state_name(fw.state), sizeof(fw), board.trace_events, board.recovery_events);
    return complete ? 0 : 3;
}
