"""Subprocess and output-file helpers for the digital-twin runner."""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path
from typing import Any

def _run_command(name: str, command: list[str], cwd: Path, timeout_s: int = 120,
                 env: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                                timeout=timeout_s, check=False, env=env)
    except FileNotFoundError:
        return {"status": "NOT_AVAILABLE", "detail": f"command not found: {command[0]}", "required": True}
    except subprocess.TimeoutExpired as exc:
        return {"status": "TIMED_OUT", "detail": str(exc), "required": True}
    return {"status": "PASSED" if result.returncode == 0 else "FAILED",
            "return_code": result.returncode, "stdout": result.stdout[-12000:],
            "stderr": result.stderr[-12000:], "command": command, "required": True}

def _clear_previous_outputs(*paths: Path) -> None:
    """Prevent failed reruns from promoting a stale report or metrics artifact."""
    for path in paths:
        path.unlink(missing_ok=True)

def _write_empty_csv(path: Path, fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.DictWriter(stream, fieldnames=fields, lineterminator="\n").writeheader()
