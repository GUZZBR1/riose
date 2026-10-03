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
    assert(model.registers[LIS2DW12_REG_CTRL2] == LIS2DW12_CTRL2_IF_ADD_INC);
    assert(lis2dw12_i2c_read(&model, 63u, &id, 2u) == LIS2DW12_EINVAL);
    assert(lis2dw12_i2c_read(&model, 0u, NULL, 1u) == LIS2DW12_EINVAL);
}

static void test_odr_timing_and_full_scale(void)
{
    lis2dw12_model_t model, high_performance, low_power_1, low_power_2,
                      on_demand, reserved_mode, reserved_odr;
    const uint8_t ctrl1 = 0x20u; /* low-power ODR code 2 = 12.5 Hz => 80 ms */
    const uint8_t ctrl6_2g = 0x00u;
    const uint8_t ctrl6_4g = 0x10u;
    lis2dw12_init(&model, NULL, NULL);
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL1, &ctrl1, 1u) == LIS2DW12_OK);
    lis2dw12_set_motion(&model, LIS2DW12_MOTION_WALKING);
    lis2dw12_tick(&model, 79u);
    assert(model.sample_number == 0u);
    lis2dw12_tick(&model, 1u);
    assert(model.sample_number == 1u);
    assert(model.registers[LIS2DW12_REG_STATUS] & 1u);

    lis2dw12_set_motion(&model, LIS2DW12_MOTION_STATIONARY);
    lis2dw12_tick(&model, 80u);
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL6, &ctrl6_2g, 1u) == LIS2DW12_OK);
    const int16_t raw_2g = lis2dw12_axis_raw(&model, 2u);
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL6, &ctrl6_4g, 1u) == LIS2DW12_OK);
    const int16_t raw_4g = lis2dw12_axis_raw(&model, 2u);
    assert(raw_2g > 0 && raw_2g == raw_4g * 2);

    const uint8_t ctrl1_12_5_hp = 0x14u; /* ODR code 1 is 12.5 Hz in high-performance mode. */
    lis2dw12_init(&high_performance, NULL, NULL);
    assert(lis2dw12_i2c_write(&high_performance, LIS2DW12_REG_CTRL1,
                              &ctrl1_12_5_hp, 1u) == LIS2DW12_OK);
    lis2dw12_set_motion(&high_performance, LIS2DW12_MOTION_WALKING);
    lis2dw12_tick(&high_performance, 79u);
    assert(high_performance.sample_number == 0u);
    lis2dw12_tick(&high_performance, 1u);
    assert(high_performance.sample_number == 1u);

    const uint8_t ctrl1_lp1_1_6hz = 0x10u;
    lis2dw12_init(&low_power_1, NULL, NULL);
    assert(lis2dw12_i2c_write(&low_power_1, LIS2DW12_REG_CTRL1,
                              &ctrl1_lp1_1_6hz, 1u) == LIS2DW12_OK);
    lis2dw12_tick(&low_power_1, 624u);
    assert(low_power_1.sample_number == 0u);
    lis2dw12_tick(&low_power_1, 1u);
    assert(low_power_1.sample_number == 1u);

    const uint8_t ctrl1_lp2_12_5hz = 0x11u;
    lis2dw12_init(&low_power_2, NULL, NULL);
    assert(lis2dw12_i2c_write(&low_power_2, LIS2DW12_REG_CTRL1,
                              &ctrl1_lp2_12_5hz, 1u) == LIS2DW12_OK);
    lis2dw12_tick(&low_power_2, 79u);
    assert(low_power_2.sample_number == 0u);
    lis2dw12_tick(&low_power_2, 1u);
    assert(low_power_2.sample_number == 1u);

    const uint8_t ctrl1_on_demand = 0x18u;
    lis2dw12_init(&on_demand, NULL, NULL);
    assert(lis2dw12_i2c_write(&on_demand, LIS2DW12_REG_CTRL1,
                              &ctrl1_on_demand, 1u) == LIS2DW12_OK);
    lis2dw12_tick(&on_demand, 1000u);
    assert(on_demand.sample_number == 0u);

    const uint8_t ctrl1_reserved_mode = 0x1cu;
    lis2dw12_init(&reserved_mode, NULL, NULL);
    assert(lis2dw12_i2c_write(&reserved_mode, LIS2DW12_REG_CTRL1,
                              &ctrl1_reserved_mode, 1u) == LIS2DW12_OK);
    lis2dw12_tick(&reserved_mode, 1000u);
    assert(reserved_mode.sample_number == 0u);

    const uint8_t reserved_odr_value = 0xa0u;
    lis2dw12_init(&reserved_odr, NULL, NULL);
    assert(lis2dw12_i2c_write(&reserved_odr, LIS2DW12_REG_CTRL1,
                              &reserved_odr_value, 1u) == LIS2DW12_OK);
    lis2dw12_tick(&reserved_odr, 1000u);
    assert(reserved_odr.sample_number == 0u);
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

    lis2dw12_set_motion(&model, LIS2DW12_MOTION_WALKING);
    uint8_t ctrl1_lp1 = 0x50u;
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL1, &ctrl1_lp1, 1u) == LIS2DW12_OK);
    lis2dw12_tick(&model, 10u);
    assert(lis2dw12_axis_raw(&model, 0u) != 0);
    assert((lis2dw12_axis_raw(&model, 0u) & 0x0f) == 0);

    uint8_t ctrl1_hp = 0x54u;
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL1, &ctrl1_hp, 1u) == LIS2DW12_OK);
    lis2dw12_tick(&model, 10u);
    assert((lis2dw12_axis_raw(&model, 0u) & 0x03) == 0);
}

