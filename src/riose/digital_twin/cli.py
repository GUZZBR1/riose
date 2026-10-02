"""Compatibility facade for :mod:`riose.products.ear_tag.digital_twin`."""

from riose.products.ear_tag.digital_twin.cli import (
    DEFAULT_OUTPUT, DEFAULT_SPEC, ROOT, SCENARIOS,
    _clear_previous_outputs, _metrics_csv, _module_available,
    _power_assumptions, _power_load_profile, _record, _report,
    _run_command, _version_matches, _write_empty_csv, _long_run_energy_uah, _stack_usage,
    generate_motion_profiles, main, preflight, run_twin,
)
from riose.products.ear_tag.digital_twin.spec import (
    dump_json, evaluate_gate, load_spec, parameter_statuses,
)

if __name__ == "__main__":
    raise SystemExit(main())
