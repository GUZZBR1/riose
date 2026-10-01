#ifndef SX1262_H
#define SX1262_H

#include "tag_firmware.h"

#define SX1262_IRQ_TX_DONE 0x0001u
#define SX1262_IRQ_RX_DONE 0x0002u
#define SX1262_IRQ_TIMEOUT 0x0200u

int sx1262_configure(const tag_hal_t *hal, uint32_t frequency_hz,
                     int8_t tx_power_dbm);
int sx1262_set_standby(const tag_hal_t *hal);
int sx1262_set_sleep(const tag_hal_t *hal);
int sx1262_write_buffer(const tag_hal_t *hal, uint8_t offset,
                        const uint8_t *data, size_t length);
int sx1262_set_tx(const tag_hal_t *hal, uint32_t timeout_ms);
int sx1262_set_rx(const tag_hal_t *hal, uint32_t timeout_ms);
int sx1262_get_irq_status(const tag_hal_t *hal, uint16_t *irq_status);
int sx1262_clear_irq_status(const tag_hal_t *hal, uint16_t irq_status);

#endif
