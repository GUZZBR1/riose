"""Headless RF/antenna digital-twin interfaces for RIOSE MVP 2.

All outputs from this package are either solver-derived or explicitly marked
unavailable. It never substitutes analytical estimates for openEMS results.
"""

__all__ = ["SCENARIOS"]

SCENARIOS = (
    "ANTENNA_FREE_SPACE",
    "ANTENNA_WITH_PCB",
    "ANTENNA_WITH_BATTERY",
    "ANTENNA_WITH_ENCLOSURE",
    "ANTENNA_NEAR_ANIMAL_APPROXIMATION",
)
