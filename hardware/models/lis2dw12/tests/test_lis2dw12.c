#include "lis2dw12_model.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static unsigned irq_count;
static void on_irq(void *unused)
{
    (void)unused;
    ++irq_count;
}

static int16_t decode_le(const uint8_t *bytes)
{
    return (int16_t)((uint16_t)bytes[0] | ((uint16_t)bytes[1] << 8u));
}

static void test_reset_identity_and_arguments(void)
{
    lis2dw12_model_t model;
    uint8_t id = 0u;
    lis2dw12_init(&model, NULL, NULL);
    assert(lis2dw12_i2c_read(&model, LIS2DW12_REG_WHO_AM_I, &id, 1u) == LIS2DW12_OK);
    assert(id == LIS2DW12_WHO_AM_I_VALUE);
    assert(lis2dw12_i2c_read(&model, 63u, &id, 2u) == LIS2DW12_EINVAL);
    assert(lis2dw12_i2c_read(&model, 0u, NULL, 1u) == LIS2DW12_EINVAL);
}

static void test_quantized_output_and_profile(void)
{
    lis2dw12_model_t model;
    uint8_t ctrl = 0x30u; /* 25 Hz ODR, high-performance mode */
    uint8_t bytes[6] = {0};
    lis2dw12_init(&model, NULL, NULL);
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL1, &ctrl, 1u) == LIS2DW12_OK);
    lis2dw12_set_motion(&model, LIS2DW12_MOTION_WALKING);
    lis2dw12_tick(&model, 125u);
    assert(lis2dw12_i2c_read(&model, LIS2DW12_REG_OUT_X_L, bytes, sizeof(bytes)) == LIS2DW12_OK);
    assert(decode_le(&bytes[0]) != 0 || decode_le(&bytes[2]) != 0 || decode_le(&bytes[4]) != 0);
    assert(model.registers[LIS2DW12_REG_STATUS] & 1u);

    lis2dw12_set_motion(&model, LIS2DW12_MOTION_STATIONARY);
    lis2dw12_tick(&model, 100u);
    assert(lis2dw12_i2c_read(&model, LIS2DW12_REG_OUT_X_L, bytes, sizeof(bytes)) == LIS2DW12_OK);
    assert(decode_le(&bytes[0]) == 0);
    assert(decode_le(&bytes[2]) == 0);
    assert(decode_le(&bytes[4]) > 0);
}

static void test_wake_irq_and_source_clear(void)
{
    lis2dw12_model_t model;
    uint8_t ctrl1 = 0x30u, route = 0x08u, threshold = 0x01u;
    uint8_t source = 0u;
    irq_count = 0u;
    lis2dw12_init(&model, on_irq, NULL);
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL1, &ctrl1, 1u) == LIS2DW12_OK);
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL4_INT1_PAD_CTRL, &route, 1u) == LIS2DW12_OK);
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_WAKE_UP_THS, &threshold, 1u) == LIS2DW12_OK);
    lis2dw12_set_motion(&model, LIS2DW12_MOTION_RUNNING);
    lis2dw12_tick(&model, 50u);
    assert(lis2dw12_irq_pending(&model));
    assert(irq_count == 1u);
    assert(lis2dw12_i2c_read(&model, LIS2DW12_REG_WAKE_UP_SRC, &source, 1u) == LIS2DW12_OK);
    assert(source & 0x08u);
    assert(!lis2dw12_irq_pending(&model));
}

static void test_i2c_failures_recover(void)
{
    lis2dw12_model_t model;
    uint8_t id = 0u;
    lis2dw12_init(&model, NULL, NULL);
    lis2dw12_fail_next_i2c(&model, 2u);
    assert(lis2dw12_i2c_read(&model, LIS2DW12_REG_WHO_AM_I, &id, 1u) == LIS2DW12_EIO);
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL1, &id, 1u) == LIS2DW12_EIO);
    assert(lis2dw12_i2c_read(&model, LIS2DW12_REG_WHO_AM_I, &id, 1u) == LIS2DW12_OK);
    assert(id == LIS2DW12_WHO_AM_I_VALUE);
}

static void test_power_down_holds_output(void)
{
    lis2dw12_model_t model;
    uint8_t output[6], before[6], ctrl = 0u;
    lis2dw12_init(&model, NULL, NULL);
    assert(lis2dw12_i2c_read(&model, LIS2DW12_REG_OUT_X_L, before, sizeof(before)) == LIS2DW12_OK);
    lis2dw12_set_motion(&model, LIS2DW12_MOTION_ABNORMAL);
    lis2dw12_tick(&model, 500u);
    assert(lis2dw12_i2c_read(&model, LIS2DW12_REG_OUT_X_L, output, sizeof(output)) == LIS2DW12_OK);
    assert(memcmp(output, before, sizeof(before)) == 0);
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL1, &ctrl, 1u) == LIS2DW12_OK);
}

int main(void)
{
    test_reset_identity_and_arguments();
    test_quantized_output_and_profile();
    test_wake_irq_and_source_clear();
    test_i2c_failures_recover();
    test_power_down_holds_output();
    puts("LIS2DW12 model: 5 test groups passed");
    return 0;
}
