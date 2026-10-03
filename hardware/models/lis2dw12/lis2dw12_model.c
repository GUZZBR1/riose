#include "lis2dw12_model.h"

#include <string.h>

static const int16_t sine_q10[16] = {
    0, 392, 724, 946, 1024, 946, 724, 392,
    0, -392, -724, -946, -1024, -946, -724, -392,
};

static int32_t wave(int amplitude, uint32_t frequency_millihz,
                    uint32_t phase_q16, uint64_t elapsed_ms)
{
    const uint64_t phase_scale = 16u * 65536u;
    uint64_t phase = (elapsed_ms * frequency_millihz * phase_scale) / 1000000u;
    phase = (phase + (uint64_t)phase_q16 * 16u) % phase_scale;
    const unsigned index = (unsigned)(phase / 65536u);
    const uint32_t fraction = (uint32_t)(phase % 65536u);
    const int32_t a = sine_q10[index];
    const int32_t b = sine_q10[(index + 1u) % 16u];
    const int32_t sample = (a * (int32_t)(65536u - fraction) +
                            b * (int32_t)fraction) / 65536;
    return (sample * amplitude) / 1024;
}

static uint32_t next_random(lis2dw12_model_t *model)
{
    /* xorshift32: compact, portable and deterministic across host toolchains. */
    uint32_t value = model->random_state;
    value ^= value << 13u;
    value ^= value >> 17u;
    value ^= value << 5u;
    model->random_state = value;
    return value;
}

static void store_axis(lis2dw12_model_t *model, unsigned axis)
{
    const uint8_t low_register = (uint8_t)(LIS2DW12_REG_OUT_X_L + (axis * 2u));
    const int16_t raw = lis2dw12_axis_raw(model, axis);
    model->registers[low_register] = (uint8_t)((uint16_t)raw & 0xffu);
    model->registers[(uint8_t)(low_register + 1u)] = (uint8_t)(((uint16_t)raw >> 8u) & 0xffu);
}

static bool odr_enabled(const lis2dw12_model_t *model)
{
    return (model->registers[LIS2DW12_REG_CTRL1] & 0xf0u) != 0u;
}

static unsigned full_scale_g(const lis2dw12_model_t *model)
{
    static const unsigned scales[] = {2u, 4u, 8u, 16u};
    return scales[(model->registers[LIS2DW12_REG_CTRL6] >> 4u) & 0x03u];
}

int16_t lis2dw12_axis_raw(const lis2dw12_model_t *model, unsigned axis)
{
    if (model == NULL || axis >= 3u) {
        return 0;
    }
    /* Quantize physical mg to the signed 16-bit output range for the configured FS. */
    const int32_t denominator = (int32_t)(full_scale_g(model) * 1000u);
    int32_t raw = ((int32_t)model->acceleration_mg[axis] * 32768) / denominator;
    if (raw > 32767) raw = 32767;
    if (raw < -32768) raw = -32768;
    return (int16_t)raw;
}

static void update_irq(lis2dw12_model_t *model)
{
    const int threshold_mg = (int)(((uint32_t)(model->registers[LIS2DW12_REG_WAKE_UP_THS] & 0x3fu) *
                                   full_scale_g(model) * 1000u) / 64u);
    int peak_delta = 0;
    for (unsigned axis = 0; axis < 3u; ++axis) {
        int delta = (int)model->acceleration_mg[axis] - (int)model->previous_acceleration_mg[axis];
        if (delta < 0) delta = -delta;
        if (delta > peak_delta) peak_delta = delta;
    }
    /* ST LIS2DW12: CTRL4.INT1_WU is bit 5 (0x20); CTRL7.INTERRUPTS_ENABLE
     * is also bit 5 (0x20). See AN5038, wake-up interrupt configuration. */
    const bool wake_routed =
        (model->registers[LIS2DW12_REG_CTRL4_INT1_PAD_CTRL] & 0x20u) != 0u;
    const bool interrupts_enabled =
        (model->registers[LIS2DW12_REG_CTRL7] & 0x20u) != 0u;
    if (wake_routed && interrupts_enabled && threshold_mg > 0 &&
        peak_delta >= threshold_mg && !model->irq_latched) {
        model->irq_latched = true;
        model->registers[LIS2DW12_REG_WAKE_UP_SRC] = 0x08u; /* WU_IA */
        model->registers[LIS2DW12_REG_ALL_INT_SRC] |= 0x08u;
        if (model->irq_callback != NULL) {
            model->irq_callback(model->irq_user_data);
        }
    }
}

