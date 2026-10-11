"""Explicit feature meaning contract shared by training and grouped evaluation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

SYNTHETIC_FEATURE_ORDER = (
    "accel_mean_native", "accel_std_native", "accel_rms_native",
)
SYNTHETIC_FEATURE_SCHEMA = {
    "schema_id": "riose.synthetic.behavior-window",
    "version": "movement-window-v1",
    "extractor": "riose.synthetic.behavior-fixture-v1",
    "units": {name: "source_native" for name in SYNTHETIC_FEATURE_ORDER},
    "definitions": {
        "accel_mean_native": "synthetic window mean acceleration on an uncalibrated source scale",
        "accel_std_native": "synthetic window acceleration standard deviation on an uncalibrated source scale",
        "accel_rms_native": "synthetic window root mean square acceleration on an uncalibrated source scale",
    },
}

SIGNAL_FEATURE_ORDER = (
    "mean_x_g", "mean_y_g", "mean_z_g", "std_x_g", "std_y_g", "std_z_g",
    "rms_x_g", "rms_y_g", "rms_z_g", "mean_magnitude_g", "rms_magnitude_g",
    "sma_g", "jerk_rms_g_per_s", "energy_g2_s", "dominant_frequency_hz",
)
SIGNAL_FEATURE_SCHEMA = {
    "schema_id": "riose.ear-tag.signal-features",
    "version": "riose.signal/1.0.0",
    "extractor": "riose.products.ear_tag.signal.engine.extract_features",
    "units": {
        **{name: "g" for name in SIGNAL_FEATURE_ORDER if name.endswith("_g")},
        "jerk_rms_g_per_s": "g/s",
        "energy_g2_s": "g^2*s",
        "dominant_frequency_hz": "Hz",
    },
    "definitions": {
        "mean_x_g": "mean acceleration on the X axis in canonical g",
        "mean_y_g": "mean acceleration on the Y axis in canonical g",
        "mean_z_g": "mean acceleration on the Z axis in canonical g",
        "std_x_g": "population standard deviation of X acceleration in canonical g",
        "std_y_g": "population standard deviation of Y acceleration in canonical g",
        "std_z_g": "population standard deviation of Z acceleration in canonical g",
        "rms_x_g": "root mean square X acceleration in canonical g",
        "rms_y_g": "root mean square Y acceleration in canonical g",
        "rms_z_g": "root mean square Z acceleration in canonical g",
        "mean_magnitude_g": "mean Euclidean acceleration magnitude in canonical g",
        "rms_magnitude_g": "root mean square Euclidean acceleration magnitude in canonical g",
        "sma_g": "mean signal magnitude area across XYZ in canonical g",
        "jerk_rms_g_per_s": "root mean square XYZ derivative magnitude in g per second",
        "energy_g2_s": "sum of squared XYZ acceleration divided by sample rate in g squared seconds",
        "dominant_frequency_hz": "frequency bin with greatest non-DC XYZ spectral power in hertz",
    },
}

_REGISTERED_SCHEMAS = {
    SYNTHETIC_FEATURE_SCHEMA["schema_id"]: deepcopy(SYNTHETIC_FEATURE_SCHEMA),
    SIGNAL_FEATURE_SCHEMA["schema_id"]: deepcopy(SIGNAL_FEATURE_SCHEMA),
}


def validate_feature_schema(schema: object, feature_order: Sequence[str]) -> dict[str, Any]:
    """Validate ordered names, units, extraction identity, and definitions."""
    required = {"schema_id", "version", "extractor", "units", "definitions"}
    if not isinstance(schema, Mapping) or set(schema) != required:
        raise ValueError("feature_schema must define schema_id, version, extractor, units, and definitions")
    for name in ("schema_id", "version", "extractor"):
        value = schema[name]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"feature_schema {name} must be a non-empty string")
    result: dict[str, Any] = {name: schema[name].strip() for name in ("schema_id", "version", "extractor")}
    for name in ("units", "definitions"):
        values = schema[name]
        if (not isinstance(values, Mapping) or set(values) != set(feature_order) or
                any(not isinstance(value, str) or not value.strip() for value in values.values())):
            raise ValueError(f"feature_schema {name} must define every feature in the declared order")
        result[name] = {key: values[key].strip() for key in feature_order}
    if not feature_order or any(not isinstance(name, str) or not name.strip() for name in feature_order):
        raise ValueError("feature schema requires a non-empty ordered feature list")
    return result


def validate_registered_feature_schema(schema: object, feature_order: Sequence[str]) -> dict[str, Any]:
    """Allow only fixture or upstream signal-engine feature definitions."""
    normalized = validate_feature_schema(schema, feature_order)
    registered = _REGISTERED_SCHEMAS.get(normalized["schema_id"])
    if (registered is None or normalized != registered or
            tuple(feature_order) not in {SYNTHETIC_FEATURE_ORDER, SIGNAL_FEATURE_ORDER}):
        raise ValueError("unregistered feature schema; use the synthetic fixture or RIOSE signal-engine schema")
    return normalized
