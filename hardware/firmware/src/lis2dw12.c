#include "tag_lis2dw12.h"

static int32_t decode_little_endian_twos_complement(const uint8_t *bytes)
{
    const uint16_t word = (uint16_t)bytes[0] | ((uint16_t)bytes[1] << 8u);
    return (word & 0x8000u) != 0u ? (int32_t)word - 0x10000 : (int32_t)word;
}

static int16_t hp14_raw_to_mg(int32_t raw16)
{
    /* HP14 results are left-aligned in the 16-bit output word. Division by
     * four removes the two alignment bits without a negative signed shift. */
    const int32_t raw14 = raw16 / 4;
    return (int16_t)((raw14 * 244) / 1000);
}

bool tag_lis2dw12_decode_hp14_axes_mg(const uint8_t *bytes, size_t length,
                                      int16_t xyz_mg[3])
{
    if (bytes == NULL || xyz_mg == NULL || length != 6u) return false;

    int16_t decoded[3];
    for (size_t axis = 0; axis < 3u; ++axis) {
        const uint8_t *word = &bytes[axis * 2u];
        /* CTRL1=0x14 selects 14-bit output left-aligned in the word. */
        if ((word[0] & 0x03u) != 0u) return false;
        decoded[axis] = hp14_raw_to_mg(
            decode_little_endian_twos_complement(word));
    }

    xyz_mg[0] = decoded[0];
    xyz_mg[1] = decoded[1];
    xyz_mg[2] = decoded[2];
    return true;
}