void lis2dw12_init(lis2dw12_model_t *model,
                   lis2dw12_irq_callback_t irq_callback,
                   void *irq_user_data)
{
    if (model == NULL) return;
    memset(model, 0, sizeof(*model));
    model->registers[LIS2DW12_REG_WHO_AM_I] = LIS2DW12_WHO_AM_I_VALUE;
    model->registers[LIS2DW12_REG_WAKE_UP_THS] = 0x02u;
    model->acceleration_mg[2] = 1000;
    model->previous_acceleration_mg[2] = 1000;
    model->motion = LIS2DW12_MOTION_STATIONARY;
    model->random_state = 0x6d2b79f5u;
    model->irq_callback = irq_callback;
    model->irq_user_data = irq_user_data;
    model->initialized = true;
    store_axis(model, 0u);
    store_axis(model, 1u);
    store_axis(model, 2u);
}

static lis2dw12_result_t bus_check(lis2dw12_model_t *model,
                                   uint8_t first_register,
                                   const void *buffer,
                                   size_t length)
{
    if (model == NULL || !model->initialized || buffer == NULL || length == 0u ||
        first_register >= LIS2DW12_REGISTER_COUNT ||
        length > (size_t)(LIS2DW12_REGISTER_COUNT - first_register)) {
        return LIS2DW12_EINVAL;
    }
    if (model->fail_transactions > 0u) {
        --model->fail_transactions;
        return LIS2DW12_EIO;
    }
    if (model->timeout_transactions > 0u) {
        --model->timeout_transactions;
        return LIS2DW12_ETIMEOUT;
    }
    return LIS2DW12_OK;
}

lis2dw12_result_t lis2dw12_i2c_read(lis2dw12_model_t *model,
                                     uint8_t first_register,
                                     uint8_t *destination,
                                     size_t length)
{
    const lis2dw12_result_t check = bus_check(model, first_register, destination, length);
    if (check != LIS2DW12_OK) return check;
    memcpy(destination, &model->registers[first_register], length);
    for (size_t i = 0; i < length; ++i) {
        const uint8_t reg = (uint8_t)(first_register + i);
        if (reg == LIS2DW12_REG_WAKE_UP_SRC || reg == LIS2DW12_REG_ALL_INT_SRC) {
            lis2dw12_clear_irq(model);
            break;
        }
    }
    return LIS2DW12_OK;
}

lis2dw12_result_t lis2dw12_i2c_write(lis2dw12_model_t *model,
                                      uint8_t first_register,
                                      const uint8_t *source,
                                      size_t length)
{
    const lis2dw12_result_t check = bus_check(model, first_register, source, length);
    if (check != LIS2DW12_OK) return check;
    for (size_t i = 0; i < length; ++i) {
        const uint8_t reg = (uint8_t)(first_register + i);
        /* Identity/status/output registers are read-only in the virtual part. */
        if (reg == LIS2DW12_REG_WHO_AM_I || reg == LIS2DW12_REG_STATUS ||
            (reg >= LIS2DW12_REG_OUT_X_L && reg <= LIS2DW12_REG_OUT_Z_H) ||
            reg == LIS2DW12_REG_WAKE_UP_SRC || reg == LIS2DW12_REG_ALL_INT_SRC) {
            continue;
        }
        model->registers[reg] = source[i];
    }
    return LIS2DW12_OK;
}

void lis2dw12_set_motion(lis2dw12_model_t *model, lis2dw12_motion_t motion)
{
    if (model == NULL || motion > LIS2DW12_MOTION_RANDOM_MOVEMENT) return;
    model->motion = motion;
}

void lis2dw12_set_motion_seed(lis2dw12_model_t *model, uint32_t seed)
{
    if (model == NULL) return;
    model->random_state = seed == 0u ? 0x6d2b79f5u : seed;
}

