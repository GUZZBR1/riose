#ifndef TAG_RESET_CAUSE_H
#define TAG_RESET_CAUSE_H

#include <stdint.h>

/* Bit assignments follow Zephyr's standardized hwinfo reset-cause flags so
 * board adapters can preserve the device driver's cause mask verbatim. */
enum {
    TAG_RESET_CAUSE_PIN = 1u << 0,
    TAG_RESET_CAUSE_SOFTWARE = 1u << 1,
    TAG_RESET_CAUSE_BROWNOUT = 1u << 2,
    TAG_RESET_CAUSE_POWER_ON = 1u << 3,
    TAG_RESET_CAUSE_WATCHDOG = 1u << 4,
    TAG_RESET_CAUSE_DEBUG = 1u << 5,
    TAG_RESET_CAUSE_SECURITY = 1u << 6,
    TAG_RESET_CAUSE_LOW_POWER_WAKE = 1u << 7,
    TAG_RESET_CAUSE_CPU_LOCKUP = 1u << 8,
};

typedef enum {
    TAG_RESET_KIND_UNKNOWN = 0,
    TAG_RESET_KIND_POWER_ON,
    TAG_RESET_KIND_WATCHDOG,
    TAG_RESET_KIND_BROWNOUT,
    TAG_RESET_KIND_PIN,
    TAG_RESET_KIND_SOFTWARE,
    TAG_RESET_KIND_OTHER,
} tag_reset_kind_t;

/* Gives watchdog and supply faults precedence when hardware reports more than
 * one sticky reset flag. This is classification of flags, not a claim about
 * why the user intended a restart. */
tag_reset_kind_t tag_reset_cause_classify(uint32_t cause_flags);
const char *tag_reset_kind_name(tag_reset_kind_t kind);

#endif
