#include "tag_lis2dw12.h"

#include <assert.h>
#include <stdint.h>

int main(void)
{
    /* +/-2 g high-performance samples are left-aligned 14-bit values.
     * 0x4000 is approximately +1 g; test both signs and fractional range. */
    assert(tag_lis2dw12_hp14_raw_to_mg(0x4000) == 999);
    assert(tag_lis2dw12_hp14_raw_to_mg((int16_t)-0x4000) == -999);
    assert(tag_lis2dw12_hp14_raw_to_mg(0x2000) == 499);
    assert(tag_lis2dw12_hp14_raw_to_mg((int16_t)-0x2000) == -499);
    assert(tag_lis2dw12_hp14_raw_to_mg(0) == 0);
    return 0;
}