void lis2dw12_tick(lis2dw12_model_t *model, uint32_t elapsed_ms)
{
    if (model == NULL || !model->initialized) return;
    model->elapsed_ms += elapsed_ms;
    if (!odr_enabled(model)) return;

    model->previous_acceleration_mg[0] = model->acceleration_mg[0];
    model->previous_acceleration_mg[1] = model->acceleration_mg[1];
    model->previous_acceleration_mg[2] = model->acceleration_mg[2];
    switch (model->motion) {
    case LIS2DW12_MOTION_STATIONARY:
        model->acceleration_mg[0] = 0;
        model->acceleration_mg[1] = 0;
        model->acceleration_mg[2] = 1000;
        break;
    case LIS2DW12_MOTION_GRAZING:
        model->acceleration_mg[0] = (int16_t)wave(70, 350, 0, model->elapsed_ms);
        model->acceleration_mg[1] = (int16_t)wave(40, 210, 0, model->elapsed_ms);
        model->acceleration_mg[2] = (int16_t)(1000 + wave(30, 350, 0, model->elapsed_ms));
        break;
    case LIS2DW12_MOTION_WALKING:
        model->acceleration_mg[0] = (int16_t)wave(260, 1800, 0, model->elapsed_ms);
        model->acceleration_mg[1] = (int16_t)wave(110, 1800, 10430, model->elapsed_ms);
        model->acceleration_mg[2] = (int16_t)(1000 + wave(180, 1800, 0, model->elapsed_ms));
        break;
    case LIS2DW12_MOTION_RUNNING:
        model->acceleration_mg[0] = (int16_t)wave(900, 3200, 0, model->elapsed_ms);
        model->acceleration_mg[1] = (int16_t)wave(500, 3200, 8342, model->elapsed_ms);
        model->acceleration_mg[2] = (int16_t)(1000 + wave(650, 3200, 0, model->elapsed_ms));
        break;
    case LIS2DW12_MOTION_ABNORMAL:
        model->acceleration_mg[0] = ((model->sample_number % 4u) == 0u) ? 1800 : -1500;
        model->acceleration_mg[1] = ((model->sample_number % 4u) == 0u) ? -1100 : 900;
        model->acceleration_mg[2] = ((model->sample_number % 4u) == 0u) ? 2100 : -1700;
        break;
    case LIS2DW12_MOTION_IMPACT:
        /* Illustrative periodic impulse. This is a test vector, not cattle data. */
        if ((model->sample_number % 16u) == 0u) {
            model->acceleration_mg[0] = 1800;
            model->acceleration_mg[1] = -1400;
            model->acceleration_mg[2] = 2400;
        } else {
            model->acceleration_mg[0] = 0;
            model->acceleration_mg[1] = 0;
            model->acceleration_mg[2] = 1000;
        }
        break;
    case LIS2DW12_MOTION_RANDOM_MOVEMENT:
        /* Seeded bounded samples in mg; deterministic for a seed and tick sequence. */
        model->acceleration_mg[0] = (int16_t)((int32_t)(next_random(model) % 1801u) - 900);
        model->acceleration_mg[1] = (int16_t)((int32_t)(next_random(model) % 1201u) - 600);
        model->acceleration_mg[2] = (int16_t)(1000 + (int32_t)(next_random(model) % 1001u) - 500);
        break;
    }
    ++model->sample_number;
    for (unsigned axis = 0; axis < 3u; ++axis) store_axis(model, axis);
    model->registers[LIS2DW12_REG_STATUS] |= 0x01u; /* data-ready */
    update_irq(model);
}

bool lis2dw12_irq_pending(const lis2dw12_model_t *model)
{
    return model != NULL && model->irq_latched;
}

void lis2dw12_clear_irq(lis2dw12_model_t *model)
{
    if (model == NULL) return;
    model->irq_latched = false;
    model->registers[LIS2DW12_REG_WAKE_UP_SRC] = 0u;
    model->registers[LIS2DW12_REG_ALL_INT_SRC] &= (uint8_t)~0x08u;
}

void lis2dw12_fail_next_i2c(lis2dw12_model_t *model, uint32_t transactions)
{
    if (model != NULL) model->fail_transactions = transactions;
}

void lis2dw12_timeout_next_i2c(lis2dw12_model_t *model, uint32_t transactions)
{
    if (model != NULL) model->timeout_transactions = transactions;
}
