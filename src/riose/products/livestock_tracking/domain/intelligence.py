"""Stable boundaries for optional intelligence producers and Core persistence.

These records describe model outputs. They do not assert animal health,
biological validity, or field validation, and they keep model and feature
provenance attached to each prediction.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Protocol, Sequence

from .contracts import EvidenceStatus


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,191}\Z", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class BehaviorPrediction:
    """A model output over one movement window, with reproducible provenance.

    ``confidence`` is a model score in [0, 1], not a calibrated probability.
    The interval uses UTC Unix seconds. Ground truth and manual labels use a
    separate data path and must never be passed as estimator input.
    """

    animal_id: str
    tag_id: str
    window_start_s: float
    window_end_s: float
    created_at_s: float
    behavior: str
    confidence: float | None
    model_version: str
    model_sha256: str
    feature_version: str
    evidence_status: EvidenceStatus
    source_ref: str
    input_sha256: str
    prediction_id: str

    def __post_init__(self) -> None:
        for name in ("animal_id", "tag_id", "behavior", "model_version",
                     "feature_version", "source_ref", "prediction_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
                raise ValueError(f"{name} must be a non-empty bounded identifier")
        if not _finite(self.window_start_s) or self.window_start_s < 0:
            raise ValueError("window_start_s must be finite Unix seconds >= 0")
        if not _finite(self.window_end_s) or self.window_end_s <= self.window_start_s:
            raise ValueError("window_end_s must be finite and after window_start_s")
        if not _finite(self.created_at_s) or self.created_at_s < 0:
            raise ValueError("created_at_s must be finite UTC Unix seconds >= 0")
        if self.confidence is not None and (
            not _finite(self.confidence) or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidence must be a finite score in [0, 1] or null")
        if not isinstance(self.evidence_status, EvidenceStatus):
            raise ValueError("evidence_status must be an EvidenceStatus")
        for name in ("model_sha256", "input_sha256"):
            if not isinstance(getattr(self, name), str) or not _SHA256.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")


class BehaviorPredictionStore(Protocol):
    """Persistence seam owned by Core; Intelligence does not own a database.

    Save is idempotent by prediction_id: return True for a new record and
    False for an identical retry. Reusing an ID with different content is an
    integrity conflict and must raise rather than overwrite the first record.
    """

    def save_behavior_prediction(self, prediction: BehaviorPrediction) -> bool: ...

    def list_behavior_predictions(
        self, animal_id: str, *, limit: int = 100
    ) -> Sequence[BehaviorPrediction]: ...


def _finite(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )
