#ifndef RIOSE_TAG_LIS2DW12_H
#define RIOSE_TAG_LIS2DW12_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Decode six little-endian OUT_X/Y/Z bytes configured by the firmware for
 * CTRL1=0x14 (14-bit high-performance mode) and CTRL6=0x00 (±2 g).
 * The returned signed integer values are mg, truncated toward zero. */
bool tag_lis2dw12_decode_hp14_axes_mg(const uint8_t *bytes, size_t length,
                                      int16_t xyz_mg[3]);

#endif