static void test_wake_irq_and_source_clear(void)
{
    lis2dw12_model_t model;
    uint8_t ctrl1 = 0x30u, route = 0x20u, interrupt_enable = 0x20u;
    uint8_t threshold = 0x01u;
    uint8_t source = 0u;
    irq_count = 0u;
    lis2dw12_init(&model, on_irq, NULL);
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL1, &ctrl1, 1u) == LIS2DW12_OK);
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL4_INT1_PAD_CTRL, &route, 1u) == LIS2DW12_OK);
    /* Routing alone must not assert INT1: CTRL7 is the global gate. */
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_WAKE_UP_THS, &threshold, 1u) == LIS2DW12_OK);
    lis2dw12_set_motion(&model, LIS2DW12_MOTION_RUNNING);
    lis2dw12_tick(&model, 50u);
    assert(!lis2dw12_irq_pending(&model));
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL7,
                              &interrupt_enable, 1u) == LIS2DW12_OK);
    lis2dw12_tick(&model, 50u);
    assert(lis2dw12_irq_pending(&model));
    assert(irq_count == 1u);
    assert(lis2dw12_i2c_read(&model, LIS2DW12_REG_WAKE_UP_SRC, &source, 1u) == LIS2DW12_OK);
    assert(source & 0x08u);
    assert(!lis2dw12_irq_pending(&model));
}

static void test_motion_no_motion_transition(void)
{
    lis2dw12_model_t model;
    const uint8_t ctrl1 = 0x40u; /* ODR code 4 = 50 Hz */
    const uint8_t ctrl5 = 0x40u; /* INT2 sleep-change route */
    const uint8_t ctrl7 = 0x20u;
    const uint8_t wake_threshold_and_sleep = 0x41u;
    uint8_t status = 0u;
    uint8_t sources = 0u;
    irq_count = 0u;
    lis2dw12_init(&model, on_irq, NULL);
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL1, &ctrl1, 1u) == LIS2DW12_OK);
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL5_INT2_PAD_CTRL, &ctrl5, 1u) == LIS2DW12_OK);
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL7, &ctrl7, 1u) == LIS2DW12_OK);
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_WAKE_UP_THS,
                              &wake_threshold_and_sleep, 1u) == LIS2DW12_OK);
    lis2dw12_set_motion(&model, LIS2DW12_MOTION_STATIONARY);
    lis2dw12_tick(&model, 320u); /* default sleep duration is 16 ODR periods */
    assert(lis2dw12_i2c_read(&model, LIS2DW12_REG_STATUS, &status, 1u) == LIS2DW12_OK);
    assert(status & LIS2DW12_STATUS_SLEEP_STATE);
    assert(lis2dw12_irq_pending(&model));
    assert(irq_count == 1u);

    assert(lis2dw12_i2c_read(&model, LIS2DW12_REG_ALL_INT_SRC, &sources, 1u) == LIS2DW12_OK);
    assert(sources & 0x20u);
    assert(!lis2dw12_irq_pending(&model));

    lis2dw12_set_motion(&model, LIS2DW12_MOTION_WALKING);
    lis2dw12_tick(&model, 20u);
    assert(lis2dw12_i2c_read(&model, LIS2DW12_REG_STATUS, &status, 1u) == LIS2DW12_OK);
    assert((status & LIS2DW12_STATUS_SLEEP_STATE) == 0u);
    assert(lis2dw12_irq_pending(&model));
    assert(irq_count == 2u);
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

static void test_i2c_timeout_recovers(void)
{
    lis2dw12_model_t model;
    uint8_t id = 0u;
    lis2dw12_init(&model, NULL, NULL);
    lis2dw12_timeout_next_i2c(&model, 1u);
    assert(lis2dw12_i2c_read(&model, LIS2DW12_REG_WHO_AM_I, &id, 1u) == LIS2DW12_ETIMEDOUT);
    assert(lis2dw12_i2c_read(&model, LIS2DW12_REG_WHO_AM_I, &id, 1u) == LIS2DW12_OK);
    assert(id == LIS2DW12_WHO_AM_I_VALUE);
}

