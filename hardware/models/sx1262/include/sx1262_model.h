#ifndef SX1262_MODEL_H
#define SX1262_MODEL_H

/* CPU-only SX1262 peripheral model. One call represents one complete SPI
 * transaction (NSS asserted for the whole buffer, then released). */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SX1262_MODEL_FIFO_SIZE 256u

enum sx1262_model_irq {
    SX1262_IRQ_TX_DONE       = 0x0001,
    SX1262_IRQ_RX_DONE       = 0x0002,
    SX1262_IRQ_PREAMBLE      = 0x0004,
    SX1262_IRQ_SYNCWORD      = 0x0008,
    SX1262_IRQ_HEADER_VALID  = 0x0010,
    SX1262_IRQ_HEADER_ERROR = 0x0020,
    SX1262_IRQ_CRC_ERROR     = 0x0040,
    SX1262_IRQ_CAD_DONE      = 0x0080,
    SX1262_IRQ_CAD_DETECTED  = 0x0100,
    SX1262_IRQ_TIMEOUT       = 0x0200,
};

enum sx1262_model_mode {
    SX1262_MODE_SLEEP = 0,
    SX1262_MODE_STANDBY_RC,
    SX1262_MODE_STANDBY_XOSC,
    SX1262_MODE_FS,
    SX1262_MODE_TX,
    SX1262_MODE_RX,
};

typedef struct sx1262_model {
    uint8_t fifo[SX1262_MODEL_FIFO_SIZE];
    uint8_t tx_base, rx_base;
    uint8_t packet_type;
    uint8_t modulation[4];
    uint8_t packet[9];
    uint8_t pa_config[4];
    uint8_t image_calibration[2];
    uint8_t tx_power_dbm;
    uint8_t ramp_time;
    uint32_t rf_frequency_word;
    uint16_t irq_status, irq_mask, dio1_mask, dio2_mask, dio3_mask;
    enum sx1262_model_mode mode;
    uint32_t now_ms;
    uint32_t tx_started_ms, tx_due_ms, tx_timeout_ms;
    uint32_t tx_latency_ms;
    uint8_t command_status;
    uint8_t last_opcode;
    uint32_t tx_count;
    uint32_t fault_count;
    bool tx_pending;
    bool rx_pending;
    bool fault;
} sx1262_model_t;

void sx1262_model_init(sx1262_model_t *model);
void sx1262_model_reset(sx1262_model_t *model);
void sx1262_model_advance(sx1262_model_t *model, uint32_t now_ms);
bool sx1262_model_irq(const sx1262_model_t *model);

/* Drop-in backend for tag_hal_t.spi_transfer(ctx, tx, tx_len, rx, rx_len).
 * For command reads, the status byte is rx[1]; result bytes follow it.
 * READ_BUFFER: [opcode, offset, dummy, dummy...] -> data starts at rx[3].
 * GET_IRQ_STATUS: [opcode, dummy, dummy] -> IRQ MSB/LSB at rx[2]/rx[3].
 * Other register/status reads return data beginning at rx[2]. */
int sx1262_model_transfer(void *ctx, const uint8_t *tx, size_t tx_len,
                          uint8_t *rx, size_t rx_len);

#ifdef __cplusplus
}
#endif
#endif
