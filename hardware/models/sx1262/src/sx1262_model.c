#include "sx1262_model.h"

#include <string.h>

/* SX126x command opcodes. */
enum {
    CMD_SET_SLEEP = 0x84, CMD_SET_STANDBY = 0x80, CMD_SET_TX = 0x83,
    CMD_SET_RF_FREQUENCY = 0x86, CMD_SET_PACKET_TYPE = 0x8a,
    CMD_SET_RX = 0x82, CMD_SET_MODULATION_PARAMS = 0x8b, CMD_SET_PACKET_PARAMS = 0x8c,
    CMD_SET_TX_PARAMS = 0x8e, CMD_SET_BUFFER_BASE = 0x8f,
    CMD_GET_STATUS = 0xc0, CMD_GET_IRQ_STATUS = 0x12,
    CMD_CLEAR_IRQ_STATUS = 0x02, CMD_SET_DIO_IRQ_PARAMS = 0x08,
    CMD_WRITE_BUFFER = 0x0e, CMD_READ_BUFFER = 0x1e,
};

enum { CMD_OK = 0x02, CMD_DATA_AVAILABLE = 0x04, CMD_TIMEOUT = 0x06,
       CMD_INVALID = 0x08, CMD_FAILED = 0x0a };

static uint32_t u24(const uint8_t *p)
{
    return ((uint32_t)p[0] << 16) | ((uint32_t)p[1] << 8) | p[2];
}

static uint16_t u16(const uint8_t *p)
{
    return (uint16_t)(((uint16_t)p[0] << 8) | p[1]);
}

static bool valid_lora_bandwidth(uint8_t bw)
{
    return bw == 0x00 || bw == 0x01 || bw == 0x02 || bw == 0x03 ||
           bw == 0x04 || bw == 0x05 || bw == 0x06 || bw == 0x09 ||
           bw == 0x0a || bw == 0x0b;
}

static void fault(sx1262_model_t *m, uint8_t status)
{
    m->fault = true;
    m->fault_count++;
    m->command_status = status;
}

void sx1262_model_reset(sx1262_model_t *m)
{
    uint32_t latency = m->tx_latency_ms;
    memset(m, 0, sizeof(*m));
    m->mode = SX1262_MODE_STANDBY_RC;
    m->command_status = CMD_OK;
    m->tx_latency_ms = latency ? latency : 30u;
}

void sx1262_model_init(sx1262_model_t *m)
{
    memset(m, 0, sizeof(*m));
    m->tx_latency_ms = 30u;
    sx1262_model_reset(m);
}

void sx1262_model_advance(sx1262_model_t *m, uint32_t now_ms)
{
    m->now_ms = now_ms;
    if (!m->tx_pending && !m->rx_pending)
        return;
    /* Unsigned subtraction is wrap-safe for intervals shorter than 2^31 ms. */
    if (m->tx_timeout_ms && (uint32_t)(now_ms - m->tx_started_ms) >= m->tx_timeout_ms) {
        m->tx_pending = false;
        m->rx_pending = false;
        m->mode = SX1262_MODE_STANDBY_RC;
        m->irq_status |= SX1262_IRQ_TIMEOUT;
        m->command_status = CMD_TIMEOUT;
    } else if ((int32_t)(now_ms - m->tx_due_ms) >= 0) {
        m->tx_pending = false;
        m->rx_pending = false;
        m->mode = SX1262_MODE_STANDBY_RC;
        m->irq_status |= m->rx_pending ? SX1262_IRQ_TIMEOUT : SX1262_IRQ_TX_DONE;
        m->command_status = m->rx_pending ? CMD_TIMEOUT : CMD_OK;
    }
}

bool sx1262_model_irq(const sx1262_model_t *m)
{
    return (m->irq_status & m->irq_mask) != 0;
}

static uint8_t status_byte(const sx1262_model_t *m)
{
    uint8_t mode;
    switch (m->mode) {
    case SX1262_MODE_SLEEP: mode = 0x00; break;
    case SX1262_MODE_STANDBY_RC: mode = 0x20; break;
    case SX1262_MODE_STANDBY_XOSC: mode = 0x30; break;
    case SX1262_MODE_FS: mode = 0x40; break;
    case SX1262_MODE_RX: mode = 0x50; break;
    case SX1262_MODE_TX: mode = 0x60; break;
    default: mode = 0x20; break;
    }
    return (uint8_t)(mode | (m->command_status & 0x0e));
}

static bool need(const uint8_t *tx, size_t tx_len, size_t n)
{
    (void)tx;
    return tx_len >= n;
}

