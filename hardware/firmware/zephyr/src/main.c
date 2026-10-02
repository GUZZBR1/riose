#include <errno.h>
#include <stdint.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/spi.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include "tag_firmware.h"

LOG_MODULE_REGISTER(cattle_tag, LOG_LEVEL_INF);

K_SEM_DEFINE(tag_event_sem, 0, 1);
static struct gpio_callback imu_gpio_cb;
static struct gpio_callback radio_gpio_cb;

#if !DT_NODE_HAS_STATUS(DT_ALIAS(tag_radio), okay) || \
    !DT_NODE_HAS_STATUS(DT_ALIAS(tag_imu), okay) || \
    !DT_NODE_HAS_STATUS(DT_ALIAS(tag_radio_busy), okay) || \
    !DT_NODE_HAS_STATUS(DT_ALIAS(tag_state_trace), okay)
#error "Add tag-radio, tag-imu, tag-radio-busy, and tag-state-trace aliases"
#endif

static const struct spi_dt_spec radio_spi = SPI_DT_SPEC_GET(
    DT_ALIAS(tag_radio), SPI_OP_MODE_MASTER | SPI_WORD_SET(8) |
                         SPI_TRANSFER_MSB, 0);
static const struct i2c_dt_spec imu_i2c = I2C_DT_SPEC_GET(DT_ALIAS(tag_imu));
static const struct gpio_dt_spec radio_reset =
    GPIO_DT_SPEC_GET(DT_ALIAS(tag_radio_reset), gpios);
static const struct gpio_dt_spec radio_busy =
    GPIO_DT_SPEC_GET(DT_ALIAS(tag_radio_busy), gpios);
static const struct gpio_dt_spec radio_dio1 =
    GPIO_DT_SPEC_GET(DT_ALIAS(tag_radio_dio1), gpios);
static const struct gpio_dt_spec radio_ant_switch =
    GPIO_DT_SPEC_GET(DT_ALIAS(tag_radio_ant_switch), gpios);
static const struct gpio_dt_spec imu_int =
    GPIO_DT_SPEC_GET(DT_ALIAS(tag_imu_int), gpios);
static const struct gpio_dt_spec state_trace_pins[] = {
    GPIO_DT_SPEC_GET_BY_IDX(DT_ALIAS(tag_state_trace), gpios, 0),
    GPIO_DT_SPEC_GET_BY_IDX(DT_ALIAS(tag_state_trace), gpios, 1),
    GPIO_DT_SPEC_GET_BY_IDX(DT_ALIAS(tag_state_trace), gpios, 2),
};

static int spi_transfer(void *context, const uint8_t *tx, size_t tx_len,
                        uint8_t *rx, size_t rx_len)
{
    ARG_UNUSED(context);
    if (tx == NULL || rx == NULL || tx_len == 0 || tx_len != rx_len) {
        return -EINVAL;
    }

    /* SX1262 drives BUSY high while it cannot accept another command. Check
     * before every transaction, including the first one after reset. */
    const int64_t deadline = k_uptime_get() + 100;
    int busy;
    do {
        busy = gpio_pin_get_dt(&radio_busy);
        if (busy < 0) return busy;
        if (busy == 0) break;
        k_msleep(1);
    } while (k_uptime_get() < deadline);
    if (busy != 0) return -ETIMEDOUT;

    struct spi_buf tx_buf = {.buf = (void *)tx, .len = tx_len};
    struct spi_buf rx_buf = {.buf = rx, .len = rx_len};
    const struct spi_buf_set tx_set = {.buffers = &tx_buf, .count = 1};
    const struct spi_buf_set rx_set = {.buffers = &rx_buf, .count = 1};
    return spi_transceive_dt(&radio_spi, &tx_set, &rx_set);
}

static int radio_reset_fn(void *context)
{
    ARG_UNUSED(context);
    int rc = gpio_pin_set_dt(&radio_reset, 1);
    if (rc != 0) return rc;
    k_msleep(2);
    rc = gpio_pin_set_dt(&radio_reset, 0);
    if (rc != 0) return rc;
    k_msleep(5);
    return 0;
}

static int imu_write_register(uint8_t reg, uint8_t value)
{
    const uint8_t bytes[] = {reg, value};
    return i2c_write_dt(&imu_i2c, bytes, sizeof(bytes));
}

