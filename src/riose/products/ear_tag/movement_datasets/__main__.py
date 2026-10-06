"""Command-line entry point for explicit movement-dataset actions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from riose.evidence.bridge import EvidenceClass

from .actbecalf import ADAPTER_VERSION, DATASET_DOI, SOURCE_URL, adapt_actbecalf_csv
from .acquisition import ACTBECALF_PUBLISHER_MD5, ACTBECALF_PUBLISHER_SIZE, download_dataset


def _file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm, usedforsecurity=False)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_new(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.link(temporary, path)
    except FileExistsError as exc:
        raise FileExistsError(f"refusing to overwrite existing derived output: {path}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RIOSE bovine movement dataset catalog and adapters")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog", help="print the checked-in candidate source catalog")
    fetch = commands.add_parser("fetch-actbecalf", help="download the licensed official ActBeCalf CSV")
    fetch.add_argument("destination", type=Path)
    convert = commands.add_parser("convert-actbecalf", help="convert an ActBeCalf CSV to canonical JSONL")
    convert.add_argument("source", type=Path)
    convert.add_argument("output", type=Path)
    evidence = convert.add_mutually_exclusive_group()
    evidence.add_argument("--measured", action="store_true",
                         help="assert the official publisher-checksummed source as external MEASURED data")
    evidence.add_argument("--simulated", action="store_true",
                         help="mark a synthetic or test fixture explicitly as SIMULATED")
    args = parser.parse_args(argv)

    if args.command == "catalog":
        catalog = Path(__file__).resolve().with_name("catalog.json")
        if not catalog.is_file():
            catalog = Path(__file__).resolve().parents[5] / "datasets" / "movement_biosignature" / "catalog.json"
        if not catalog.is_file():
            parser.error("checked-in catalog.json was not found from this source checkout")
        print(catalog.read_text(encoding="utf-8"), end="")
        return 0
    if args.command == "fetch-actbecalf":
        print(json.dumps(download_dataset("actbecalf", args.destination), sort_keys=True))
        return 0

    source = args.source.resolve()
    output = args.output.resolve()
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    if output == source or manifest_path == source:
        parser.error("derived output must be separate from the immutable raw source")
    if output.exists() or manifest_path.exists():
        parser.error("refusing to overwrite existing derived output or manifest")
    source_digest = _file_digest(source, "sha256")
    if args.measured:
        publisher_md5 = _file_digest(source, "md5")
        if publisher_md5 != ACTBECALF_PUBLISHER_MD5 or source.stat().st_size != ACTBECALF_PUBLISHER_SIZE:
            parser.error("--measured requires a byte-identical file matching the official publisher checksum")
    evidence_class = (
        EvidenceClass.MEASURED if args.measured else
        EvidenceClass.SIMULATED if args.simulated else EvidenceClass.UNKNOWN
    )
    count = 0
    unknown_label_examples: list[str] = []
    manifest = {
        "adapter": "actbecalf",
        "adapter_version": ADAPTER_VERSION,
        "dataset_doi": DATASET_DOI,
        "source_url": SOURCE_URL,
        "source_file": source.name,
        "source_sha256": source_digest,
        "source_md5_verified": args.measured,
        "evidence_status": evidence_class.value,
        "canonical_label_policy": "UNKNOWN; original source label preserved",
        "canonical_unknown_count": 0,
        "canonical_unknown_original_label_examples": [],
        "sample_count": 0,
        "output_file": output.name,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    staged_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.name}.", delete=False) as staged:
            staged_path = Path(staged.name)
            for sample in adapt_actbecalf_csv(source, evidence_class=evidence_class):
                if sample.source_file_sha256 != source_digest:
                    raise ValueError("adapter snapshot checksum differs from the conversion source; no output was published")
                staged.write((sample.to_json() + "\n").encode("utf-8"))
                count += 1
                if sample.canonical_label == "UNKNOWN" and sample.original_label not in unknown_label_examples:
                    if len(unknown_label_examples) < 10:
                        unknown_label_examples.append(sample.original_label)
            staged.flush()
            os.fsync(staged.fileno())
    except BaseException:
        if staged_path is not None:
            staged_path.unlink(missing_ok=True)
        raise
    assert staged_path is not None
    if _file_digest(source, "sha256") != source_digest:
        staged_path.unlink(missing_ok=True)
        parser.error("raw source changed during conversion; no output was published")
    manifest["sample_count"] = count
    manifest["canonical_unknown_count"] = count
    manifest["canonical_unknown_original_label_examples"] = unknown_label_examples
    manifest["output_sha256"] = _file_digest(staged_path, "sha256")
    published = False
    try:
        try:
            os.link(staged_path, output)
            published = True
        except FileExistsError as exc:
            raise FileExistsError(f"refusing to overwrite existing derived output: {output}") from exc
        _write_new(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    except BaseException:
        if published:
            output.unlink(missing_ok=True)
        raise
    finally:
        staged_path.unlink(missing_ok=True)
    print(json.dumps({"output": str(output), "manifest": str(manifest_path), "sample_count": count},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
