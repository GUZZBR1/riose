"""Deterministic summary/report generation and fail-closed evidence packaging."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import tempfile
from typing import Any

from riose.simulation_contract.v1 import (
    ContractError,
    canonical_json,
    content_hash,
    load_json,
)


MANIFEST_SCHEMA = "riose.simulation.evidence-manifest/v1"
SUMMARY_SCHEMA = "riose.simulation.evidence-summary/v1"
DEFAULT_MAX_PACKAGE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
_REQUIRED = {"request.json", "summary.json", "report.md"}
_DENIED_NAMES = {".env", "id_rsa", "id_ed25519", "credentials", "credentials.json", "secrets.json",
                 ".git", ".venv", "__pycache__", "node_modules"}
_FIGURE_EXTENSIONS = {".png", ".svg", ".jpg", ".jpeg", ".webp", ".pdf"}


class EvidenceError(ValueError):
    """Input or package violates the evidence pipeline's safety policy."""


def _json_bytes(value: Any) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _check_sensitive_value(value: Any, where: str = "request") -> None:
    if isinstance(value, str):
        sensitive = ("-----begin ", "ghp_", "github_pat_", "bearer ", "sk-")
        lower = value.lower()
        if (any(marker in lower for marker in sensitive)
                or re.search(r"(?:^[/~]|^[A-Za-z]:[\\/]|^\\\\|/home/[^\s]+|/root/[^\s]*|[A-Za-z]:\\Users\\[^\\\s]+|\\\\[^\\]+\\Users\\[^\\]+)", value, re.I)):
            raise EvidenceError(f"sensitive or machine-local value is not allowed in {where}")
    elif isinstance(value, dict):
        for key, item in value.items():
            if re.search(r"(?:secret|token|password|credential|private[_-]?key)", str(key), re.I):
                raise EvidenceError(f"secret-like field is not allowed in {where}.{key}")
            _check_sensitive_value(item, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_sensitive_value(item, f"{where}[{index}]")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relative(raw: str) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        raise EvidenceError(f"unsafe artifact path: {raw!r}")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise EvidenceError(f"unsafe artifact path: {raw!r}")
    if path.parts and ":" in path.parts[0]:
        raise EvidenceError(f"absolute artifact path is not allowed: {raw!r}")
    if any(part.startswith(".") or not re.fullmatch(r"[A-Za-z0-9._-]+", part) for part in path.parts):
        raise EvidenceError(f"artifact path contains unsupported characters: {raw!r}")
    if any(part.lower() in _DENIED_NAMES or part.lower().startswith((".env.", "id_rsa", "id_ed25519", "secret", "credential"))
           or part.lower().endswith((".pem", ".key", ".p12", ".pfx")) for part in path.parts):
        raise EvidenceError(f"sensitive artifact path is not allowed: {raw!r}")
    return path


def _read_source(root: Path, relative: str, *, max_bytes: int) -> bytes:
    safe = _safe_relative(relative)
    source = root.joinpath(*safe.parts)
    try:
        if any(part.is_symlink() for part in (source, *source.parents) if part != root.parent):
            raise EvidenceError(f"symlink inputs are not allowed: {relative}")
        resolved = source.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError(f"artifact is missing or escapes campaign directory: {relative}") from exc
    if not resolved.is_file():
        raise EvidenceError(f"artifact is not a regular file: {relative}")
    size = resolved.stat().st_size
    if size > max_bytes:
        raise EvidenceError(f"artifact exceeds size limit ({size} > {max_bytes}): {relative}")
    return resolved.read_bytes()


def _source_name(root: Path, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if (root / name).exists() or (root / name).is_symlink():
            return name
    return None


def _load_json_source(root: Path, name: str, *, max_bytes: int) -> dict[str, Any]:
    try:
        value = json.loads(_read_source(root, name, max_bytes=max_bytes).decode("utf-8"),
                           parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise EvidenceError(f"{name} is malformed JSON") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"{name} must contain a JSON object")
    return value


def _metric(value: float | int | None, unit: str | None, *, status: str = "AVAILABLE",
            numerator: int | None = None, denominator: int | None = None) -> dict[str, Any]:
    return {"value": value, "unit": unit, "status": status,
            "numerator": numerator, "denominator": denominator}


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _md(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("`", "\\`").replace("<", "&lt;").replace(">", "&gt;").replace("\n", " ").replace("\r", " ")


def _statistics(values: list[float], unit: str) -> dict[str, Any]:
    if not values:
        return {name: _metric(None, unit, status="NOT_AVAILABLE") for name in ("mean", "median", "min", "max")}
    ordered = sorted(values)
    n = len(ordered)
    median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    return {"mean": _metric(_mean(values), unit), "median": _metric(median, unit),
            "min": _metric(ordered[0], unit), "max": _metric(ordered[-1], unit)}


def _validate_location_quality(request: dict[str, Any], result: dict[str, Any]) -> None:
    """Recompute the operational plausibility gate from canonical request bounds."""
    bounds = request.get("operational_bounds_m")
    for index, location in enumerate(result["locations"]):
        if "quality_status" not in location:
            continue
        position = location["position_m"]
        solver_status = location["solver_status"]
        if position is None:
            expected = ("NOT_EVALUATED", f"NO_NUMERICAL_POSITION:{solver_status}", bounds)
        elif bounds is None:
            expected = ("NOT_EVALUATED", "NO_DECLARED_OPERATIONAL_BOUNDS", None)
        else:
            inside = (bounds["east_min_m"] <= position[0] <= bounds["east_max_m"]
                      and bounds["north_min_m"] <= position[1] <= bounds["north_max_m"])
            expected = ("ACCEPTED" if inside else "REJECTED",
                        "WITHIN_DECLARED_OPERATIONAL_BOUNDS" if inside
                        else "OUTSIDE_DECLARED_OPERATIONAL_BOUNDS", bounds)
        observed = (location["quality_status"], location["quality_reason"],
                    location["quality_bounds_m"])
        if observed != expected:
            raise EvidenceError(f"result location {index} quality gate does not match request-declared bounds")


def _validate_temporal_binding(binding: Any, requested: Any, expected_seed: int, request_hash: str,
                               run_id: str | None, artifacts: Any) -> None:
    if (not isinstance(binding, dict) or binding.get("requested") != requested
            or binding.get("status") not in {"VERIFIED", "NOT_RUN", "NOT_APPLICABLE"}):
        raise EvidenceError("manifest temporal binding differs from the request")
    if binding["status"] != "VERIFIED":
        if requested is None and binding["status"] != "NOT_APPLICABLE":
            raise EvidenceError("absent temporal settings must be marked NOT_APPLICABLE")
        if binding.get("effective") is not None:
            raise EvidenceError("unrun temporal settings cannot claim effective values")
        return
    if not isinstance(requested, dict):
        raise EvidenceError("temporal runtime is verified although the request has no temporal settings")
    expected_effective = {"detector": requested["detector"], "clocks": requested["clocks"],
        "clock_seed": expected_seed,
        "correlated_jitter_std_s": requested["correlated_jitter_std_s"],
        "timestamp_error_std_s": requested["timestamp_error_std_s"],
        "noise_figure_db": requested["noise_figure_db"],
        "snr_threshold_db": requested["snr_threshold_db"],
        "detection_margin_db": requested["detection_margin_db"],
        "max_iterations": requested["max_iterations"]}
    if (binding.get("schema_version") != "riose.simulation.temporal-binding/v1"
            or binding.get("run_id") != run_id
            or binding.get("request_sha256") != request_hash
            or binding.get("forwarded") != requested
            or binding.get("effective") != expected_effective
            or not isinstance(binding.get("effective_defaults"), dict)
            or set(binding["effective_defaults"]) != {"phy.preamble_symbols", "sweep.noise_density_dbm_hz"}
            or any(not isinstance(row, dict) or row.get("requested") is not None
                   or row.get("status") != "VERIFIED"
                   or isinstance(row.get("effective"), bool)
                   or not isinstance(row.get("effective"), (int, float))
                   or not math.isfinite(row["effective"])
                   for row in binding["effective_defaults"].values())
            or type(binding["effective_defaults"]["phy.preamble_symbols"]["effective"]) is not int
            or not isinstance(binding.get("observed_detector_modes"), list)
            or any(mode != requested["detector"]["mode"]
                   for mode in binding["observed_detector_modes"])):
        raise EvidenceError("verified temporal runtime settings lack matching run-level evidence")
    if (not isinstance(artifacts, dict)
            or binding.get("input_sha256") != artifacts.get("inputs.json")
            or binding.get("runtime_artifact_sha256") != artifacts.get("pipeline.json")):
        raise EvidenceError("temporal runtime binding is not tied to this run's input and output artifacts")


def _summary(request: dict[str, Any], result: dict[str, Any] | None, failure: dict[str, Any] | None) -> dict[str, Any]:
    campaign_id = request["campaign_id"]
    if failure is not None:
        return {"schema_version": SUMMARY_SCHEMA, "campaign_id": campaign_id,
                "status": "FAILED", "evidence_status": "SIMULATED",
                "rf": {"links": _metric(None, "links", status="NOT_RUN"), "los": _metric(None, "links", status="NOT_RUN"),
                       "nlos": _metric(None, "links", status="NOT_RUN"), "no_path": _metric(None, "links", status="NOT_RUN"),
                       "received_power_dbm": _statistics([], "dBm"), "propagation_delay_s": _statistics([], "s")},
                "network": {key: _metric(None, unit, status="NOT_RUN") for key, unit in
                            (("transmitted", "packets"), ("received", "packets"), ("drops", "packets"), ("collisions", "packets"), ("pdr", "ratio"))},
                "localization": {key: _metric(None, unit, status="NOT_RUN") for key, unit in
                                 (("attempts", "estimates"), ("positions_available", "estimates"),
                                  ("converged", "estimates"), ("failed", "estimates"),
                                  ("convergence_rate", "ratio"), ("rmse", "m"), ("median_error", "m"))}
                                | {"quality": {"ACCEPTED": 0, "REJECTED": 0, "NOT_EVALUATED": 0}}}

    assert result is not None
    observations = result["observations"]
    links = len(observations)
    states = [row["metrics"]["path_state"] for row in observations]
    powers = [float(row["metrics"]["received_power_dbm"]) for row in observations
              if row["metrics"]["received_power_dbm"] is not None]
    delays = [float(row["metrics"]["propagation_delay_s"]) for row in observations
              if row["metrics"]["propagation_delay_s"] is not None]
    locations = result["locations"]
    location_positions = sum(row["position_m"] is not None for row in locations)
    return {
        "schema_version": SUMMARY_SCHEMA, "campaign_id": campaign_id,
        "status": "COMPLETED", "evidence_status": "SIMULATED",
        "rf": {
            "links": _metric(links, "links"),
            "los": _metric(states.count("LOS"), "links"),
            "nlos": _metric(states.count("NLOS"), "links"),
            "no_path": _metric(states.count("NO_PATH"), "links"),
            "received_power_dbm": _statistics(powers, "dBm"),
            "propagation_delay_s": _statistics(delays, "s"),
        },
        # V1 link observations do not carry packet identity or network-event
        # counters. Counting one row per receiver would inflate TX/PDR, so
        # packet-level network metrics remain explicitly unavailable.
        "network": {key: _metric(None, unit, status="NOT_AVAILABLE") for key, unit in
                    (("transmitted", "packets"), ("received", "packets"), ("drops", "packets"),
                     ("collisions", "packets"), ("pdr", "ratio"))},
        "localization": {
            "attempts": _metric(len(locations), "estimates"),
            "positions_available": _metric(location_positions, "estimates"),
            "quality": {status: sum(row.get("quality_status", "NOT_EVALUATED") == status
                                    for row in locations)
                        for status in ("ACCEPTED", "REJECTED", "NOT_EVALUATED")},
            "converged": _metric(None, "estimates", status="NOT_AVAILABLE"),
            "failed": _metric(None, "estimates", status="NOT_AVAILABLE"),
            "convergence_rate": _metric(None, "ratio", status="NOT_AVAILABLE"),
            "rmse": _metric(None, "m", status="NOT_AVAILABLE"),
            "median_error": _metric(None, "m", status="NOT_AVAILABLE"),
        },
    }


def _report(manifest: dict[str, Any], summary: dict[str, Any]) -> str:
    request = manifest["configuration"]
    engine = manifest["engine"]
    limitations = manifest["limitations"]
    binding = request["parameter_binding"]
    def metric(v: dict[str, Any]) -> str:
        return "NOT AVAILABLE" if v["value"] is None else f"{v['value']} {v['unit'] or ''}".strip()
    lines = [
        "# Simulation Evidence Report", "", "## Campaign", f"- ID: `{_md(manifest['campaign_id'])}`",
        f"- Status: **{manifest['execution']['status']}**", "", "## Purpose",
        "Package selected simulation outputs for reproducibility and audit.", "",
        "## Configuration",
        f"- Seed requested / used: {request['seed_requested']} / {request['seed_used'] if request['seed_used'] is not None else 'NOT AVAILABLE'}",
        f"- Frequency requested / used: {request['frequency_hz_requested']} / {request['frequency_hz_used'] if request['frequency_hz_used'] is not None else 'NOT AVAILABLE'} Hz",
        f"- Bandwidth requested / used: {request['bandwidth_hz_requested'] if request['bandwidth_hz_requested'] is not None else 'NOT AVAILABLE'} / {request['bandwidth_hz_used'] if request['bandwidth_hz_used'] is not None else 'NOT AVAILABLE'} Hz",
        f"- TX power requested / used: {request['tx_power_dbm_requested']} / {request['tx_power_dbm_used'] if request['tx_power_dbm_used'] is not None else 'NOT AVAILABLE'} dBm",
        f"- Used configuration source: {request['used_configuration_source'] or 'NOT AVAILABLE'}", "", "## Engine",
        f"- Backend requested/used: {_md(engine['backend_requested'])} / {_md(engine['backend_used'])}",
        f"- Parameter binding: radio/backend `{binding.get('radio_and_backend', {}).get('status', binding.get('status', 'NOT_AVAILABLE'))}`; "
        f"trajectory `{binding.get('trajectory', {}).get('status', 'NOT_AVAILABLE')}`; "
        f"network `{binding.get('network', {}).get('status', 'NOT_AVAILABLE')}`; "
        f"temporal `{binding.get('temporal', {}).get('status', 'NOT_AVAILABLE')}`",
        f"- Solver version: {_md(engine['solver_version'] or 'NOT AVAILABLE')}",
        *(f"- Failure ({_md(item['category'])}): {_md(item['message'])}" for item in manifest["execution"]["failures"]), "",
        "## RF Results", f"- Links: {metric(summary['rf']['links'])}",
        f"- LOS / NLOS / NO_PATH: {metric(summary['rf']['los'])} / {metric(summary['rf']['nlos'])} / {metric(summary['rf']['no_path'])}",
        f"- Received power mean: {metric(summary['rf']['received_power_dbm']['mean'])}",
        f"- Propagation delay mean: {metric(summary['rf']['propagation_delay_s']['mean'])}", "",
        "## Network Results", f"- TX / RX / drops: {metric(summary['network']['transmitted'])} / {metric(summary['network']['received'])} / {metric(summary['network']['drops'])}",
        f"- PDR: {metric(summary['network']['pdr'])}", f"- Collisions: {metric(summary['network']['collisions'])}", "",
        "## Localization Results", f"- Attempts: {metric(summary['localization']['attempts'])}",
        f"- Positions available: {metric(summary['localization']['positions_available'])}",
        f"- Operational quality accepted / rejected / not evaluated: "
        f"{summary['localization']['quality']['ACCEPTED']} / "
        f"{summary['localization']['quality']['REJECTED']} / "
        f"{summary['localization']['quality']['NOT_EVALUATED']}",
        f"- RMSE: {metric(summary['localization']['rmse'])}", "",
        "## Evidence Classification", "**EvidenceStatus: SIMULATED**",
        "THIS PACKAGE CONTAINS SIMULATION EVIDENCE. IT DOES NOT CONSTITUTE PHYSICAL OR FIELD VALIDATION.", "",
        "## Reproducibility", f"- Request SHA-256: `{manifest['request_hash']}`",
        f"- Source result SHA-256: `{manifest['provenance']['source_result_sha256'] or 'NOT AVAILABLE'}`",
        f"- Engine output SHA-256: `{manifest['provenance']['engine_output_sha256'] or 'NOT AVAILABLE'}`",
        f"- RIOSE revision: {manifest['provenance']['riose']['sha'] or 'NOT AVAILABLE'}",
        f"- frequencia revision: {manifest['provenance']['frequencia']['sha'] or 'NOT AVAILABLE'}",
        "- Configuration reproducibility is recorded; bitwise-identical output is not promised.", "",
        "## Limitations", *(f"- {_md(text)}" for text in limitations),
        "", "## Tested", *(f"- {_md(text)}" for text in manifest["tested"]),
        "", "## Not Tested", *(f"- {_md(text)}" for text in manifest["not_tested"]),
        "", "## Artifacts", *(f"- `{_md(item['path'])}` ({item['size_bytes']} bytes, SHA-256 `{item['sha256']}`)"
                               for item in manifest["outputs"] if item["path"] != "report.md"), "",
    ]
    return "\n".join(lines)


def _git_provenance(repo: Path | None) -> dict[str, Any]:
    if repo is None:
        return {"repository": "RIOSE", "sha": None, "dirty": None}
    import subprocess
    try:
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                             capture_output=True, text=True, timeout=3).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], check=True,
                                    capture_output=True, text=True, timeout=3).stdout.strip())
        return {"repository": "RIOSE", "sha": sha, "dirty": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"repository": "RIOSE", "sha": None, "dirty": None}


