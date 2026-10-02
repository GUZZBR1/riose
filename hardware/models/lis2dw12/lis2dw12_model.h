#ifndef LIS2DW12_MODEL_H
#define LIS2DW12_MODEL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define LIS2DW12_WHO_AM_I_VALUE 0x44u
#define LIS2DW12_REG_WHO_AM_I 0x0Fu
#define LIS2DW12_REG_CTRL1 0x20u
#define LIS2DW12_REG_CTRL2 0x21u
#define LIS2DW12_REG_CTRL3 0x22u
#define LIS2DW12_REG_CTRL4_INT1_PAD_CTRL 0x23u
#define LIS2DW12_REG_CTRL5_INT2_PAD_CTRL 0x24u
#define LIS2DW12_REG_CTRL6 0x25u
#define LIS2DW12_REG_CTRL7 0x3Fu
#define LIS2DW12_REG_STATUS 0x27u
#define LIS2DW12_REG_OUT_X_L 0x28u
#define LIS2DW12_REG_OUT_X_H 0x29u
#define LIS2DW12_REG_OUT_Y_L 0x2Au
#define LIS2DW12_REG_OUT_Y_H 0x2Bu
#define LIS2DW12_REG_OUT_Z_L 0x2Cu
#define LIS2DW12_REG_OUT_Z_H 0x2Du
#define LIS2DW12_REG_WAKE_UP_THS 0x34u
#define LIS2DW12_REG_WAKE_UP_DUR 0x35u
#define LIS2DW12_REG_WAKE_UP_SRC 0x38u
#define LIS2DW12_REG_ALL_INT_SRC 0x3Bu

#define LIS2DW12_REGISTER_COUNT 64u

typedef enum {
    LIS2DW12_OK = 0,
    LIS2DW12_EINVAL = -1,
    LIS2DW12_EIO = -2,
} lis2dw12_result_t;

typedef enum {
    LIS2DW12_MOTION_STATIONARY = 0,
    LIS2DW12_MOTION_GRAZING,
    LIS2DW12_MOTION_WALKING,
    LIS2DW12_MOTION_RUNNING,
    LIS2DW12_MOTION_ABNORMAL,
} lis2dw12_motion_t;

typedef void (*lis2dw12_irq_callback_t)(void *user_data);

typedef struct {
    uint8_t registers[LIS2DW12_REGISTER_COUNT];
    int16_t acceleration_mg[3];
    int16_t previous_acceleration_mg[3];
    uint64_t elapsed_ms;
    uint32_t sample_number;
    uint32_t fail_transactions;
    lis2dw12_motion_t motion;
    bool irq_latched;
    bool initialized;
    lis2dw12_irq_callback_t irq_callback;
    void *irq_user_data;
} lis2dw12_model_t;

/* Initialize with device reset defaults. The callback fires on a rising IRQ. */
void lis2dw12_init(lis2dw12_model_t *model,
                   lis2dw12_irq_callback_t irq_callback,
                   void *irq_user_data);

/* I2C register operations. A multi-byte operation auto-increments addresses. */
lis2dw12_result_t lis2dw12_i2c_read(lis2dw12_model_t *model,
                                     uint8_t first_register,
                                     uint8_t *destination,
                                     size_t length);
lis2dw12_result_t lis2dw12_i2c_write(lis2dw12_model_t *model,
                                      uint8_t first_register,
                                      const uint8_t *source,
                                      size_t length);

/* Advance virtual time and update outputs according to the selected profile. */
void lis2dw12_tick(lis2dw12_model_t *model, uint32_t elapsed_ms);
void lis2dw12_set_motion(lis2dw12_model_t *model, lis2dw12_motion_t motion);

/* IRQ can be consumed as a flag by a HAL adapter; source-register reads clear it. */
bool lis2dw12_irq_pending(const lis2dw12_model_t *model);
void lis2dw12_clear_irq(lis2dw12_model_t *model);

/* Inject failures on the next N bus transactions, then return to normal. */
void lis2dw12_fail_next_i2c(lis2dw12_model_t *model, uint32_t transactions);

/* Raw signed 16-bit register output, left-aligned like the sensor data format. */
int16_t lis2dw12_axis_raw(const lis2dw12_model_t *model, unsigned axis);

#ifdef __cplusplus
}
#endif
#endif
