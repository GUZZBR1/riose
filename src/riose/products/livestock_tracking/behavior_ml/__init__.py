"""Offline behavior classification research MVP (not field validated)."""

from .feature_schema import SIGNAL_FEATURE_SCHEMA
from .pipeline import (
    FEATURE_NAMES,
    MODEL_VERSION,
    BehaviorWindow,
    create_synthetic_fixture,
    infer,
    load_artifact,
    run_training,
    save_artifact,
    split_by_animal,
)

__all__ = [
    "FEATURE_NAMES", "MODEL_VERSION", "SIGNAL_FEATURE_SCHEMA", "BehaviorWindow", "create_synthetic_fixture",
    "infer", "load_artifact", "run_training", "save_artifact", "split_by_animal",
]
