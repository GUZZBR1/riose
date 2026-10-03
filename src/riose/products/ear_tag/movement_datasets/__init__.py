"""Offline-first adapters for externally sourced bovine movement datasets.

These adapters preserve source values and provenance. They do not validate
RIOSE hardware or infer behavior classes from sensor signals.
"""

from .actbecalf import ADAPTER_VERSION, adapt_actbecalf_csv
from .contract import CanonicalSample, SensorPosition

__all__ = ["ADAPTER_VERSION", "CanonicalSample", "SensorPosition", "adapt_actbecalf_csv"]
