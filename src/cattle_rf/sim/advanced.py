"""Optional advanced simulator availability checks; core has no such dependency."""

from __future__ import annotations

from importlib.util import find_spec


def advanced_capabilities() -> dict[str, bool]:
    """Report whether optional Python integrations appear importable."""
    return {
        "sionna": find_spec("sionna") is not None,
        "sionna_rt": find_spec("sionna.rt") is not None if find_spec("sionna") else False,
        "ns3": find_spec("ns") is not None,
        "wokwi": False,  # Wokwi is an external service/tool, not a Python package.
        "zephyr_native_sim": False,  # checked by CLI/system probe outside core import path
    }