int sx1262_model_transfer(void *ctx, const uint8_t *tx, size_t tx_len,
                          uint8_t *rx, size_t rx_len)
{
    sx1262_model_t *m = (sx1262_model_t *)ctx;
    size_t i;
    uint8_t op;
    if (!m || !tx || !tx_len || (rx_len && !rx))
        return -1;
    sx1262_model_advance(m, m->now_ms);
    if (rx)
        memset(rx, 0, rx_len);
    op = tx[0];
    m->last_opcode = op;
    m->command_status = CMD_OK;

    switch (op) {
    case CMD_GET_STATUS:
        if (rx_len > 1) rx[1] = status_byte(m);
        break;
    case CMD_SET_SLEEP:
        if (!need(tx, tx_len, 2)) { fault(m, CMD_INVALID); break; }
        m->mode = SX1262_MODE_SLEEP;
        m->tx_pending = false;
        break;
    case CMD_SET_STANDBY:
        if (!need(tx, tx_len, 2) || tx[1] > 1) { fault(m, CMD_INVALID); break; }
        m->mode = tx[1] ? SX1262_MODE_STANDBY_XOSC : SX1262_MODE_STANDBY_RC;
        m->tx_pending = false;
        break;
    case CMD_SET_PACKET_TYPE:
        if (!need(tx, tx_len, 2) || (tx[1] != 0 && tx[1] != 1)) { fault(m, CMD_INVALID); break; }
        m->packet_type = tx[1];
        break;
    case CMD_SET_RF_FREQUENCY:
        if (!need(tx, tx_len, 5)) { fault(m, CMD_INVALID); break; }
        m->rf_frequency_word = ((uint32_t)tx[1] << 24) | ((uint32_t)tx[2] << 16) |
                               ((uint32_t)tx[3] << 8) | tx[4];
        break;
    case CMD_SET_TX_PARAMS:
        if (!need(tx, tx_len, 3)) { fault(m, CMD_INVALID); break; }
        m->tx_power_dbm = tx[1]; /* signed 8-bit two's-complement representation */
        m->ramp_time = tx[2];
        break;
    case CMD_SET_MODULATION_PARAMS:
        if (!need(tx, tx_len, 5)) { fault(m, CMD_INVALID); break; }
        if (m->packet_type == 1 && (tx[1] < 5 || tx[1] > 12 || !valid_lora_bandwidth(tx[2]) || tx[3] < 1 || tx[3] > 4 || tx[4] > 1)) {
            fault(m, CMD_INVALID); break;
        }
        memcpy(m->modulation, tx + 1, sizeof(m->modulation));
        break;
    case CMD_SET_PACKET_PARAMS:
        /* SX126x SetPacketParams has six LoRa arguments (7 bytes with
         * opcode); FSK uses a longer packet parameter structure. */
        if (!need(tx, tx_len, 7)) { fault(m, CMD_INVALID); break; }
        memset(m->packet, 0, sizeof(m->packet));
        memcpy(m->packet, tx + 1, tx_len - 1 < sizeof(m->packet) ? tx_len - 1 : sizeof(m->packet));
        break;
    case CMD_SET_BUFFER_BASE:
        if (!need(tx, tx_len, 3)) { fault(m, CMD_INVALID); break; }
        m->tx_base = tx[1]; m->rx_base = tx[2];
        break;
    case CMD_WRITE_BUFFER:
        if (!need(tx, tx_len, 2)) { fault(m, CMD_INVALID); break; }
        for (i = 2; i < tx_len; i++)
            m->fifo[(uint8_t)(tx[1] + (uint8_t)(i - 2))] = tx[i];
        break;
    case CMD_READ_BUFFER:
        if (!need(tx, tx_len, 3)) { fault(m, CMD_INVALID); break; }
        for (i = 3; i < rx_len; i++)
            rx[i] = m->fifo[(uint8_t)(tx[1] + (uint8_t)(i - 3))];
        m->command_status = CMD_DATA_AVAILABLE;
        break;
    case CMD_SET_DIO_IRQ_PARAMS:
        if (!need(tx, tx_len, 9)) { fault(m, CMD_INVALID); break; }
        m->irq_mask = u16(tx + 1); m->dio1_mask = u16(tx + 3);
        m->dio2_mask = u16(tx + 5); m->dio3_mask = u16(tx + 7);
        break;
    case CMD_GET_IRQ_STATUS:
        if (rx_len > 1) rx[1] = status_byte(m);
        if (rx_len > 2) rx[2] = (uint8_t)(m->irq_status >> 8);
        if (rx_len > 3) rx[3] = (uint8_t)m->irq_status;
        m->command_status = CMD_DATA_AVAILABLE;
        break;
    case CMD_CLEAR_IRQ_STATUS:
        if (!need(tx, tx_len, 3)) { fault(m, CMD_INVALID); break; }
        m->irq_status &= (uint16_t)~u16(tx + 1);
        break;
    case CMD_SET_TX:
        if (!need(tx, tx_len, 4)) { fault(m, CMD_INVALID); break; }
        if (m->mode == SX1262_MODE_SLEEP || m->mode == SX1262_MODE_TX) { fault(m, CMD_FAILED); break; }
        m->tx_timeout_ms = (u24(tx + 1) * 15625u + 999999u) / 1000000u;
        m->tx_started_ms = m->now_ms;
        m->tx_due_ms = m->now_ms + m->tx_latency_ms;
        m->tx_pending = true;
        m->rx_pending = false;
        m->mode = SX1262_MODE_TX;
        m->tx_count++;
        break;
    case CMD_SET_RX:
        /* Timeout is a 24-bit count in units of 15.625 us. 0 means
         * continuous receive; this deterministic model treats it as a
         * bounded 1 s window to avoid an unbounded host test. */
        if (!need(tx, tx_len, 4) || m->mode == SX1262_MODE_SLEEP ||
            m->mode == SX1262_MODE_TX) { fault(m, CMD_FAILED); break; }
        m->tx_pending = false;
        m->rx_pending = true;
        m->tx_timeout_ms = (u24(tx + 1) == 0)
            ? 1000u : (u24(tx + 1) * 15625u + 999999u) / 1000000u;
        m->tx_started_ms = m->now_ms;
        m->tx_due_ms = m->now_ms + m->tx_timeout_ms;
        m->mode = SX1262_MODE_RX;
        break;
    default:
        fault(m, CMD_INVALID);
        break;
    }
    if (rx_len > 1 && op != CMD_GET_STATUS && op != CMD_GET_IRQ_STATUS)
        rx[1] = status_byte(m);
    return 0;
}
