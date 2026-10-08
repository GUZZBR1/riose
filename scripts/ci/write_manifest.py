"""Write deterministic SHA-256 inventory for the versioned SC-4 package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "ci-scientific-gates"
MANIFEST = PACKAGE / "manifest.json"


def main() -> None:
    artifacts = {}
    for path in sorted(PACKAGE.rglob("*")):
        if not path.is_file() or path == MANIFEST:
            continue
        if any(part in {"__pycache__", ".pytest_cache"} for part in path.parts):
            continue
        artifacts[path.relative_to(PACKAGE).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    discovery = json.loads((PACKAGE / "discovery.json").read_text(encoding="utf-8"))
    document = {
        "schema_version": "riose.sc4-evidence-manifest/v1",
        "repository": discovery["repository"],
        "branch": discovery["branch"],
        "base_sha": discovery["base_sha"],
        "artifacts": artifacts,
    }
    MANIFEST.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
