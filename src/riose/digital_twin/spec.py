"""Compatibility facade for the canonical ear-tag spec module."""

from riose.products.ear_tag.digital_twin.spec import (
    ALLOWED_STATUSES, ALLOWED_UNITS, FORBIDDEN_STATUSES, REVIEW_KEYS,
    SpecError, dump_json, evaluate_gate, load_spec, parameter_statuses,
    validate_spec,
)
