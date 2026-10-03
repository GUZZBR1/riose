"""Adapter for the official ActBeCalf CSV export.

The publisher does not state the unit used in CSV columns accX/accY/accZ or
the timestamp timezone. Both uncertainties are retained instead of guessed.
"""

from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import math
from pathlib import Path
import re
import tempfile
from typing import Iterator, TextIO

from riose.evidence.bridge import EvidenceClass, MeasurementProvenance, map_source_evidence

from .contract import AxisUnit, CanonicalSample, SensorPosition
from .acquisition import ACTBECALF_PUBLISHER_MD5, ACTBECALF_PUBLISHER_SIZE

ADAPTER_VERSION = "1.0.0"
DATASET_ID = "actbecalf"
DATASET_DOI = "10.5281/zenodo.13259482"
SOURCE_URL = "https://zenodo.org/records/13259482"
EXPECTED_COLUMNS = ("dateTime", "calfId", "accX", "accY", "accZ", "behaviour", "segId")
_SEGMENT_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")


def _timestamp(value: str) -> tuple[str, str]:
    source_value = value
    value = value.strip()
    if not value:
        raise ValueError("dateTime is missing")
    try:
        if "T" not in value and " " not in value:
            raise ValueError("time component is required")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid ActBeCalf dateTime: {value!r}") from exc
    if parsed.tzinfo is None:
        return source_value, "UNKNOWN"
    if parsed.utcoffset().total_seconds() == 0:
        return source_value, "UTC"
    return source_value, "OFFSET"


def _number(value: str, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _rows(stream: TextIO, source_file: str, digest: str,
          evidence_class: EvidenceClass) -> Iterator[CanonicalSample]:
    reader = csv.DictReader(stream, strict=True)
    if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
        raise ValueError("unexpected ActBeCalf CSV header; refusing to guess axes or columns")
    try:
        for row in reader:
            row_number = reader.line_num
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"malformed ActBeCalf CSV row {row_number}")
            animal_id = row["calfId"]
            label = row["behaviour"]
            segment_id = row["segId"]
            if not animal_id.strip() or len(animal_id) > 128:
                raise ValueError(f"missing or invalid calfId at CSV row {row_number}")
            if not label.strip() or len(label) > 256:
                raise ValueError(f"missing or invalid behaviour at CSV row {row_number}")
            if not _SEGMENT_ID.fullmatch(segment_id.strip()):
                raise ValueError(f"missing or invalid segId at CSV row {row_number}")
            source_segment_id = segment_id
            timestamp, timezone = _timestamp(row["dateTime"])
            if evidence_class is EvidenceClass.SIMULATED:
                evidence = map_source_evidence(
                    "SIMULATED", source_ref=SOURCE_URL,
                    source_context={"dataset_id": DATASET_ID, "source_file_sha256": digest,
                                    "sensor_position": "NECK"},
                )
            elif evidence_class is EvidenceClass.MEASURED:
                evidence = map_source_evidence(
                    "MEASURED", source_ref=f"DOI:{DATASET_DOI}",
                    measurement_provenance=MeasurementProvenance(
                        physical_source_ref="ActBeCalf AX3 accelerometer dataset",
                        capture_ref=f"{source_file}#row={row_number}",
                        provenance_ref=f"DOI:{DATASET_DOI}",
                    ),
                    source_context={"dataset_id": DATASET_ID, "source_file_sha256": digest,
                                    "sensor_position": "NECK"},
                )
            else:
                evidence = map_source_evidence(
                    "UNKNOWN", source_ref=SOURCE_URL,
                    source_context={"dataset_id": DATASET_ID, "source_file_sha256": digest,
                                    "sensor_position": "NECK"},
                )
            yield CanonicalSample(
                dataset_id=DATASET_ID,
                dataset_doi=DATASET_DOI,
                source_url=SOURCE_URL,
                source_file=source_file,
                source_file_sha256=digest,
                source_row=row_number,
                animal_id=animal_id,
                source_segment_id=source_segment_id,
                # segId is a behavioral annotation segment, not a capture session.
                session_id=None,
                timestamp=timestamp,
                timestamp_timezone=timezone,
                sensor_position=SensorPosition.NECK,
                sample_rate_hz=25.0,
                x=_number(row["accX"], "accX"),
                y=_number(row["accY"], "accY"),
                z=_number(row["accZ"], "accZ"),
                axis_unit=AxisUnit.UNKNOWN,
                original_label=label,
                canonical_label="UNKNOWN",
                mapping_version="none",
                mapping_reason="No source-backed equivalence to RIOSE behavior classes has been established.",
                evidence=evidence,
                adapter_version=ADAPTER_VERSION,
            )
    except csv.Error as exc:
        raise ValueError("malformed ActBeCalf CSV quoting or encoding") from exc


def adapt_actbecalf_csv(path: str | Path, *, evidence_class: EvidenceClass) -> Iterator[CanonicalSample]:
    """Read a CSV without modifying it, with provenance status chosen explicitly.

    Test/synthetic fixtures must pass ``SIMULATED``. ``MEASURED`` produces a
    record through the shared evidence bridge and only describes the external
    dataset capture; it never represents RIOSE hardware validation.
    """

    if evidence_class not in {EvidenceClass.SIMULATED, EvidenceClass.MEASURED, EvidenceClass.UNKNOWN}:
        raise ValueError("ActBeCalf evidence_class must be SIMULATED, MEASURED, or UNKNOWN")
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    # Hash and parse a private snapshot so path replacement cannot associate an
    # earlier checksum with different sample bytes.
    with tempfile.TemporaryDirectory(prefix="riose-actbecalf-") as temporary_directory:
        snapshot = Path(temporary_directory) / source.name
        digest = hashlib.sha256()
        publisher_digest = hashlib.md5(usedforsecurity=False)
        source_size = 0
        with source.open("rb") as binary, snapshot.open("xb") as copy:
            for chunk in iter(lambda: binary.read(1024 * 1024), b""):
                copy.write(chunk)
                digest.update(chunk)
                publisher_digest.update(chunk)
                source_size += len(chunk)
        source_digest = digest.hexdigest()
        if evidence_class is EvidenceClass.MEASURED and (
            publisher_digest.hexdigest() != ACTBECALF_PUBLISHER_MD5
            or source_size != ACTBECALF_PUBLISHER_SIZE
        ):
            raise ValueError("MEASURED evidence requires a full file matching the official publisher checksum and size")
        with snapshot.open("r", encoding="utf-8-sig", newline="") as text:
            yield from _rows(text, source.name, source_digest, evidence_class)
