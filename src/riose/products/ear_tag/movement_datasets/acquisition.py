"""Explicit, checksum-verified acquisition for redistributable ActBeCalf."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from typing import BinaryIO, Callable
from urllib.request import urlopen

ACTBECALF_CONTENT_URL = "https://zenodo.org/api/records/13259482/files/AcTBeCalf.csv/content"
ACTBECALF_PUBLISHER_MD5 = "59bd00564af64d92489485fa5a8a3960"
ACTBECALF_PUBLISHER_SIZE = 177608717


def _file_md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_actbecalf(
    destination: str | Path,
    *,
    opener: Callable[..., BinaryIO] = urlopen,
) -> dict[str, object]:
    """Download the official CC BY 4.0 file once, rejecting changed content.

    This function is only called explicitly; importing the module performs no
    network activity. Existing files are never overwritten.
    """

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        actual = _file_md5(target)
        if actual != ACTBECALF_PUBLISHER_MD5 or target.stat().st_size != ACTBECALF_PUBLISHER_SIZE:
            raise ValueError("existing destination has unexpected content; refusing to overwrite it")
        return {"path": str(target), "status": "ALREADY_PRESENT", "md5": actual}

    temporary_path: Path | None = None
    digest = hashlib.md5(usedforsecurity=False)
    size = 0
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", delete=False) as output:
            temporary_path = Path(output.name)
            with opener(ACTBECALF_CONTENT_URL, timeout=60) as response:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        if digest.hexdigest() != ACTBECALF_PUBLISHER_MD5 or size != ACTBECALF_PUBLISHER_SIZE:
            raise ValueError("download checksum does not match the publisher record")
        # A same-filesystem hard link publishes atomically and cannot replace a
        # file another process created after the first existence check.
        try:
            os.link(temporary_path, target)
        except FileExistsError:
            actual = _file_md5(target)
            if actual != ACTBECALF_PUBLISHER_MD5 or target.stat().st_size != ACTBECALF_PUBLISHER_SIZE:
                raise ValueError("destination was created with unexpected content; refusing to overwrite it")
            return {"path": str(target), "status": "ALREADY_PRESENT", "md5": actual}
        return {"path": str(target), "status": "DOWNLOADED", "md5": digest.hexdigest()}
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def download_dataset(dataset_id: str, destination: str | Path) -> dict[str, object]:
    """Fail closed for catalogued sources without a verified fetch workflow."""

    if dataset_id != "actbecalf":
        raise ValueError(f"automated acquisition is not enabled for dataset {dataset_id!r}")
    return download_actbecalf(destination)