static int imu_configure(void)
{
    uint8_t reg = 0x0f; /* WHO_AM_I: LIS2DW12 returns 0x44. */
    uint8_t identity = 0;
    int rc = i2c_write_read_dt(&imu_i2c, &reg, sizeof(reg), &identity,
                               sizeof(identity));
    if (rc != 0) return rc;
    if (identity != 0x44) return -ENODEV;
    rc = imu_write_register(0x21, 0x08); /* CTRL2: block data update */
    if (rc != 0) return rc;
    rc = imu_write_register(0x20, 0x14); /* CTRL1: 12.5 Hz, low-power mode */
    if (rc != 0) return rc;
    rc = imu_write_register(0x34, 0x02); /* WAKE_UP_THS: 62.5 mg at +/-2 g */
    if (rc != 0) return rc;
    rc = imu_write_register(0x35, 0x00); /* WAKE_UP_DUR: no extra debounce */
    if (rc != 0) return rc;

    /* Source registers are read-to-clear; discard any power-up/latching event
     * before enabling the route and global interrupt gate. */
    uint8_t source_reg = 0x38; /* WAKE_UP_SRC */
    uint8_t source = 0;
    rc = i2c_write_read_dt(&imu_i2c, &source_reg, sizeof(source_reg),
                           &source, sizeof(source));
    if (rc != 0) return rc;
    source_reg = 0x3b; /* ALL_INT_SRC */
    rc = i2c_write_read_dt(&imu_i2c, &source_reg, sizeof(source_reg),
                           &source, sizeof(source));
    if (rc != 0) return rc;
    rc = imu_write_register(0x23, 0x20); /* CTRL4.INT1_WU (bit 5) -> INT1 */
    if (rc != 0) return rc;
    return imu_write_register(0x3f, 0x20); /* CTRL7.INTERRUPTS_ENABLE */
}

static int imu_read_fn(void *context, tag_imu_sample_t *sample)
{
    ARG_UNUSED(context);
    if (sample == NULL) return -EINVAL;
    uint8_t reg = 0xa8; /* OUT_X_L | auto increment */
    uint8_t data[6] = {0};
    int rc = i2c_write_read_dt(&imu_i2c, &reg, sizeof(reg), data, sizeof(data));
    if (rc != 0) return rc;

    for (size_t axis = 0; axis < 3; ++axis) {
        const int16_t raw16 = (int16_t)((uint16_t)data[axis * 2] |
                               ((uint16_t)data[axis * 2 + 1] << 8));
        /* LIS2DW12 14-bit output is left-aligned; +/-2 g sensitivity is
         * 0.061 mg per 12-bit sample. Return integer mg to the HAL contract. */
        const int32_t raw12 = raw16 >> 4;
        const int16_t mg = (int16_t)((raw12 * 61) / 1000);
        if (axis == 0) sample->x_mg = mg;
        else if (axis == 1) sample->y_mg = mg;
        else sample->z_mg = mg;
    }
    uint8_t source_reg = 0x38; /* Reading WAKE_UP_SRC clears the latched WU event. */
    uint8_t wake_source = 0;
    rc = i2c_write_read_dt(&imu_i2c, &source_reg, sizeof(source_reg),
                           &wake_source, sizeof(wake_source));
    if (rc != 0) return rc;
    sample->interrupt_flags = (wake_source & 0x08u) != 0u
        ? TAG_IMU_FLAG_WAKE_UP : 0u;
    return 0;
}

static bool imu_irq_pending(void *context)
{
    ARG_UNUSED(context);
    return gpio_pin_get_dt(&imu_int) > 0;
}

static bool radio_irq_pending(void *context)
{
    ARG_UNUSED(context);
    return gpio_pin_get_dt(&radio_dio1) > 0;
}

static uint32_t clock_ms(void *context)
{
    ARG_UNUSED(context);
    return k_uptime_get_32();
}

static void sleep_ms(void *context, uint32_t duration_ms)
{
    ARG_UNUSED(context);
    k_sleep(K_MSEC(duration_ms));
}

static void tag_gpio_isr(const struct device *port, struct gpio_callback *cb,
                         gpio_port_pins_t pins)
{
    ARG_UNUSED(port);
    ARG_UNUSED(cb);
    ARG_UNUSED(pins);
    k_sem_give(&tag_event_sem);
}

