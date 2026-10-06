"""Fail-closed public commitment envelope for future publication adapters.

This module deliberately has no persistence, signer, or network dependencies.
Only a version, an allowlisted digest algorithm, and a fixed-size commitment
digest may cross the public boundary.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Final


MAX_PUBLIC_ENVELOPE_BYTES: Final = 512
PUBLIC_ENVELOPE_VERSION: Final = 1
PUBLIC_DIGEST_ALGORITHMS: Final = frozenset({"sha256"})
_DIGEST_PATTERN: Final = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_ALLOWED_KEYS: Final = frozenset({"version", "algorithm", "commitment"})


class PrivacyGuardError(ValueError):
    """A public envelope failed validation without exposing rejected data."""


@dataclass(frozen=True, slots=True)
class PublicCommitmentEnvelope:
    """The complete, intentionally small DTO permitted at the public edge."""

    version: int
    algorithm: str
    commitment: str


def guard_public_envelope(value: object) -> PublicCommitmentEnvelope:
    """Validate an already-decoded JSON object against the positive allowlist."""

    if type(value) is not dict:
        raise PrivacyGuardError("envelope must be a JSON object")
    if frozenset(value) != _ALLOWED_KEYS:
        # Do not echo caller-controlled keys; they could themselves contain PII.
        raise PrivacyGuardError("envelope contains missing or unsupported fields")

    version = value["version"]
    if type(version) is not int or version != PUBLIC_ENVELOPE_VERSION:
        raise PrivacyGuardError("$.version is unsupported")

    algorithm = value["algorithm"]
    if type(algorithm) is not str or algorithm not in PUBLIC_DIGEST_ALGORITHMS:
        raise PrivacyGuardError("$.algorithm is unsupported")

    commitment = value["commitment"]
    if type(commitment) is not str or _DIGEST_PATTERN.fullmatch(commitment) is None:
        raise PrivacyGuardError("$.commitment must be a lowercase SHA-256 digest")

    return PublicCommitmentEnvelope(version, algorithm, commitment)


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PrivacyGuardError("envelope contains duplicate keys")
        result[key] = value
    return result


def _reject_non_json_constant(_constant: str) -> object:
    raise PrivacyGuardError("envelope contains a non-JSON number")


def parse_public_envelope_json(document: str | bytes) -> PublicCommitmentEnvelope:
    """Parse and guard bounded JSON, rejecting duplicate keys at every depth."""

    if isinstance(document, bytes):
        if len(document) > MAX_PUBLIC_ENVELOPE_BYTES:
            raise PrivacyGuardError("envelope exceeds the size limit")
        try:
            document = document.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise PrivacyGuardError("envelope must use UTF-8 encoding") from exc
    elif isinstance(document, str):
        try:
            encoded = document.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise PrivacyGuardError("envelope must use valid UTF-8 text") from exc
        if len(encoded) > MAX_PUBLIC_ENVELOPE_BYTES:
            raise PrivacyGuardError("envelope exceeds the size limit")
    else:
        raise PrivacyGuardError("envelope must be UTF-8 JSON")

    try:
        value = json.loads(
            document,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_non_json_constant,
        )
    except PrivacyGuardError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise PrivacyGuardError("envelope is not valid JSON") from exc
    return guard_public_envelope(value)


def serialize_public_envelope(value: object) -> bytes:
    """Return deterministic UTF-8 JSON bytes only after strict validation."""

    if isinstance(value, PublicCommitmentEnvelope):
        value = {
            "version": value.version,
            "algorithm": value.algorithm,
            "commitment": value.commitment,
        }
    envelope = guard_public_envelope(value)
    document = json.dumps(
        {
            "algorithm": envelope.algorithm,
            "commitment": envelope.commitment,
            "version": envelope.version,
        },
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(document) > MAX_PUBLIC_ENVELOPE_BYTES:
        # Defensive invariant if the schema changes in a later version.
        raise PrivacyGuardError("envelope exceeds the size limit")
    return document


def build_public_envelope(commitment: str) -> PublicCommitmentEnvelope:
    """Build the current SHA-256 envelope from a digest, never from an event."""

    return guard_public_envelope(
        {
            "version": PUBLIC_ENVELOPE_VERSION,
            "algorithm": "sha256",
            "commitment": commitment,
        }
    )
