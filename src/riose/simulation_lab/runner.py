"""Pin, inspect, and safely execute the real analytical frequencia smoke runner.

This adapter validates Simulation Request V1, then invokes frequencia's existing
analytic FARM command. That command currently runs its own deterministic smoke
scenario; request parameters are not translated into a frequencia campaign.
The returned V1 result therefore contains no fabricated observations.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from typing import Any

from riose.simulation_contract import ContractError, canonical_json, content_hash, load_json, validate_result
from riose.simulation_contract.v1 import RESULT_SCHEMA

FREQUENCIA_URL = "https://github.com/GUZZBR1/frequencia.git"
EXPECTED_FREQUENCIA_SHA = "0190048023269da695c84d0ff5e1cf3c6ed502d7"
ANALYTIC_ENTRYPOINT = Path("experiments/farm_rf/run_experiment.py")
ANALYTIC_BACKEND = "analytic_free_space_plus_flat_ground_reflection"
MAX_LOG_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024 * 1024
MAX_REQUEST_BYTES = 10 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 300


class RunnerError(RuntimeError):
    """A validation or execution failure with a safe, user-facing explanation."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _controlled_environment() -> dict[str, str]:
    """Keep process launch predictable without passing unrelated secrets/config."""
    names = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE")
    env = {name: os.environ[name] for name in names if name in os.environ}
    env.update({"PYTHONUTF8": "1", "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    return env


def _git(repo: Path, *args: str, timeout: float = 60) -> str:
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], check=False,
                                capture_output=True, text=True, timeout=timeout,
                                env=_controlled_environment(), shell=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RunnerError(f"cannot inspect frequencia Git checkout ({type(exc).__name__})") from exc
    if result.returncode:
        detail = result.stderr.strip()[:500]
        raise RunnerError(f"git {' '.join(args)} failed: {detail or result.returncode}")
    return result.stdout.strip()


def _canonical_remote(url: str) -> str:
    normalized = url.strip().lower().removesuffix("/").removesuffix(".git")
    if normalized.startswith("git@github.com:"):
        normalized = "https://github.com/" + normalized[len("git@github.com:"):]
    elif normalized.startswith("ssh://git@github.com/"):
        normalized = "https://github.com/" + normalized[len("ssh://git@github.com/"):]
    return normalized


def _check_expected_sha(value: str) -> str:
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise RunnerError("expected frequencia SHA must be 40 lowercase hexadecimal characters")
    return value


def _repo_path(path: str | Path | None) -> Path | None:
    raw = path if path is not None else os.environ.get("FREQUENCIA_REPO")
    return Path(raw).expanduser().resolve(strict=False) if raw is not None and str(raw).strip() else None


def _engine_inspection(path: str | Path | None, expected_sha: str) -> dict[str, Any]:
    repo = _repo_path(path)
    ns3_root = Path(os.environ.get(
        "FREQUENCIA_NS3_ROOT", str(Path.home() / ".local/share/frequencia/ns-3.48"))).expanduser()
    ns3_available = ((ns3_root / "ns3").is_file()
                     and (ns3_root / "build/lib/libns3.48-lorawan-default.so").is_file())
    inspection: dict[str, Any] = {
        "path": str(repo) if repo else None, "repository_url": FREQUENCIA_URL,
        "expected_sha": expected_sha, "actual_sha": None, "dirty": None,
        "git_repository": False, "remote_matches": False, "entrypoint_available": False,
        "python": {"available": bool(sys.executable), "executable": sys.executable,
                   "version": sys.version.split()[0]},
        "capabilities": {
            "core_python": "AVAILABLE" if sys.executable else "UNAVAILABLE",
            "analytic": "UNAVAILABLE",
            "sionna_rt": "UNAVAILABLE",
            "ns3": "AVAILABLE" if ns3_available else "UNAVAILABLE",
            "ns3_root": str(ns3_root.resolve()),
            "lorawan": "UNAVAILABLE",
            "gpu": "AVAILABLE" if shutil.which("nvidia-smi") else "UNAVAILABLE",
        },
        "errors": [],
    }
    if repo is None:
        inspection["errors"].append("frequencia path is unset; pass --repo or FREQUENCIA_REPO")
        return inspection
    if not repo.exists() or not repo.is_dir():
        inspection["errors"].append("frequencia path does not exist or is not a directory")
        return inspection
    try:
        top = Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()
    except RunnerError as exc:
        inspection["errors"].append(str(exc))
        return inspection
    inspection["git_repository"] = True
    if top != repo:
        inspection["errors"].append("frequencia path must point to the Git repository root")
        return inspection
    try:
        inspection["actual_sha"] = _git(repo, "rev-parse", "HEAD")
        inspection["dirty"] = bool(_git(repo, "status", "--porcelain=v1", "--untracked-files=normal",
                                         "--ignore-submodules=none"))
        remotes = _git(repo, "remote").splitlines()
        remote_urls = []
        for remote in remotes:
            try:
                remote_urls.extend(_git(repo, "remote", "get-url", "--all", remote).splitlines())
            except RunnerError:
                continue
        inspection["remote_matches"] = any(
            _canonical_remote(url) == _canonical_remote(FREQUENCIA_URL) for url in remote_urls)
        inspection["entrypoint_available"] = (repo / ANALYTIC_ENTRYPOINT).is_file()
        sionna_python = repo / ".venv-sionna-agent1" / "bin" / "python"
        if sys.platform == "win32":
            sionna_python = repo / ".venv-sionna-agent1" / "Scripts" / "python.exe"
        if sionna_python.is_file():
            try:
                probe = subprocess.run(
                    [str(sionna_python), "-c",
                     "import importlib.metadata as m; print(m.version('sionna-rt'))"],
                    cwd=repo, env=_controlled_environment(), capture_output=True,
                    text=True, timeout=20, check=False, shell=False)
                if probe.returncode == 0 and probe.stdout.strip():
                    inspection["capabilities"]["sionna_rt"] = "AVAILABLE"
                    inspection["capabilities"]["sionna_rt_version"] = probe.stdout.strip()[:100]
            except (OSError, subprocess.TimeoutExpired):
                pass
        entrypoint = repo / ANALYTIC_ENTRYPOINT
        if entrypoint.is_symlink() or not entrypoint.resolve().is_relative_to(repo):
            inspection["entrypoint_available"] = False
            inspection["errors"].append("frequencia analytic entrypoint must be a regular file inside the checkout")
        if inspection["entrypoint_available"]:
            inspection["capabilities"]["analytic"] = "AVAILABLE"
        if ((repo / "network" / "ns3_sionna_adapter.cc").is_file()
                and (repo / ".gitmodules").is_file()):
            inspection["capabilities"]["lorawan"] = (
                "AVAILABLE" if ns3_available else "UNAVAILABLE")
    except RunnerError as exc:
        inspection["errors"].append(str(exc))
    return inspection


def _check_inspection(inspection: dict[str, Any], *, allow_dirty: bool) -> None:
    errors = list(inspection["errors"])
    if not inspection["git_repository"]:
        errors.append("frequencia checkout is not a Git repository")
    if not inspection["remote_matches"]:
        errors.append("frequencia remote does not identify GUZZBR1/frequencia")
    if inspection["actual_sha"] != inspection["expected_sha"]:
        errors.append("frequencia HEAD does not match the expected commit SHA")
    if inspection["dirty"] and not allow_dirty:
        errors.append("frequencia checkout is dirty; pass --allow-dirty only for an intentional lab run")
    if not inspection["entrypoint_available"]:
        errors.append(f"frequencia analytic entrypoint is missing: {ANALYTIC_ENTRYPOINT.as_posix()}")
    if errors:
        raise RunnerError("; ".join(dict.fromkeys(errors)))


def doctor(repo: str | Path | None = None, *, expected_sha: str = EXPECTED_FREQUENCIA_SHA) -> dict[str, Any]:
    """Report repository identity, pin, dirty state, interpreter, and optional tools."""
    _check_expected_sha(expected_sha)
    inspection = _engine_inspection(repo, expected_sha)
    if inspection["actual_sha"] and inspection["actual_sha"] != expected_sha:
        inspection["errors"].append("HEAD differs from expected SHA")
    if inspection["dirty"]:
        inspection["errors"].append("checkout has local modifications")
    if not inspection["remote_matches"]:
        inspection["errors"].append("remote is not GUZZBR1/frequencia")
    if not inspection["entrypoint_available"]:
        inspection["errors"].append(f"entrypoint missing: {ANALYTIC_ENTRYPOINT.as_posix()}")
    inspection["errors"] = list(dict.fromkeys(inspection["errors"]))
    inspection["status"] = "READY" if not inspection["errors"] else "BLOCKED"
    return inspection


def _validate_request_file(request_path: Path, expected_sha: str) -> tuple[dict[str, Any], str]:
    try:
        if request_path.stat().st_size > MAX_REQUEST_BYTES:
            raise RunnerError(f"request exceeds the {MAX_REQUEST_BYTES // (1024 * 1024)} MiB size limit")
        request = load_json(request_path.read_text(encoding="utf-8"), kind="request")
    except RunnerError:
        raise
    except (OSError, UnicodeError, ContractError) as exc:
        raise RunnerError(f"invalid Simulation Request V1: {exc}") from exc
    if request["backend"] not in {"analytic", "frequencia.analytic", "sionna-rt"}:
        raise RunnerError(f"unsupported requested backend {request['backend']!r}; no fallback is available")
    if request["expected_evidence"] != "SIMULATED":
        raise RunnerError("Simulation Lab runs must declare expected_evidence=SIMULATED")
    pinned = request["provenance"]["frequencia_revision"]
    if pinned is not None and pinned != expected_sha:
        raise RunnerError("request provenance frequencia_revision differs from the configured expected SHA")
    return request, content_hash(request)


def _analytic_parameter_binding(request: dict[str, Any], request_hash: str) -> dict[str, Any]:
    """Keep fixed-smoke inputs distinct from the request values it does not use."""
    radio = request["radio"]
    return {
        "schema_version": "riose.simulation.parameter-binding/v1",
        "request_sha256": request_hash,
        "radio_and_backend": {
            "requested": {"backend": request["backend"], "seed": request["seed"],
                          "frequency_hz": radio["frequency_hz"],
                          "bandwidth_hz": radio["bandwidth_hz"],
                          "tx_power_dbm": radio["tx_power_dbm"]},
            "effective": {"backend": ANALYTIC_BACKEND, "seed": None,
                          "frequency_hz": None, "bandwidth_hz": None,
                          "tx_power_dbm": None},
            "status": "REQUEST_SPECIFIC_PARAMETERS_UNSUPPORTED",
        },
        "trajectory": {"requested_sha256": content_hash(request["trajectory"]),
                       "effective_sha256": None, "status": "NOT_BOUND"},
        "solver": {"requested": request["solver"]["parameters"],
                   "effective": None, "status": "NOT_BOUND"},
        "network": {"requested": request["solver"]["parameters"].get("network"),
                    "effective": None, "status": "NOT_RUN"},
        "temporal": {"requested": request["solver"]["parameters"].get("temporal"),
                     "effective": None,
                     "status": ("NOT_APPLICABLE" if request["solver"]["parameters"].get("temporal") is None
                                else "NOT_RUN")},
    }


def _default_runs_root() -> Path:
    configured = os.environ.get("RIOSE_SIMULATION_RUNS")
    if configured:
        return Path(configured).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache"))
    return (base / "RIOSE" / "simulation_runs").resolve()


def _new_workspace(root: Path) -> tuple[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        run_id = uuid.uuid4().hex
        path = root / run_id
        try:
            path.mkdir()
            return run_id, path
        except FileExistsError:
            continue
    raise RunnerError("could not allocate a unique run workspace")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(canonical_json(value) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _run_process(command: list[str], *, cwd: Path, logs: Path,
                 timeout_seconds: float, output_dir: Path | None = None) -> tuple[int, str | None]:
    """Stream bounded child output to isolated files; kill on timeout or log overflow."""
    logs.mkdir(parents=True, exist_ok=True)
    overflow = threading.Event()
    errors: list[str] = []

    def pump(source: Any, destination: Path) -> None:
        written = 0
        try:
            with destination.open("wb") as output:
                while chunk := source.read(65536):
                    remaining = MAX_LOG_BYTES - written
                    if remaining > 0:
                        output.write(chunk[:remaining])
                        written += min(len(chunk), remaining)
                    if len(chunk) > remaining:
                        overflow.set()
                output.flush()
        except OSError as exc:
            errors.append(type(exc).__name__)
            overflow.set()

    try:
        process = subprocess.Popen(command, cwd=cwd, env=_controlled_environment(), shell=False,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise RunnerError(f"could not start frequencia process: {type(exc).__name__}") from exc
    assert process.stdout is not None and process.stderr is not None
    threads = [threading.Thread(target=pump, args=(stream, logs / name), daemon=True)
               for stream, name in ((process.stdout, "stdout.log"), (process.stderr, "stderr.log"))]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout_seconds
    next_output_check = time.monotonic()
    reason: str | None = None
    while process.poll() is None:
        if overflow.is_set():
            reason = f"process output exceeded the {MAX_LOG_BYTES // (1024 * 1024)} MiB per-stream limit"
            process.kill()
            break
        if time.monotonic() >= deadline:
            reason = f"process timed out after {timeout_seconds:g} seconds"
            process.kill()
            break
        if output_dir is not None and time.monotonic() >= next_output_check:
            next_output_check = time.monotonic() + 0.5
            try:
                files = list(output_dir.rglob("*")) if output_dir.exists() else []
                output_bytes = sum(item.stat().st_size for item in files
                                   if item.is_file() and not item.is_symlink())
                symlink_output = any(item.is_symlink() for item in files)
            except OSError:
                output_bytes, symlink_output = MAX_OUTPUT_BYTES + 1, False
            if output_bytes > MAX_OUTPUT_BYTES or symlink_output:
                reason = (f"process output exceeded the {MAX_OUTPUT_BYTES // (1024 * 1024)} MiB workspace limit"
                          if output_bytes > MAX_OUTPUT_BYTES else "process output created a symlink")
                process.kill()
                break
        time.sleep(0.025)
    try:
        return_code = process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        return_code = process.wait()
    for thread in threads:
        thread.join(timeout=5)
    if any(thread.is_alive() for thread in threads):
        reason = reason or "process output reader did not terminate"
    if overflow.is_set():
        reason = reason or f"process output exceeded the {MAX_LOG_BYTES // (1024 * 1024)} MiB per-stream limit"
    if errors:
        reason = reason or f"could not persist process logs ({', '.join(errors)})"
    return return_code, reason


def _git_provenance(repo: Path) -> tuple[str | None, bool | None]:
    try:
        root = Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()
        if root != repo:
            return None, None
        sha = _git(repo, "rev-parse", "HEAD")
        dirty = bool(_git(repo, "status", "--porcelain=v1", "--untracked-files=normal",
                          "--ignore-submodules=none"))
        return sha, dirty
    except RunnerError:
        return None, None


def run(request_path: str | Path, *, repo: str | Path | None = None,
        expected_sha: str = EXPECTED_FREQUENCIA_SHA, output_root: str | Path | None = None,
        dry_run: bool = False, allow_dirty: bool = False,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Execute the pinned analytic smoke and emit a V1 result plus provenance."""
    _check_expected_sha(expected_sha)
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
        raise RunnerError("timeout_seconds must be greater than zero")
    request_file = Path(request_path).expanduser().resolve(strict=False)
    request, request_hash = _validate_request_file(request_file, expected_sha)
    if request["backend"] == "sionna-rt":
        from .farm_rf import run_farm_sionna
        return run_farm_sionna(request, request_hash, repo=repo, expected_sha=expected_sha,
                               output_root=output_root, timeout_seconds=timeout_seconds,
                               allow_dirty=allow_dirty, dry_run=dry_run)
    inspection = _engine_inspection(repo, expected_sha)
    _check_inspection(inspection, allow_dirty=allow_dirty)
    engine_root = Path(inspection["path"])
    run_id, workspace = _new_workspace(Path(output_root).expanduser().resolve() if output_root else _default_runs_root())
    request_copy = workspace / "request" / "request.json"
    _write_json(request_copy, request)
    riose_root = Path(__file__).resolve().parents[3]
    riose_sha, riose_dirty = _git_provenance(riose_root)
    command = [sys.executable, str(engine_root / ANALYTIC_ENTRYPOINT), "--backend", "analytic",
               "--output-dir", str(workspace / "outputs" / "engine")]
    started_at = _utc_now()
    started = time.monotonic()
    exit_code: int | None = None
    result: dict[str, Any] | None = None
    output_hash: str | None = None
    execution_error: str | None = None
    if not dry_run:
        try:
            exit_code, process_error = _run_process(command, cwd=engine_root,
                                                    logs=workspace / "logs", timeout_seconds=float(timeout_seconds),
                                                    output_dir=workspace / "outputs" / "engine")
            if process_error:
                raise RunnerError(process_error)
            if exit_code != 0:
                raise RunnerError(f"frequencia process exited with code {exit_code}; see {workspace / 'logs'}")
            summary_path = workspace / "outputs" / "engine" / "summary.json"
            if not summary_path.is_file():
                raise RunnerError("frequencia exited successfully but did not produce summary.json")
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"),
                                     parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                raise RunnerError("frequencia summary.json is malformed") from exc
            if (not isinstance(summary, dict) or summary.get("backend") != ANALYTIC_BACKEND
                    or summary.get("classification") != "SIMULAÇÃO"):
                raise RunnerError("frequencia output does not identify the expected analytical SIMULACAO backend")
            output_hash = _sha256(summary_path)
            result = {
                "schema_version": RESULT_SCHEMA, "campaign_id": request["campaign_id"],
                "scenario_id": request["scenario_id"], "backend": "frequencia.analytic",
                "solver_version": inspection["actual_sha"], "status": "SIMULATED",
                "id_mappings": [], "observations": [], "locations": [],
                "warnings": ["frequencia's built-in analytic smoke scenario ran; request-specific observations are not yet mapped."],
                "limitations": ["Request geometry, radio parameters, and seed are validated and hashed but are not translated to frequencia input yet."],
                "provenance": {"request_sha256": request_hash, "output_sha256": output_hash, "completed_at": _utc_now()},
            }
            validate_result(result)
            _write_json(workspace / "result" / "result.json", result)
        except RunnerError as exc:
            execution_error = str(exc)
    manifest = {
        "schema_version": "riose.simulation.run-manifest/v1", "run_id": run_id,
        "campaign_id": request["campaign_id"], "riose": {"revision": riose_sha, "dirty": riose_dirty},
        "engine": {"repository_url": FREQUENCIA_URL, "path": str(engine_root),
                   "expected_sha": expected_sha, "actual_sha": inspection["actual_sha"],
                   "dirty": inspection["dirty"], "capabilities": inspection["capabilities"]},
        "backend_requested": request["backend"],
        "backend_used": None if dry_run or execution_error else "frequencia.analytic",
        "evidence_classification": "SIMULATED", "request_sha256": request_hash,
        "parameter_binding": _analytic_parameter_binding(request, request_hash),
        "seed": request["seed"],
        "request_path": str(request_copy), "command": command, "working_directory": str(engine_root),
        "started_at": started_at, "finished_at": _utc_now(),
        "duration_seconds": time.monotonic() - started, "exit_code": exit_code,
        "dry_run": dry_run, "output_sha256": output_hash,
        "execution_status": "FAILED" if execution_error else ("PLANNED" if dry_run else "SIMULATED"),
        "error": execution_error,
        "warnings": ["Smoke validates the engine process boundary; request parameters are not yet mapped into its internal scenario."],
    }
    _write_json(workspace / "manifest.json", manifest)
    if execution_error:
        raise RunnerError(f"{execution_error}; manifest: {workspace / 'manifest.json'}")
    return {"run_id": run_id, "workspace": str(workspace), "manifest": manifest,
            "result": result, "status": "PLANNED" if dry_run else "SIMULATED"}
