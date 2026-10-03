"""Offline, deterministic acceleration signal processing for ear tags.

The public API is intentionally small: create :class:`SignalTrace` from XYZ
samples, then call :func:`extract_features`. Results describe signal features;
they do not classify behavior or validate the source evidence.
"""

from .engine import (
    FEATURE_NAMES,
    PIPELINE_VERSION,
    SignalSample,
    SignalTrace,
    WindowConfig,
    FeatureWindow,
    extract_features,
)

__all__ = [
    "FEATURE_NAMES",
    "PIPELINE_VERSION",
    "SignalSample",
    "SignalTrace",
    "WindowConfig",
    "FeatureWindow",
    "extract_features",
]
