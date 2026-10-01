#include "tag_firmware.h"
#include "sx1262.h"

#include <stdio.h>
#include <string.h>

typedef struct {
    uint32_t time_ms;
    uint16_t irq;
    bool irq_high;
    tag_imu_sample_t imu;
    uint8_t opcodes[128];
    size_t opcode_count;
    uint8_t packet[64];
    size_t packet_len;
} host_board_t;

static int spi_transfer(void *ctx, const uint8_t *tx, size_t tx_len,
                        uint8_t *rx, size_t rx_len)
{
    host_board_t *board = ctx;
    if (tx_len == 0u || tx_len != rx_len) return -1;
    const uint8_t op = tx[0];
    if (board->opcode_count < sizeof(board->opcodes))
        board->opcodes[board->opcode_count++] = op;
    memset(rx, 0, rx_len);
    if (op == 0x0eu && tx_len >= 3u) {
        board->packet_len = tx_len - 2u;
        memcpy(board->packet, tx + 2u, board->packet_len);
    } else if (op == 0x83u) {
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
    *sample = ((host_board_t *)ctx)->imu;
    return 0;
}
static bool imu_irq(void *ctx) { (void)ctx; return false; }
static bool radio_irq(void *ctx) { return ((host_board_t *)ctx)->irq_high; }
static uint32_t clock_ms(void *ctx) { return ((host_board_t *)ctx)->time_ms; }
static void sleep_ms(void *ctx, uint32_t ms)
{
    ((host_board_t *)ctx)->time_ms += ms;
}

int main(void)
{
    host_board_t board = {0};
    board.imu = (tag_imu_sample_t){.x_mg=500, .y_mg=0, .z_mg=866};
    const tag_hal_t hal = {
        .context=&board, .spi_transfer=spi_transfer, .radio_reset=radio_reset,
        .imu_read=imu_read, .imu_irq_pending=imu_irq,
        .radio_irq_pending=radio_irq, .clock_ms=clock_ms, .sleep_ms=sleep_ms
    };
    const tag_config_t cfg = tag_default_config(0x12345678u);
    tag_firmware_t fw;
    if (tag_firmware_init(&fw, &hal, &cfg) != 0) return 1;

    tag_firmware_step(&fw); /* BOOT -> SELF_TEST */
    tag_firmware_step(&fw); /* probe IMU and configure SX1262 */
    tag_firmware_step(&fw); /* due beacon -> sample */
    tag_firmware_step(&fw); /* classify motion and send */
    tag_firmware_step(&fw); /* IRQ TX_DONE */
    tag_firmware_step(&fw); /* bounded RX window times out */

    if (fw.packets_sent != 1u || fw.failures != 0u ||
        !tag_telemetry_crc_valid(board.packet, board.packet_len) ||
        board.packet_len != 24u || tag_firmware_state(&fw) != TAG_STATE_SLEEP) {
        fprintf(stderr, "host firmware cycle failed: sent=%u failures=%u packet=%zu state=%d\n",
                fw.packets_sent, fw.failures, board.packet_len, fw.state);
        return 2;
    }
    printf("firmware cycle OK: tag=0x%08x state=SLEEP behavior=%u packet=%zuB crc=valid tx=%u opcodes=",
           cfg.tag_id, (unsigned)fw.behavior, board.packet_len, fw.packets_sent);
    for (size_t i = 0; i < board.opcode_count; ++i)
        printf("%s%02X", i == 0u ? "" : " ", board.opcodes[i]);
    putchar('\n');
    return 0;
}