static void test_software_reset_after_fault_restores_device(void)
{
    lis2dw12_model_t model;
    uint8_t ctrl1 = 0x40u;
    uint8_t reset = LIS2DW12_CTRL2_SOFT_RESET;
    uint8_t id = 0u;
    lis2dw12_init(&model, NULL, NULL);
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL1, &ctrl1, 1u) == LIS2DW12_OK);
    lis2dw12_fail_next_i2c(&model, 1u);
    assert(lis2dw12_i2c_read(&model, LIS2DW12_REG_WHO_AM_I, &id, 1u) == LIS2DW12_EIO);
    assert(lis2dw12_i2c_write(&model, LIS2DW12_REG_CTRL2, &reset, 1u) == LIS2DW12_OK);
    assert(model.registers[LIS2DW12_REG_CTRL1] == 0u);
    assert(model.registers[LIS2DW12_REG_CTRL2] == LIS2DW12_CTRL2_IF_ADD_INC);
    assert(lis2dw12_i2c_read(&model, LIS2DW12_REG_WHO_AM_I, &id, 1u) == LIS2DW12_OK);
    assert(id == LIS2DW12_WHO_AM_I_VALUE);
}

static void configure_wake(lis2dw12_model_t *model)
{
    const uint8_t ctrl1 = 0x40u; /* ODR code 4 = 50 Hz */
    const uint8_t route = 0x20u;
    const uint8_t interrupt_enable = 0x20u;
    const uint8_t threshold = 0x01u;
    assert(lis2dw12_i2c_write(model, LIS2DW12_REG_CTRL1, &ctrl1, 1u) == LIS2DW12_OK);
    assert(lis2dw12_i2c_write(model, LIS2DW12_REG_CTRL4_INT1_PAD_CTRL, &route, 1u) == LIS2DW12_OK);
    assert(lis2dw12_i2c_write(model, LIS2DW12_REG_CTRL7, &interrupt_enable, 1u) == LIS2DW12_OK);
    assert(lis2dw12_i2c_write(model, LIS2DW12_REG_WAKE_UP_THS, &threshold, 1u) == LIS2DW12_OK);
    lis2dw12_set_motion(model, LIS2DW12_MOTION_RUNNING);
}

static void test_irq_absent_and_stuck_recover(void)
{
    lis2dw12_model_t absent, stuck;
    irq_count = 0u;
    lis2dw12_init(&absent, on_irq, NULL);
    lis2dw12_set_irq_faults(&absent, true, false);
    configure_wake(&absent);
    lis2dw12_tick(&absent, 20u);
    assert(!lis2dw12_irq_pending(&absent));
    assert(irq_count == 0u);
    lis2dw12_set_irq_faults(&absent, false, false);
    assert(lis2dw12_irq_pending(&absent));
    lis2dw12_clear_irq(&absent);
    assert(!lis2dw12_irq_pending(&absent));

    lis2dw12_init(&stuck, on_irq, NULL);
    lis2dw12_set_irq_faults(&stuck, false, true);
    configure_wake(&stuck);
    lis2dw12_tick(&stuck, 20u);
    assert(lis2dw12_irq_pending(&stuck));
    lis2dw12_clear_irq(&stuck);
    assert(lis2dw12_irq_pending(&stuck));
    lis2dw12_set_irq_faults(&stuck, false, false);
    lis2dw12_clear_irq(&stuck);
    assert(!lis2dw12_irq_pending(&stuck));
    uint8_t source = 0xffu;
    assert(lis2dw12_i2c_read(&stuck, LIS2DW12_REG_WAKE_UP_SRC, &source, 1u) == LIS2DW12_OK);
    assert(source == 0u);
}

static void test_reset_after_irq_fault_restores_defaults(void)
{
    lis2dw12_model_t model;
    uint8_t id = 0u;
    lis2dw12_init(&model, NULL, NULL);
    lis2dw12_set_irq_faults(&model, false, true);
    configure_wake(&model);
    lis2dw12_tick(&model, 20u);
    assert(lis2dw12_irq_pending(&model));
    lis2dw12_init(&model, NULL, NULL);
    assert(!lis2dw12_irq_pending(&model));
    assert(lis2dw12_i2c_read(&model, LIS2DW12_REG_WHO_AM_I, &id, 1u) == LIS2DW12_OK);
    assert(id == LIS2DW12_WHO_AM_I_VALUE);
    assert(model.registers[LIS2DW12_REG_CTRL1] == 0u);
    lis2dw12_tick(&model, 100u);
    assert(model.sample_number == 0u);
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
    test_odr_timing_and_full_scale();
    test_quantized_output_and_profile();
    test_wake_irq_and_source_clear();
    test_motion_no_motion_transition();
    test_i2c_failures_recover();
    test_i2c_timeout_recovers();
    test_software_reset_after_fault_restores_device();
    test_irq_absent_and_stuck_recover();
    test_reset_after_irq_fault_restores_defaults();
    test_power_down_holds_output();
    puts("LIS2DW12 model: 9 test groups passed");
    return 0;
}
