#include "tag_lis2dw12.h"

int16_t tag_lis2dw12_hp14_raw_to_mg(int16_t raw16)
{
    /* A signed divide by four removes the two alignment bits without relying
     * on implementation-defined right shift behavior for negative values. */
    const int32_t raw14 = (int32_t)raw16 / 4;
    return (int16_t)((raw14 * 244) / 1000);
}