static void wait_for_event(void *context, uint32_t timeout_ms)
{
    ARG_UNUSED(context);
    /* Level check closes the gap between the FSM's IRQ check and taking the
     * semaphore. INT1/DIO1 callbacks then wake the MCU without periodic polls. */
    if (gpio_pin_get_dt(&imu_int) > 0 || gpio_pin_get_dt(&radio_dio1) > 0) return;
    (void)k_sem_take(&tag_event_sem, K_MSEC(timeout_ms));
}

static void state_trace(void *context, tag_state_t state)
{
    ARG_UNUSED(context);
    const uint8_t code = (uint8_t)state;
    for (size_t bit = 0; bit < ARRAY_SIZE(state_trace_pins); ++bit) {
        (void)gpio_pin_set_dt(&state_trace_pins[bit], (code >> bit) & 1u);
    }
}

int main(void)
{
    if (!spi_is_ready_dt(&radio_spi) || !i2c_is_ready_dt(&imu_i2c) ||
        !gpio_is_ready_dt(&radio_reset) || !gpio_is_ready_dt(&radio_busy) ||
        !gpio_is_ready_dt(&radio_dio1) || !gpio_is_ready_dt(&radio_ant_switch) ||
        !gpio_is_ready_dt(&imu_int)) {
        LOG_ERR("A required SPI, I2C, or GPIO device is not ready");
        return -ENODEV;
    }
    int rc = gpio_pin_configure_dt(&radio_reset, GPIO_OUTPUT_INACTIVE);
    if (rc != 0) return rc;
    rc = gpio_pin_configure_dt(&radio_busy, GPIO_INPUT);
    if (rc != 0) return rc;
    rc = gpio_pin_configure_dt(&radio_dio1, GPIO_INPUT);
    if (rc != 0) return rc;
    /* Shield ANT_SW is held high; SX1262 DIO2 selects TX/RX automatically. */
    rc = gpio_pin_configure_dt(&radio_ant_switch, GPIO_OUTPUT_ACTIVE);
    if (rc != 0) return rc;
    rc = gpio_pin_configure_dt(&imu_int, GPIO_INPUT);
    if (rc != 0) return rc;
    for (size_t i = 0; i < ARRAY_SIZE(state_trace_pins); ++i) {
        if (!gpio_is_ready_dt(&state_trace_pins[i])) return -ENODEV;
        rc = gpio_pin_configure_dt(&state_trace_pins[i], GPIO_OUTPUT_INACTIVE);
        if (rc != 0) return rc;
    }
    gpio_init_callback(&imu_gpio_cb, tag_gpio_isr, BIT(imu_int.pin));
    rc = gpio_add_callback(imu_int.port, &imu_gpio_cb);
    if (rc != 0) return rc;
    rc = gpio_pin_interrupt_configure_dt(&imu_int, GPIO_INT_EDGE_TO_ACTIVE);
    if (rc != 0) return rc;
    gpio_init_callback(&radio_gpio_cb, tag_gpio_isr, BIT(radio_dio1.pin));
    rc = gpio_add_callback(radio_dio1.port, &radio_gpio_cb);
    if (rc != 0) return rc;
    rc = gpio_pin_interrupt_configure_dt(&radio_dio1, GPIO_INT_EDGE_TO_ACTIVE);
    if (rc != 0) return rc;
    rc = imu_configure();
    if (rc != 0) {
        LOG_ERR("LIS2DW12 I2C setup failed (%d)", rc);
        return rc;
    }

    const tag_hal_t hal = {
        .context = NULL,
        .spi_transfer = spi_transfer,
        .radio_reset = radio_reset_fn,
        .imu_read = imu_read_fn,
        .imu_irq_pending = imu_irq_pending,
        .radio_irq_pending = radio_irq_pending,
        .clock_ms = clock_ms,
        .sleep_ms = sleep_ms,
        .wait_for_event = wait_for_event,
        .state_trace = state_trace,
    };
    tag_config_t config = tag_default_config(CONFIG_TAG_ID);
    config.rf_frequency_hz = CONFIG_TAG_RF_FREQUENCY_HZ;
    config.tx_power_dbm = CONFIG_TAG_TX_POWER_DBM;
    config.battery_mv = CONFIG_TAG_BATTERY_MV;
    static tag_firmware_t firmware;
    rc = tag_firmware_init(&firmware, &hal, &config);
    if (rc != 0) return rc;
    LOG_INF("C tag firmware started (tag id %u)", config.tag_id);

    while (true) tag_firmware_step(&firmware);
    return 0;
}
