#include "tag_lis2dw12.h"

#include <assert.h>
#include <stdint.h>

static void expect_axes(const uint8_t bytes[6], int16_t x, int16_t y, int16_t z)
{
    int16_t axes[3] = {123, 456, 789};
    assert(tag_lis2dw12_decode_hp14_axes_mg(bytes, 6u, axes));
    assert(axes[0] == x);
    assert(axes[1] == y);
    assert(axes[2] == z);
}

int main(void)
{
    /* Byte order and axis order: X=+1 g, Y=-1 g, Z=+0.5 g. */
    static const uint8_t axis_probe[6] = {
        0x00u, 0x40u, 0x00u, 0xc0u, 0x00u, 0x20u,
    };
    expect_axes(axis_probe, 999, -999, 499);
    expect_axes(axis_probe, 999, -999, 499); /* repeated decode is deterministic */

    /* Zero and signed small samples straddling zero. Integer mg truncates. */
    static const uint8_t small[6] = {
        0x00u, 0x00u, 0x40u, 0x00u, 0xc0u, 0xffu,
    };
    expect_axes(small, 0, 3, -3);

    /* 14-bit signed limits at the explicitly configured ±2 g range. */
    static const uint8_t limits[6] = {
        0xfcu, 0x7fu, 0x00u, 0x80u, 0x00u, 0x00u,
    };
    expect_axes(limits, 1998, -1998, 0);

    int16_t unchanged[3] = {11, 22, 33};
    assert(!tag_lis2dw12_decode_hp14_axes_mg(axis_probe, 5u, unchanged));
    assert(unchanged[0] == 11 && unchanged[1] == 22 && unchanged[2] == 33);
    assert(!tag_lis2dw12_decode_hp14_axes_mg(axis_probe, 7u, unchanged));
    assert(!tag_lis2dw12_decode_hp14_axes_mg(NULL, 6u, unchanged));
    assert(!tag_lis2dw12_decode_hp14_axes_mg(axis_probe, 6u, NULL));

    static const uint8_t invalid_alignment[6] = {
        0x01u, 0x00u, 0x00u, 0x00u, 0x00u, 0x00u,
    };
    assert(!tag_lis2dw12_decode_hp14_axes_mg(invalid_alignment, 6u, unchanged));
    assert(unchanged[0] == 11 && unchanged[1] == 22 && unchanged[2] == 33);
    return 0;
}
