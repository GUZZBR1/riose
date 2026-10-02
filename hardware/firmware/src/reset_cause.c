#include "tag_reset_cause.h"

tag_reset_kind_t tag_reset_cause_classify(uint32_t flags)
{
    if (flags == 0u) return TAG_RESET_KIND_UNKNOWN;
    if ((flags & TAG_RESET_CAUSE_WATCHDOG) != 0u) return TAG_RESET_KIND_WATCHDOG;
    if ((flags & TAG_RESET_CAUSE_BROWNOUT) != 0u) return TAG_RESET_KIND_BROWNOUT;
    if ((flags & TAG_RESET_CAUSE_PIN) != 0u) return TAG_RESET_KIND_PIN;
    if ((flags & TAG_RESET_CAUSE_SOFTWARE) != 0u) return TAG_RESET_KIND_SOFTWARE;
    if (flags == TAG_RESET_CAUSE_POWER_ON) return TAG_RESET_KIND_POWER_ON;
    return TAG_RESET_KIND_OTHER;
}

const char *tag_reset_kind_name(tag_reset_kind_t kind)
{
    switch (kind) {
    case TAG_RESET_KIND_POWER_ON: return "power_on";
    case TAG_RESET_KIND_WATCHDOG: return "watchdog";
    case TAG_RESET_KIND_BROWNOUT: return "brownout";
    case TAG_RESET_KIND_PIN: return "pin";
    case TAG_RESET_KIND_SOFTWARE: return "software";
    case TAG_RESET_KIND_OTHER: return "other";
    case TAG_RESET_KIND_UNKNOWN:
    default: return "unknown";
    }
}