def build_package(campaign: str | Path, destination: str | Path, *,
                  selected_artifacts: tuple[str, ...] | list[str] = (),
                  max_package_bytes: int = DEFAULT_MAX_PACKAGE_BYTES,
                  max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
                  riose_repo: str | Path | None = None,
                  frequencia_repo: str | Path | None = None) -> dict[str, Any]:
    """Build an atomic package from request/result JSON and explicitly selected files.

    Accepts root-level fixture inputs or the Simulation Lab runner's
    request/request.json, result/result.json, manifest.json layout. Failed runs
    may use request.json plus failure.json; existing destinations are preserved.
    """
    target = Path(destination).absolute()
    if max_package_bytes <= 0 or max_artifact_bytes <= 0:
        raise EvidenceError("size limits must be positive")
    try:
        root = Path(campaign).resolve(strict=True)
        if not root.is_dir() or target.exists() or target.is_symlink():
            raise EvidenceError("campaign must be a directory and destination must not exist")
        if target.resolve(strict=False).is_relative_to(root):
            raise EvidenceError("package destination must be outside the campaign source directory")
        request_name = _source_name(root, ("request.json", "request/request.json"))
        if request_name is None:
            raise EvidenceError("campaign request.json is missing")
        request = load_json(_read_source(root, request_name, max_bytes=max_artifact_bytes).decode("utf-8"), kind="request")
        _check_sensitive_value(request)
        run_name = _source_name(root, ("manifest.json",))
        run_metadata = _load_json_source(root, run_name, max_bytes=max_artifact_bytes) if run_name else None
        if run_metadata is not None:
            if run_metadata.get("schema_version") != "riose.simulation.run-manifest/v1":
                raise EvidenceError("unsupported source run manifest schema")
            if (run_metadata.get("campaign_id") != request["campaign_id"]
                    or run_metadata.get("request_sha256") != content_hash(request)
                    or run_metadata.get("backend_requested") != request["backend"]
                    or run_metadata.get("evidence_classification") != "SIMULATED"
                    or run_metadata.get("exit_code") != 0 or run_metadata.get("dry_run") is True):
                raise EvidenceError("run manifest does not verify against request or successful SIMULATED execution")
        failure: dict[str, Any] | None = None
        result: dict[str, Any] | None = None
        result_name = _source_name(root, ("result.json", "result/result.json"))
        if result_name is not None:
            result = load_json(_read_source(root, result_name, max_bytes=max_artifact_bytes).decode("utf-8"), kind="result")
            if (result["campaign_id"] != request["campaign_id"]
                    or result["scenario_id"] != request["scenario_id"]
                    or (run_metadata is None and result["backend"] != request["backend"])):
                raise EvidenceError("request and result identity/configuration do not match")
            if run_metadata is not None and run_metadata.get("backend_used") != result["backend"]:
                raise EvidenceError("run manifest backend differs from Simulation Result")
            if result["provenance"]["request_sha256"] not in (None, content_hash(request)):
                raise EvidenceError("result request hash does not match canonical request")
            _validate_location_quality(request, result)
        else:
            failure_name = _source_name(root, ("failure.json",))
            if failure_name is None:
                raise EvidenceError("campaign has neither a result nor failure.json")
            failure = _load_json_source(root, failure_name, max_bytes=max_artifact_bytes)
            _check_sensitive_value(failure, "failure")
            if set(failure) != {"status", "error_category", "message", "completed_at", "warnings", "limitations"} or failure["status"] != "FAILED":
                raise EvidenceError("failure.json must declare FAILED and the supported fields")
            if not isinstance(failure["error_category"], str) or not failure["error_category"].strip():
                raise EvidenceError("failure.json error_category is required")
            for key in ("message", "completed_at"):
                if not isinstance(failure[key], str) or not failure[key].strip():
                    raise EvidenceError(f"failure.json {key} is required")
            for key in ("warnings", "limitations"):
                if not isinstance(failure[key], list) or not all(isinstance(x, str) for x in failure[key]):
                    raise EvidenceError(f"failure.json {key} must be an array of strings")
            try:
                finished = datetime.fromisoformat(failure["completed_at"].replace("Z", "+00:00"))
            except ValueError as exc:
                raise EvidenceError("failure.json completed_at must be ISO-8601") from exc
            if finished.tzinfo is None or finished.utcoffset() is None:
                raise EvidenceError("failure.json completed_at must include a UTC offset")

        request_hash = content_hash(request)
        if failure:
            completed_at = failure["completed_at"]
            warnings = failure["warnings"]
            limitations = failure["limitations"]
            tested = ["Simulation request contract validation", "Failure package integrity checks"]
            not_tested = ["Simulation execution", "Physical hardware and field validation"]
        else:
            assert result is not None
            completed_at = result["provenance"]["completed_at"]
            warnings = result["warnings"]
            limitations = result["limitations"]
            tested = ["Simulation request/result contract validation", "Evidence package build and integrity metadata"]
            not_tested = ["Physical hardware and field validation"]
            if run_metadata is not None:
                used = result["backend"]
                tested.append(f"{used} output validation")
            else:
                not_tested.append("Simulation backend execution (no runner manifest supplied)")
            if "sionna" not in (result["backend"].lower() if result else ""):
                not_tested.append("Sionna RT")
            if "ns3" not in (result["backend"].lower() if result else "") and "ns-3" not in (result["backend"].lower() if result else ""):
                not_tested.append("ns-3")
        if "Simulation evidence does not establish physical or field validation." not in limitations:
            limitations = [*limitations, "Simulation evidence does not establish physical or field validation."]

        selections = sorted(set(selected_artifacts))
        if len(selections) != len(selected_artifacts):
            raise EvidenceError("duplicate selected artifact")
        if any(name in {"request.json", "result.json", "failure.json", "manifest.json", "summary.json", "report.md"} for name in selections):
            raise EvidenceError("selected artifacts must be distinct from reserved package files")
        payloads: dict[str, tuple[bytes, str]] = {
            "request.json": (_json_bytes(request), "canonical simulation request"),
            "summary.json": (_json_bytes(_summary(request, result, failure)), "derived campaign summary"),
        }
        for name in selections:
            safe = _safe_relative(name)
            if Path(safe.name).suffix.lower() not in _FIGURE_EXTENSIONS:
                raise EvidenceError(f"selected artifacts must be figures: {name}")
            relative = f"plots/{safe.as_posix()}"
            payloads[relative] = (_read_source(root, name, max_bytes=max_artifact_bytes), "explicitly selected figure or artifact")
        rprov = _git_provenance(Path(riose_repo) if riose_repo else None)
        if run_metadata and isinstance(run_metadata.get("riose"), dict):
            rprov["sha"] = run_metadata["riose"].get("revision") or rprov["sha"]
            rprov["dirty"] = run_metadata["riose"].get("dirty", rprov["dirty"])
        if request["provenance"]["riose_revision"] and not rprov["sha"]:
            rprov["sha"] = request["provenance"]["riose_revision"]
        fprov = {"repository": "GUZZBR1/frequencia", "sha": request["provenance"]["frequencia_revision"], "dirty": None}
        if frequencia_repo is not None:
            fprov = _git_provenance(Path(frequencia_repo)) | {"repository": "GUZZBR1/frequencia"}
        if run_metadata and isinstance(run_metadata.get("engine"), dict):
            source_engine = run_metadata["engine"]
            fprov = {"repository": source_engine.get("repository_url", "GUZZBR1/frequencia"),
                     "sha": source_engine.get("actual_sha") or fprov["sha"],
                     "dirty": source_engine.get("dirty", fprov["dirty"])}
        elif request["provenance"]["frequencia_revision"] and not fprov["sha"]:
            fprov["sha"] = request["provenance"]["frequencia_revision"]
        radio = request["radio"]
        backend_lower = request["backend"].lower()
        backend_used = result["backend"] if result else request["backend"]
        engine = {"backend_requested": request["backend"], "backend_used": backend_used,
                  "result_backend": backend_used,
                  "solver": request["solver"], "solver_version": result["solver_version"] if result else None,
                  "ns3_version": None, "capabilities_available": {}, "capabilities_used": {
                      "analytic": "USED" if "analytic" in backend_used.lower() else "NOT_RUN",
                      "sionna_rt": "USED" if "sionna" in backend_used.lower() else "NOT_RUN",
                      "ns3": "USED" if "ns-3" in backend_used.lower() or "ns3" in backend_used.lower() else "NOT_RUN"}}
        if run_metadata and isinstance(run_metadata.get("engine"), dict):
            engine["capabilities_available"] = run_metadata["engine"].get("capabilities", {})
            engine["ns3_version"] = run_metadata["engine"].get("ns3_version")
            engine["solver_version"] = run_metadata["engine"].get("sionna_version", engine["solver_version"])
            network_metadata = run_metadata.get("network")
            if isinstance(network_metadata, dict) and isinstance(network_metadata.get("artifact_sha256"), dict):
                engine["network"] = {"artifact_sha256": network_metadata["artifact_sha256"]}
        binding = (run_metadata.get("parameter_binding") if run_metadata else None)
        if binding is None:
            binding = {"schema_version": "riose.simulation.parameter-binding/v1",
                       "request_sha256": request_hash, "status": "NO_RUN_MANIFEST"}
        if (not isinstance(binding, dict)
                or binding.get("schema_version") != "riose.simulation.parameter-binding/v1"
                or binding.get("request_sha256") != request_hash):
            raise EvidenceError("parameter binding is missing, unsupported, or tied to another request")
        radio_binding = binding.get("radio_and_backend")
        if radio_binding is not None:
            if not isinstance(radio_binding, dict) or set(radio_binding) != {"requested", "effective", "status"}:
                raise EvidenceError("radio/backend parameter binding is malformed")
            expected_requested = {"backend": request["backend"], "seed": request["seed"],
                                  "frequency_hz": radio["frequency_hz"],
                                  "bandwidth_hz": radio["bandwidth_hz"],
                                  "tx_power_dbm": radio["tx_power_dbm"]}
            if radio_binding["requested"] != expected_requested:
                raise EvidenceError("parameter binding requested values differ from the canonical request")
            if radio_binding["status"] not in {"VERIFIED", "REQUEST_SPECIFIC_PARAMETERS_UNSUPPORTED"}:
                raise EvidenceError("radio/backend parameter binding has an unknown status")
            if radio_binding["status"] == "VERIFIED" and radio_binding["effective"] != expected_requested:
                raise EvidenceError("verified effective radio/backend values differ from the request")
            if radio_binding["status"] == "REQUEST_SPECIFIC_PARAMETERS_UNSUPPORTED":
                effective = radio_binding["effective"]
                if (not isinstance(effective, dict) or any(effective.get(key) is not None for key in
                    ("seed", "frequency_hz", "bandwidth_hz", "tx_power_dbm"))):
                    raise EvidenceError("unsupported request parameters must not claim effective values")
        used_parameters: dict[str, Any] = {}
        used_sources: list[str] = []
        if run_metadata:
            if isinstance(radio_binding, dict) and radio_binding.get("status") == "VERIFIED":
                effective = radio_binding["effective"]
                used_parameters.update({key: effective.get(key) for key in
                                        ("seed", "frequency_hz", "bandwidth_hz", "tx_power_dbm")})
                used_sources.append("verified parameter binding")
            if run_metadata.get("output_sha256") is not None:
                summary_bytes = _read_source(root, "outputs/engine/summary.json", max_bytes=max_artifact_bytes)
                if _sha256(summary_bytes) != run_metadata["output_sha256"]:
                    raise EvidenceError("runner engine summary hash mismatch")
                engine_summary = json.loads(summary_bytes.decode("utf-8"),
                                            parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
                if not isinstance(engine_summary, dict):
                    raise EvidenceError("runner engine summary must be an object")
                engine_parameters = engine_summary.get("parameters", {})
                if not isinstance(engine_parameters, dict):
                    raise EvidenceError("runner engine summary parameters must be an object")
                used_parameters.update(engine_parameters)
                used_sources.append("hashed engine summary")
        config_hashes = [ref["sha256"] for ref in request["input_references"]]
        if run_metadata:
            config_hashes.extend(run_metadata.get(key) for key in
                                 ("config_sha256", "trajectory_sha256", "experiment_spec_sha256")
                                 if isinstance(run_metadata.get(key), str))
        manifest: dict[str, Any] = {
            "schema_version": MANIFEST_SCHEMA, "campaign_id": request["campaign_id"],
            "created_at": datetime.now().astimezone().isoformat(), "evidence_status": "SIMULATED",
            "request_hash": request_hash,
            "provenance": {"riose": rprov, "frequencia": fprov,
                           "source_result_sha256": content_hash(result) if result is not None else None,
                           "engine_output_sha256": result["provenance"]["output_sha256"] if result is not None else None,
                           "failure_sha256": content_hash(failure) if failure is not None else None},
            "engine": engine,
            "configuration": {"seed_requested": request["seed"], "seed_used": used_parameters.get("seed"),
                               "frequency_hz_requested": radio["frequency_hz"],
                               "frequency_hz_used": used_parameters.get("frequency_hz"),
                               "bandwidth_hz_requested": radio["bandwidth_hz"],
                               "bandwidth_hz_used": used_parameters.get("bandwidth_hz"),
                               "tx_power_dbm_requested": radio["tx_power_dbm"],
                               "tx_power_dbm_used": used_parameters.get("tx_power_dbm"),
                               "used_configuration_source": ", ".join(dict.fromkeys(used_sources)),
                               "parameter_binding": binding,
                               "network": binding.get("network", {"status": "NOT_AVAILABLE"}),
                               "detector": (binding.get("temporal", {}).get("effective", {}).get("detector")
                                            if isinstance(binding.get("temporal"), dict)
                                            and isinstance(binding["temporal"].get("effective"), dict) else "NOT_AVAILABLE"),
                               "clock_model": (binding.get("temporal", {}).get("effective", {}).get("clocks")
                                               if isinstance(binding.get("temporal"), dict)
                                               and isinstance(binding["temporal"].get("effective"), dict) else "NOT_AVAILABLE"),
                               "localization_method": sorted({row["method"] for row in result["locations"]}) if result else "NOT_RUN",
                               "trajectory_hash": content_hash(request["trajectory"]),
                               "input_hashes": sorted(set(config_hashes))},
            "environment": {"python": platform.python_version(), "os": platform.platform(),
                            "cpu": platform.processor() or "NOT_AVAILABLE", "gpu": "NOT_RECORDED"},
            "execution": {"started_at": run_metadata.get("started_at") if run_metadata else None,
                          "completed_at": run_metadata.get("finished_at", completed_at) if run_metadata else completed_at,
                          "runtime_seconds": run_metadata.get("duration_seconds") if run_metadata else None,
                          "status": "FAILED" if failure else "COMPLETED", "warnings": warnings,
                          "failures": [{"category": failure["error_category"], "message": failure["message"]}] if failure else []},
            "limitations": limitations, "assumptions": [],
            "physical_validation_status": "NOT_VALIDATED",
            "tested": tested, "not_tested": not_tested,
            "outputs": [],
        }
        for name, (data, purpose) in sorted(payloads.items()):
            manifest["outputs"].append({"path": name, "size_bytes": len(data), "sha256": _sha256(data), "purpose": purpose})
        report_bytes = _report(manifest, json.loads(payloads["summary.json"][0])).encode("utf-8")
        payloads["report.md"] = (report_bytes, "human-readable derived report")
        manifest["outputs"].append({"path": "report.md", "size_bytes": len(payloads["report.md"][0]),
                                     "sha256": _sha256(payloads["report.md"][0]), "purpose": "human-readable derived report"})
        manifest["outputs"].sort(key=lambda item: item["path"])
        total = sum(len(data) for data, _ in payloads.values()) + len(_json_bytes(manifest))
        if total > max_package_bytes:
            raise EvidenceError(f"package exceeds size limit ({total} > {max_package_bytes})")

        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
        try:
            for name, (data, _) in payloads.items():
                path = staging.joinpath(*_safe_relative(name).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            (staging / "manifest.json").write_bytes(_json_bytes(manifest))
            result_check = verify_package(staging, max_package_bytes=max_package_bytes)
            if not result_check["valid"]:
                raise EvidenceError("generated package failed verification: " + "; ".join(result_check["errors"]))
            os.rename(staging, target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return manifest
    except EvidenceError:
        raise
    except (ContractError, UnicodeError, json.JSONDecodeError, OSError, ValueError, TypeError) as exc:
        raise EvidenceError(str(exc)) from exc


def verify_package(package: str | Path, *, max_package_bytes: int = DEFAULT_MAX_PACKAGE_BYTES) -> dict[str, Any]:
    """Verify package schemas, identity, output hashes/sizes and path allowlist."""
    errors: list[str] = []
    try:
        root = Path(package).resolve(strict=True)
        if not root.is_dir():
            raise EvidenceError("package must be a directory")
        actual: set[str] = set()
        package_size = 0
        for path in root.rglob("*"):
            if path.is_symlink():
                raise EvidenceError(f"package contains symlink: {path.relative_to(root).as_posix()}")
            if path.is_file():
                actual.add(path.relative_to(root).as_posix())
                package_size += path.stat().st_size
                if package_size > max_package_bytes:
                    raise EvidenceError("package exceeds size limit")
        manifest_path = root / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise EvidenceError("manifest.json is missing or unsafe")
        if manifest_path.stat().st_size > max_package_bytes:
            raise EvidenceError("manifest exceeds package size limit")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        if not isinstance(manifest, dict):
            raise EvidenceError("manifest must be a JSON object")
        if manifest.get("schema_version") != MANIFEST_SCHEMA:
            raise EvidenceError("unsupported manifest schema")
        required_manifest_keys = {"schema_version", "campaign_id", "created_at", "evidence_status", "request_hash",
                                  "provenance", "engine", "configuration", "environment", "execution", "limitations",
                                  "assumptions", "physical_validation_status", "tested", "not_tested", "outputs"}
        if set(manifest) != required_manifest_keys:
            raise EvidenceError("manifest has missing or unsupported fields")
        if manifest.get("evidence_status") != "SIMULATED" or manifest.get("physical_validation_status") != "NOT_VALIDATED":
            raise EvidenceError("evidence classification must remain SIMULATED / NOT_VALIDATED")
        provenance = manifest.get("provenance")
        expected_provenance = {"riose", "frequencia", "source_result_sha256", "engine_output_sha256", "failure_sha256"}
        if not isinstance(provenance, dict) or set(provenance) != expected_provenance:
            raise EvidenceError("manifest provenance is malformed")
        for key in ("source_result_sha256", "engine_output_sha256", "failure_sha256"):
            digest = provenance[key]
            if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                raise EvidenceError(f"manifest provenance {key} is not a SHA-256 digest")
        records = manifest.get("outputs")
        if not isinstance(records, list):
            raise EvidenceError("manifest outputs must be an array")
        listed: dict[str, dict[str, Any]] = {}
        for record in records:
            if not isinstance(record, dict) or set(record) != {"path", "size_bytes", "sha256", "purpose"}:
                raise EvidenceError("malformed output record")
            safe = _safe_relative(record["path"])
            rel = safe.as_posix()
            if rel in listed:
                raise EvidenceError(f"duplicate output path: {rel}")
            if (isinstance(record["size_bytes"], bool) or not isinstance(record["size_bytes"], int)
                    or record["size_bytes"] < 0 or not isinstance(record["sha256"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])):
                raise EvidenceError(f"invalid output size or SHA-256: {rel}")
            if rel not in _REQUIRED and not rel.startswith("plots/"):
                raise EvidenceError(f"output is outside package allowlist: {rel}")
            listed[rel] = record
        if not _REQUIRED.issubset(listed):
            raise EvidenceError("manifest does not include all required outputs")
        if sorted(listed) != [r["path"] for r in records]:
            raise EvidenceError("manifest outputs must be in stable path order")
        if (root / "request.json").is_symlink() or (root / "summary.json").is_symlink() or (root / "report.md").is_symlink():
            raise EvidenceError("required files may not be symlinks")
        request = load_json((root / "request.json").read_text(encoding="utf-8"), kind="request")
        _check_sensitive_value(request)
        summary = json.loads((root / "summary.json").read_text(encoding="utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        if not isinstance(summary, dict):
            raise EvidenceError("summary must be a JSON object")
        if content_hash(request) != manifest.get("request_hash"):
            raise EvidenceError("request hash mismatch")
        if request["campaign_id"] != manifest.get("campaign_id") or summary.get("campaign_id") != manifest.get("campaign_id"):
            raise EvidenceError("campaign identity mismatch")
        if (manifest["engine"].get("backend_requested") != request["backend"]
                or manifest["engine"].get("backend_used") != manifest["engine"].get("result_backend")):
            raise EvidenceError("manifest requested/result backend is inconsistent")
        radio = request["radio"]
        config = manifest["configuration"]
        expected_config_keys = {"seed_requested", "seed_used", "frequency_hz_requested", "frequency_hz_used",
                                "bandwidth_hz_requested", "bandwidth_hz_used", "tx_power_dbm_requested",
                                "tx_power_dbm_used", "used_configuration_source", "network", "detector",
                                "clock_model", "localization_method", "trajectory_hash", "input_hashes",
                                "parameter_binding"}
        if set(config) != expected_config_keys or any(config.get(field) != value for field, value in (
            ("seed_requested", request["seed"]), ("frequency_hz_requested", radio["frequency_hz"]),
            ("bandwidth_hz_requested", radio["bandwidth_hz"]), ("tx_power_dbm_requested", radio["tx_power_dbm"]),
        )):
            raise EvidenceError("manifest configuration differs from request")
        binding = config["parameter_binding"]
        if (not isinstance(binding, dict)
                or binding.get("schema_version") != "riose.simulation.parameter-binding/v1"
                or binding.get("request_sha256") != manifest["request_hash"]):
            raise EvidenceError("manifest parameter binding does not identify the canonical request")
        radio_binding = binding.get("radio_and_backend")
        if radio_binding is not None:
            requested_binding = radio_binding.get("requested") if isinstance(radio_binding, dict) else None
            expected_binding = {"backend": request["backend"], "seed": request["seed"],
                                "frequency_hz": radio["frequency_hz"],
                                "bandwidth_hz": radio["bandwidth_hz"],
                                "tx_power_dbm": radio["tx_power_dbm"]}
            if requested_binding != expected_binding:
                raise EvidenceError("manifest parameter binding requested values differ from request")
            if radio_binding.get("status") == "VERIFIED" and radio_binding.get("effective") != expected_binding:
                raise EvidenceError("manifest verified effective values differ from requested values")
            if radio_binding.get("status") == "REQUEST_SPECIFIC_PARAMETERS_UNSUPPORTED":
                effective = radio_binding.get("effective")
                if not isinstance(effective, dict) or any(effective.get(key) is not None for key in
                    ("seed", "frequency_hz", "bandwidth_hz", "tx_power_dbm")):
                    raise EvidenceError("unsupported parameters claim an effective value")
        trajectory_binding = binding.get("trajectory")
        if trajectory_binding is not None and (
            not isinstance(trajectory_binding, dict)
            or trajectory_binding.get("requested_sha256") != content_hash(request["trajectory"])
            or trajectory_binding.get("status") not in {"VERIFIED", "NOT_BOUND"}
        ):
            raise EvidenceError("manifest trajectory binding differs from the request")
        solver_binding = binding.get("solver")
        if solver_binding is not None:
            requested_solver = solver_binding.get("requested") if isinstance(solver_binding, dict) else None
            request_solver = request["solver"]["parameters"]
            if (not isinstance(requested_solver, dict)
                    or any(request_solver.get(key) != value for key, value in requested_solver.items())
                    or solver_binding.get("status") not in {"VERIFIED", "NOT_BOUND"}):
                raise EvidenceError("manifest solver binding differs from the request")
            if solver_binding["status"] == "VERIFIED":
                effective_solver = solver_binding.get("effective")
                if not isinstance(effective_solver, dict) or any(
                    effective_solver.get(key) != value for key, value in requested_solver.items()
                ):
                    raise EvidenceError("verified effective solver settings differ from the request")
        network_binding = binding.get("network")
        if network_binding is not None:
            if (not isinstance(network_binding, dict)
                    or network_binding.get("requested") != request["solver"]["parameters"].get("network")
                    or network_binding.get("status") not in {"VERIFIED", "NOT_RUN"}):
                raise EvidenceError("manifest network binding differs from the request")
            if network_binding["status"] == "VERIFIED":
                effective_network = network_binding.get("effective")
                requested_network = network_binding["requested"]
                expected_network = {"seed": request["seed"], "frequency_hz": radio["frequency_hz"],
                    "bandwidth_hz": radio["bandwidth_hz"], "tx_power_dbm": radio["tx_power_dbm"],
                    "spreading_factor": requested_network.get("spreading_factor"),
                    "payload_bytes": requested_network.get("payload_bytes"),
                    "traffic_interval_s": requested_network.get("traffic_interval_s")}
                if not isinstance(effective_network, dict) or any(
                    effective_network.get(key) != value for key, value in expected_network.items()
                ):
                    raise EvidenceError("verified effective network settings differ from the request")
        temporal_binding = binding.get("temporal")
        if temporal_binding is not None:
            requested_temporal = request["solver"]["parameters"].get("temporal")
            artifact_hashes = (manifest.get("engine", {}).get("network", {})
                               .get("artifact_sha256", {})
                               if isinstance(temporal_binding, dict)
                               and temporal_binding.get("status") == "VERIFIED" else {})
            _validate_temporal_binding(temporal_binding, requested_temporal, request["seed"], manifest["request_hash"],
                                       manifest.get("run_id"), artifact_hashes)
        if summary.get("schema_version") != SUMMARY_SCHEMA or summary.get("evidence_status") != "SIMULATED":
            raise EvidenceError("unsupported or improperly classified summary")
        if summary.get("status") != manifest.get("execution", {}).get("status"):
            raise EvidenceError("summary status differs from manifest")
        if summary["status"] == "FAILED" and provenance["failure_sha256"] is None:
            raise EvidenceError("failed package is missing its source failure hash")
        if summary["status"] == "COMPLETED" and provenance["source_result_sha256"] is None:
            raise EvidenceError("completed package is missing its source result hash")
        if (root / "report.md").read_text(encoding="utf-8") != _report(manifest, summary):
            raise EvidenceError("report does not match manifest and summary")
        total = 0
        for rel, record in listed.items():
            path = root.joinpath(*_safe_relative(rel).parts)
            if any(part.is_symlink() for part in (path, *path.parents) if part != root.parent):
                raise EvidenceError(f"symlink output is not allowed: {rel}")
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            if not resolved.is_file():
                raise EvidenceError(f"output is not a regular file: {rel}")
            data = resolved.read_bytes()
            total += len(data)
            if len(data) != record["size_bytes"]:
                raise EvidenceError(f"size mismatch: {rel}")
            if _sha256(data) != record["sha256"]:
                raise EvidenceError(f"SHA-256 mismatch: {rel}")
        if total > max_package_bytes:
            raise EvidenceError("package exceeds size limit")
        expected = set(listed) | {"manifest.json"}
        extras = actual - expected
        missing = expected - actual
        if missing:
            raise EvidenceError("missing files: " + ", ".join(sorted(missing)))
        if extras:
            raise EvidenceError("extra files are not allowed: " + ", ".join(sorted(extras)))
        manifest_size = manifest_path.stat().st_size
        if total + manifest_size > max_package_bytes:
            raise EvidenceError("package exceeds size limit")
        return {"valid": True, "evidence_status": "SIMULATED", "artifacts": len(listed),
                "hashes": "PASS", "schema": "PASS", "errors": []}
    except (EvidenceError, ContractError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        errors.append(str(exc))
        return {"valid": False, "evidence_status": None, "artifacts": 0,
                "hashes": "FAIL", "schema": "FAIL", "errors": errors}
