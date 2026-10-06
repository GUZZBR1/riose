#!/usr/bin/env python3
"""Convert one SIMULATED RIOSE acceleration CSV into Renode RESD input."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

MAX_SENSOR_ACCELERATION_G = Decimal(16)


def _renode_root(explicit: Path | None) -> Path:
    if explicit is not None:
        root = explicit
    elif os.environ.get("RENODE_HOME"):
        root = Path(os.environ["RENODE_HOME"])
    else:
        executable = shutil.which("renode")
        if executable is None:
            raise ValueError("pass --renode-home or put renode on PATH")
        root = Path(executable).resolve().parent
    root = root.resolve()
    if not (root / "tools" / "csv2resd" / "csv2resd.py").is_file():
        raise ValueError(f"{root} does not contain tools/csv2resd/csv2resd.py")
    return root


def _validate_resd(data: bytes, rate: Decimal, samples: list[tuple[int, int, int]]) -> None:
    if len(data) < 45 or data[:8] != b"RESD\x01\x00\x00\x00":
        raise ValueError("Renode converter did not produce a valid RESD v1 file")
    block_type, sample_type, channel_id, block_size = struct.unpack_from("<BHHQ", data, 8)
    start_time, period = struct.unpack_from("<QQ", data, 21)
    metadata_size = struct.unpack_from("<Q", data, 37)[0]
    sample_offset = 45 + metadata_size
    if (block_type, sample_type, channel_id) != (2, 2, 0) or block_size != len(data) - 21:
        raise ValueError("RESD must contain one constant-frequency acceleration block")
    if period != int(Decimal(1_000_000_000) / rate) or start_time != 0:
        raise ValueError("RESD frequency or start time does not match the dataset")
    if sample_offset > len(data) or (len(data) - sample_offset) % 12:
        raise ValueError("RESD acceleration payload is malformed")
    actual = [struct.unpack_from("<iii", data, offset) for offset in range(sample_offset, len(data), 12)]
    if actual != samples:
        raise ValueError("RESD samples do not match the selected CSV profile")


def convert_dataset(
    manifest_path: Path,
    dataset_name: str,
    output: Path,
    renode_home: Path | None = None,
    metadata_output: Path | None = None,
) -> dict:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata_output = (metadata_output or output.with_suffix(output.suffix + ".json")).resolve()
    if metadata_output == output:
        raise ValueError("RESD output and metadata sidecar must use different paths")
    metadata_output.parent.mkdir(parents=True, exist_ok=True)
    # Remove old artifacts first so any failed invocation cannot masquerade as a fresh run.
    output.unlink(missing_ok=True)
    metadata_output.unlink(missing_ok=True)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("provenance") != "SIMULATED":
        raise ValueError("manifest provenance must be SIMULATED")
    matches = [item for item in manifest.get("datasets", []) if item.get("name", "").upper() == dataset_name.upper()]
    if len(matches) != 1:
        raise ValueError(f"dataset {dataset_name!r} is missing or ambiguous")
    dataset = matches[0]
    if dataset.get("status") != "SIMULATED" or dataset.get("unit") != "g":
        raise ValueError("dataset must be a SIMULATED acceleration trace in g")
    if dataset.get("axes") != ["x", "y", "z"]:
        raise ValueError("dataset must declare x, y, z axes")
    rate = Decimal(str(dataset["sample_rate_hz"]))
    if not rate.is_finite() or rate <= 0:
        raise ValueError("sample_rate_hz must be finite and positive")
    if not isinstance(dataset.get("seed"), int) or dataset["seed"] < 0:
        raise ValueError("dataset seed must be a non-negative integer")

    source = manifest_path.parent / dataset["file"]
    with source.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["timestamp_s", "x_g", "y_g", "z_g"]:
            raise ValueError(f"unexpected CSV columns in {source}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"CSV must contain at least one acceleration sample: {source}")
    if len(rows) != dataset.get("samples"):
        raise ValueError("CSV sample count does not match the manifest")
    duration = Decimal(str(dataset["duration_s"]))
    expected_duration = Decimal(len(rows)) / rate
    if not duration.is_finite() or abs(duration - expected_duration) > Decimal("0.000000001"):
        raise ValueError("duration_s does not match samples / sample_rate_hz")

    scale = Decimal(1_000_000)
    acceleration_samples = []
    for index, row in enumerate(rows):
        timestamp = Decimal(row["timestamp_s"])
        expected_timestamp = Decimal(index) / rate
        if not timestamp.is_finite() or abs(timestamp - expected_timestamp) > Decimal("0.000000001"):
            raise ValueError(f"timestamp_s at row {index + 1} does not match the declared sample rate")
        vector = []
        for axis in "xyz":
            value = Decimal(row[f"{axis}_g"])
            if not value.is_finite():
                raise ValueError(f"{axis}_g at row {index + 1} must be finite")
            if abs(value) > MAX_SENSOR_ACCELERATION_G:
                raise ValueError(f"{axis}_g at row {index + 1} exceeds the LIS2DW12 ±16 g physical range")
            vector.append(int(value * scale))
        acceleration_samples.append(tuple(vector))

    root = _renode_root(renode_home)
    converter = root / "tools" / "csv2resd" / "csv2resd.py"
    dataset_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    identity = {
        "schema_version": 1,
        "profile": dataset["name"].upper(),
        "seed": dataset["seed"],
        "sample_rate_hz": float(rate),
        "duration_s": float(duration),
        "samples": len(rows),
        "axes": dataset["axes"],
        "unit": dataset["unit"],
        "status": "SIMULATED",
        "provenance": "SIMULATED",
        "dataset_sha256": dataset_sha256,
    }
    identity_bytes = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    profile_hash = hashlib.sha256(identity_bytes).hexdigest()
    identity["profile_hash"] = profile_hash
    identity["profile_id"] = f"{identity['profile'].lower()}-seed{identity['seed']}-{profile_hash[:12]}"
    with tempfile.TemporaryDirectory(prefix="riose-lis2dw12-") as temporary:
        temporary = Path(temporary)
        acceleration_csv = temporary / "acceleration_ug.csv"
        temporary_output = temporary / "profile.resd"
        with acceleration_csv.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(("x", "y", "z"))
            for vector in acceleration_samples:
                writer.writerow(vector)
        subprocess.run(
            [
                sys.executable,
                str(converter),
                "--input",
                str(acceleration_csv),
                "--frequency",
                str(rate),
                "--start-time",
                "0",
                "--map",
                "acceleration:x,y,z:x,y,z",
                str(temporary_output),
            ],
            check=True,
        )
        resd_bytes = temporary_output.read_bytes()
        _validate_resd(resd_bytes, rate, acceleration_samples)
        output.write_bytes(resd_bytes)
    identity["resd_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    identity["dataset_file"] = str(source.resolve())
    identity["resd_file"] = str(output)
    metadata_output.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return identity


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="dataset name, e.g. WALK")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).parents[2] / "models" / "lis2dw12" / "datasets" / "manifest.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata-output", type=Path)
    parser.add_argument("--renode-home", type=Path)
    args = parser.parse_args()
    identity = convert_dataset(args.manifest, args.dataset, args.output, args.renode_home, args.metadata_output)
    print(f"Wrote {identity['profile_id']} SIMULATED RESD sha256={identity['resd_sha256']} to {args.output}")


if __name__ == "__main__":
    main()
