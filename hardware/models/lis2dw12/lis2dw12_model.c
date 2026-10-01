#include "lis2dw12_model.h"

#include <math.h>
#include <string.h>

#define PI_F 3.14159265358979323846f

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
    const float counts_per_mg = 32768.0f / ((float)full_scale_g(model) * 1000.0f);
    float raw = (float)model->acceleration_mg[axis] * counts_per_mg;
    if (raw > 32767.0f) raw = 32767.0f;
    if (raw < -32768.0f) raw = -32768.0f;
    return (int16_t)lrintf(raw);
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
    const bool wake_routed = (model->registers[LIS2DW12_REG_CTRL4_INT1_PAD_CTRL] & 0x08u) != 0u;
    if (wake_routed && threshold_mg > 0 && peak_delta >= threshold_mg && !model->irq_latched) {
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
    if (model == NULL || motion > LIS2DW12_MOTION_ABNORMAL) return;
    model->motion = motion;
}

void lis2dw12_tick(lis2dw12_model_t *model, uint32_t elapsed_ms)
{
    if (model == NULL || !model->initialized) return;
    model->elapsed_ms += elapsed_ms;
    if (!odr_enabled(model)) return;

    const float t = (float)model->elapsed_ms / 1000.0f;
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
        model->acceleration_mg[0] = (int16_t)lrintf(70.0f * sinf(2.0f * PI_F * 0.35f * t));
        model->acceleration_mg[1] = (int16_t)lrintf(40.0f * sinf(2.0f * PI_F * 0.21f * t));
        model->acceleration_mg[2] = (int16_t)(1000 + 30.0f * sinf(2.0f * PI_F * 0.35f * t));
        break;
    case LIS2DW12_MOTION_WALKING:
        model->acceleration_mg[0] = (int16_t)lrintf(260.0f * sinf(2.0f * PI_F * 1.8f * t));
        model->acceleration_mg[1] = (int16_t)lrintf(110.0f * sinf(2.0f * PI_F * 1.8f * t + 1.0f));
        model->acceleration_mg[2] = (int16_t)lrintf(1000.0f + 180.0f * sinf(2.0f * PI_F * 1.8f * t));
        break;
    case LIS2DW12_MOTION_RUNNING:
        model->acceleration_mg[0] = (int16_t)lrintf(900.0f * sinf(2.0f * PI_F * 3.2f * t));
        model->acceleration_mg[1] = (int16_t)lrintf(500.0f * sinf(2.0f * PI_F * 3.2f * t + 0.8f));
        model->acceleration_mg[2] = (int16_t)lrintf(1000.0f + 650.0f * sinf(2.0f * PI_F * 3.2f * t));
        break;
    case LIS2DW12_MOTION_ABNORMAL:
        model->acceleration_mg[0] = ((model->sample_number % 4u) == 0u) ? 1800 : -1500;
        model->acceleration_mg[1] = ((model->sample_number % 4u) == 0u) ? -1100 : 900;
        model->acceleration_mg[2] = ((model->sample_number % 4u) == 0u) ? 2100 : -1700;
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
