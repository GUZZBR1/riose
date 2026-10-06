#ifndef RIOSE_TAG_LIS2DW12_H
#define RIOSE_TAG_LIS2DW12_H

#include <stdint.h>

/* Decode signed, left-aligned LIS2DW12 output for CTRL1=0x14 at +/-2 g.
 * That setting uses 14-bit high-performance data (0.244 mg/LSB). */
int16_t tag_lis2dw12_hp14_raw_to_mg(int16_t raw16);

#endif
