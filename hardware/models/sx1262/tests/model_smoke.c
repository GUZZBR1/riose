#include "sx1262_model.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static sx1262_model_t radio;

/* Same call shape as tag_hal_t.spi_transfer; ctx identifies the peripheral. */
static int spi_transfer(void *ctx, const uint8_t *tx, size_t tx_len,
                        uint8_t *rx, size_t rx_len)
{
    return sx1262_model_transfer(ctx, tx, tx_len, rx, rx_len);
}

static void command(const uint8_t *tx, size_t tx_len)
{
    uint8_t rx[16] = {0};
    assert(spi_transfer(&radio, tx, tx_len, rx, tx_len) == 0);
}

int main(void)
{
    uint8_t rx[16] = {0};
    uint8_t long_write[513] = {0x0e, 0x00};
    uint8_t long_rx[513] = {0};
    const uint8_t reset_cfg[] = {0x80, 0x00};          /* standby RC */
    const uint8_t packet_type[] = {0x8a, 0x01};       /* LoRa */
    const uint8_t frequency[] = {0x86, 0x39, 0x30, 0x00, 0x00}; /* 915 MHz word */
    const uint8_t tx_params[] = {0x8e, 0x0a, 0x04};   /* +10 dBm, ramp */
    const uint8_t modulation[] = {0x8b, 0x07, 0x04, 0x01, 0x00};
    const uint8_t packet_params[] = {0x8c, 0x00, 0x08, 0x00, 0x12, 0x01, 0x00};
    const uint8_t base[] = {0x8f, 0x00, 0x80};
    const uint8_t dio_irq[] = {0x08, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00};
    const uint8_t payload[] = {0x0e, 0x00, 0xc1, 0x7a, 0x05, 0x00};
    const uint8_t start_tx[] = {0x83, 0x00, 0x00, 0x00};
    const uint8_t get_irq[] = {0x12, 0x00, 0x00, 0x00};
    const uint8_t clear_irq[] = {0x02, 0x00, 0x01};
    const uint8_t start_tx_timeout[] = {0x83, 0x00, 0x00, 0x01}; /* 15.625 us radio timeout */
    const uint8_t clear_all_irq[] = {0x02, 0x03, 0xff};
    const uint8_t start_rx[] = {0x82, 0x00, 0x00, 0x40}; /* 1 ms timeout */
    const uint8_t start_rx_continuous[] = {0x82, 0x00, 0x00, 0x00};
    const uint8_t long_timeout_tx[] = {0x83, 0xff, 0xff, 0xff};
    const uint8_t equal_timeout_tx[] = {0x83, 0x00, 0x01, 0xc0}; /* 7 ms == TX latency */
    const uint8_t later_timeout_tx[] = {0x83, 0x00, 0x02, 0x00}; /* 8 ms > TX latency */
    const uint8_t start_sleep[] = {0x84, 0x04};
    const uint8_t read_back[] = {0x1e, 0x00, 0x00, 0x00, 0x00, 0x00};
    const uint8_t fifo_wrap[] = {0x0e, 0xff, 0xaa, 0xbb};
    const uint8_t read_wrap[] = {0x1e, 0xff, 0x00, 0x00, 0x00};

    sx1262_model_init(&radio);
    radio.tx_latency_ms = 7;
    command(reset_cfg, sizeof(reset_cfg));
    command(packet_type, sizeof(packet_type)); command(frequency, sizeof(frequency));
    command(tx_params, sizeof(tx_params)); command(modulation, sizeof(modulation));
    command(packet_params, sizeof(packet_params)); command(base, sizeof(base));
    command(dio_irq, sizeof(dio_irq)); command(payload, sizeof(payload));
    assert(radio.rf_frequency_word == 0x39300000u);
    assert(radio.tx_power_dbm == 10);

    /* Valid SX126x LoRa SetPacketParams carries exactly six bytes. */
    assert(!radio.fault);

    assert(spi_transfer(&radio, read_back, sizeof(read_back), rx, sizeof(read_back)) == 0);
    assert(rx[3] == 0xc1 && rx[4] == 0x7a && rx[5] == 0x05);
    command(fifo_wrap, sizeof(fifo_wrap));
    assert(spi_transfer(&radio, read_wrap, sizeof(read_wrap), rx, sizeof(read_wrap)) == 0);
    assert(rx[3] == 0xaa && rx[4] == 0xbb);
    memset(long_write + 2, 0xaa, sizeof(long_write) - 3);
    long_write[sizeof(long_write) - 1] = 0xbb;
    assert(spi_transfer(&radio, long_write, sizeof(long_write), long_rx, sizeof(long_rx)) == 0);
    assert(radio.fifo[0xfe] == 0xbb);
    assert(spi_transfer(&radio, start_tx, sizeof(start_tx), rx, sizeof(start_tx)) == 0);
    assert(radio.tx_pending && radio.mode == SX1262_MODE_TX && radio.tx_count == 1);
    sx1262_model_advance(&radio, 6);
    assert(radio.tx_pending && !sx1262_model_irq(&radio));
    sx1262_model_advance(&radio, 7);
    assert(!radio.tx_pending && (radio.irq_status & SX1262_IRQ_TX_DONE));
    assert(sx1262_model_irq(&radio));
    assert(spi_transfer(&radio, get_irq, sizeof(get_irq), rx, sizeof(get_irq)) == 0);
    assert(rx[2] == 0 && rx[3] == 1);
    assert(spi_transfer(&radio, clear_irq, sizeof(clear_irq), rx, sizeof(clear_irq)) == 0);
    assert(!sx1262_model_irq(&radio));

    radio.tx_latency_ms = 30;
    assert(spi_transfer(&radio, start_tx_timeout, sizeof(start_tx_timeout), rx, sizeof(start_tx_timeout)) == 0);
    sx1262_model_advance(&radio, 8);
    assert(!radio.tx_pending && (radio.irq_status & SX1262_IRQ_TIMEOUT));
    assert(radio.command_status == 0x06);
    assert(spi_transfer(&radio, clear_all_irq, sizeof(clear_all_irq), rx, sizeof(clear_all_irq)) == 0);

    assert(spi_transfer(&radio, start_rx, sizeof(start_rx), rx, sizeof(start_rx)) == 0);
    assert(radio.rx_pending && radio.mode == SX1262_MODE_RX);
    sx1262_model_advance(&radio, radio.now_ms + 1);
    assert(!radio.rx_pending && (radio.irq_status & SX1262_IRQ_TIMEOUT));
    assert(!(radio.irq_status & SX1262_IRQ_TX_DONE));
    assert(spi_transfer(&radio, clear_all_irq, sizeof(clear_all_irq), rx, sizeof(clear_all_irq)) == 0);

    /* At equal TX and timeout deadlines, timeout wins; a later timeout does not. */
    radio.tx_latency_ms = 7;
    assert(spi_transfer(&radio, equal_timeout_tx, sizeof(equal_timeout_tx), rx, sizeof(equal_timeout_tx)) == 0);
    sx1262_model_advance(&radio, radio.now_ms + 7u);
    assert((radio.irq_status & SX1262_IRQ_TIMEOUT) != 0);
    assert((radio.irq_status & SX1262_IRQ_TX_DONE) == 0);
    assert(spi_transfer(&radio, clear_all_irq, sizeof(clear_all_irq), rx, sizeof(clear_all_irq)) == 0);
    assert(spi_transfer(&radio, later_timeout_tx, sizeof(later_timeout_tx), rx, sizeof(later_timeout_tx)) == 0);
    sx1262_model_advance(&radio, radio.now_ms + 100u);
    assert((radio.irq_status & SX1262_IRQ_TX_DONE) != 0);
    assert((radio.irq_status & SX1262_IRQ_TIMEOUT) == 0);
    assert(spi_transfer(&radio, clear_all_irq, sizeof(clear_all_irq), rx, sizeof(clear_all_irq)) == 0);

    /* A running TX keeps its captured deadline if the configured latency changes. */
    radio.tx_latency_ms = 30;
    assert(spi_transfer(&radio, start_tx, sizeof(start_tx), rx, sizeof(start_tx)) == 0);
    radio.tx_latency_ms = 1;
    sx1262_model_advance(&radio, radio.now_ms + 1u);
    assert(radio.tx_pending && !(radio.irq_status & SX1262_IRQ_TX_DONE));
    sx1262_model_advance(&radio, radio.now_ms + 29u);
    assert(!radio.tx_pending && (radio.irq_status & SX1262_IRQ_TX_DONE));
    assert(spi_transfer(&radio, clear_all_irq, sizeof(clear_all_irq), rx, sizeof(clear_all_irq)) == 0);

    /* Continuous RX is bounded to one virtual second for deterministic tests. */
    assert(spi_transfer(&radio, start_rx_continuous, sizeof(start_rx_continuous), rx, sizeof(start_rx_continuous)) == 0);
    sx1262_model_advance(&radio, radio.now_ms + 999u);
    assert(radio.rx_pending);
    sx1262_model_advance(&radio, radio.now_ms + 1u);
    assert(!radio.rx_pending && (radio.irq_status & SX1262_IRQ_TIMEOUT));
    assert(!(radio.irq_status & SX1262_IRQ_TX_DONE));
    assert(spi_transfer(&radio, clear_all_irq, sizeof(clear_all_irq), rx, sizeof(clear_all_irq)) == 0);

    /* Large 24-bit timeouts must not overflow their millisecond conversion. */
    assert(spi_transfer(&radio, long_timeout_tx, sizeof(long_timeout_tx), rx, sizeof(long_timeout_tx)) == 0);
    assert(radio.tx_pending && radio.tx_timeout_ms == 262144u);
    assert(spi_transfer(&radio, start_sleep, sizeof(start_sleep), rx, sizeof(start_sleep)) == 0);
    assert(!radio.tx_pending && !radio.rx_pending && radio.mode == SX1262_MODE_SLEEP);

    /* DIO1 routing is independent from the global IRQ mask. */
    { const uint8_t start_tx_again[] = {0x83, 0, 0, 0};
      const uint8_t dio_irq_disabled[] = {0x08, 0, 1, 0, 0, 0, 0, 0, 0};
      const uint8_t return_to_standby[] = {0x80, 0};
      radio.tx_latency_ms = 7;
      assert(spi_transfer(&radio, return_to_standby, sizeof(return_to_standby), rx, sizeof(return_to_standby)) == 0);
      assert(spi_transfer(&radio, dio_irq, sizeof(dio_irq), rx, sizeof(dio_irq)) == 0);
      assert(spi_transfer(&radio, start_tx_again, sizeof(start_tx_again), rx, sizeof(start_tx_again)) == 0);
      sx1262_model_advance(&radio, radio.now_ms + 7u);
      assert((radio.irq_status & SX1262_IRQ_TX_DONE) != 0);
      assert(sx1262_model_irq(&radio));
      assert(spi_transfer(&radio, dio_irq_disabled, sizeof(dio_irq_disabled), rx, sizeof(dio_irq_disabled)) == 0);
      assert(!sx1262_model_irq(&radio));
    }

    /* Invalid command length is surfaced in command status and diagnostics. */
    { const uint8_t malformed[] = {0x86, 0x01};
      const uint8_t overlong[] = {0x80, 0x00, 0x00};
      assert(spi_transfer(&radio, malformed, sizeof(malformed), rx, sizeof(malformed)) == 0);
      assert(radio.fault && radio.fault_count == 1 && (rx[1] & 0x0e) == 0x08);
      assert(spi_transfer(&radio, overlong, sizeof(overlong), rx, sizeof(overlong)) == 0);
      assert(radio.fault_count == 2 && (rx[1] & 0x0e) == 0x08); }

    /* Reset clears configuration/FIFO/IRQ and any active radio timer. */
    command(payload, sizeof(payload));
    assert(radio.fifo[0] == 0xc1);
    sx1262_model_reset(&radio);
    assert(radio.mode == SX1262_MODE_STANDBY_RC && radio.irq_status == 0);
    assert(radio.rf_frequency_word == 0 && radio.packet_type == 0);
    assert(radio.tx_base == 0 && radio.rx_base == 0 && radio.fifo[0] == 0);
    assert(radio.tx_latency_ms == 7 && !radio.tx_pending && !radio.rx_pending);

    puts("SX1262 model smoke: PASS (configuration, FIFO, virtual-time outcomes, IRQ routing, reset/sleep and malformed commands)");
    return 0;
}
