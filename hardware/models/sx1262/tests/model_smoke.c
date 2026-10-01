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
    const uint8_t start_rx[] = {0x82, 0x00, 0x00, 0x40}; /* bounded timeout */
    const uint8_t read_back[] = {0x1e, 0x00, 0x00, 0x00, 0x00, 0x00};

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

    /* Invalid command length is surfaced in command status and diagnostics. */
    { const uint8_t malformed[] = {0x86, 0x01};
      assert(spi_transfer(&radio, malformed, sizeof(malformed), rx, sizeof(malformed)) == 0);
      assert(radio.fault && radio.fault_count == 1 && (rx[1] & 0x0e) == 0x08); }

    puts("SX1262 model smoke: PASS (SPI config, FIFO, TX_DONE/TIMEOUT, IRQ clear, malformed command)");
    return 0;
}
