"""Build and verify small, auditable packages of simulation evidence."""

from .pipeline import (
    DEFAULT_MAX_ARTIFACT_BYTES,
    DEFAULT_MAX_PACKAGE_BYTES,
    EvidenceError,
    build_package,
    verify_package,
)

__all__ = [
    "DEFAULT_MAX_ARTIFACT_BYTES",
    "DEFAULT_MAX_PACKAGE_BYTES",
    "EvidenceError",
    "build_package",
    "verify_package",
]
