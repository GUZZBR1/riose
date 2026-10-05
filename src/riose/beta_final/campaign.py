"""Provenance-first runner for the selected RIOSE Beta simulation subset."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from riose.simulation_contract.v1 import canonical_json, content_hash
from riose.simulation_lab.runner import EXPECTED_FREQUENCIA_SHA, RunnerError, doctor, run

from .contract import BetaContractError, load_scenario


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SPEC = ROOT / "docs/research/beta-final/campaign-spec.json"
SCHEMA_PATH = ROOT / "docs/research/beta-final/scenario-contract.schema.json"


class CampaignError(RuntimeError):
    """The campaign cannot start or its evidence fails the Beta gate."""


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            text=True, check=False, timeout=30)
    if result.returncode:
        raise CampaignError(f"git {' '.join(args)} failed: {result.stderr.strip()[:400]}")
    return result.stdout.strip()


def _provenance(root: Path) -> dict[str, Any]:
    revision = _git(root, "rev-parse", "HEAD")
    dirty = bool(_git(root, "status", "--porcelain=v1", "--untracked-files=normal"))
    return {"revision": revision, "dirty": dirty}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def validate_run_evidence(output: dict[str, Any], *, expected_riose: str,
                          expected_frequencia: str) -> None:
    """Reject fixtures, dirty source, revision drift, and missing runtime binding."""
    manifest = output.get("manifest")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "riose.simulation.run-manifest/v1":
        raise CampaignError("run output is missing the V1 runtime manifest")
    riose = manifest.get("riose")
    engine = manifest.get("engine")
    if not isinstance(riose, dict) or riose.get("revision") != expected_riose or riose.get("dirty") is not False:
        raise CampaignError("run is not bound to the clean campaign RIOSE revision")
    if not isinstance(engine, dict) or engine.get("actual_sha") != expected_frequencia or engine.get("dirty") is not False:
        raise CampaignError("run is not bound to the clean pinned FREQUENCIA revision")
    if (manifest.get("evidence_classification") != "SIMULATED"
            or manifest.get("execution_status") not in {None, "COMPLETED"}):
        raise CampaignError("simulation run evidence must remain SIMULATED")
    if not isinstance(manifest.get("request_sha256"), str) or len(manifest["request_sha256"]) != 64:
        raise CampaignError("runtime request hash is missing")
    result = output.get("result")
    if not isinstance(result, dict) or result.get("status") != "SIMULATED":
        raise CampaignError("runtime result is missing or has an invalid evidence classification")
    binding = manifest.get("parameter_binding")
    if not isinstance(binding, dict):
        raise CampaignError("run is missing requested/effective parameter binding")
    for section in ("radio_and_backend", "solver", "trajectory", "network"):
        part = binding.get(section)
        if isinstance(part, dict) and part.get("status") not in {"VERIFIED", "NOT_RUN", "NOT_APPLICABLE"}:
            raise CampaignError(f"run has unverified effective configuration: {section}")
    solver = binding.get("solver")
    if isinstance(solver, dict) and solver.get("status") == "VERIFIED":
        sources = solver.get("effective_sources")
        effective = solver.get("effective")
        if (not isinstance(sources, dict) or not isinstance(effective, dict)
                or set(sources) - set(effective)
                or set(sources.values()) - {"REQUESTED", "UPSTREAM_DEFAULT"}
                or not all(isinstance(solver.get(key), str) and len(solver[key]) == 64
                           for key in ("source_config_sha256", "effective_config_sha256"))):
            raise CampaignError("run does not expose complete effective solver configuration provenance")


def validate_request_alignment(scenario: dict[str, Any], request: dict[str, Any]) -> None:
    """Prevent a scenario contract from silently describing a different run."""
    mappings = request.get("id_mappings", [])
    source_to_target = {(row.get("source_kind"), row.get("source_id")): (row.get("riose_kind"), row.get("riose_id"))
                        for row in mappings if isinstance(row, dict)}
    contract_ids = {(row["animal_id"], row["tag_id"], row["device_id"])
                    for row in scenario["identities"]}
    request_ids = set()
    for tag in request.get("tags", []):
        animal = source_to_target.get(("animal_id", tag.get("animal_ref")))
        device = source_to_target.get(("device_id", tag.get("device_ref")))
        request_ids.add((animal[1] if animal else None, tag.get("tag_ref"),
                         device[1] if device else None))
    if request_ids != contract_ids:
        raise CampaignError("scenario contract identities do not match the simulation request mappings")
    expected_rf = scenario["rf"].get("parameters", {})
    for field in ("frequency_hz", "bandwidth_hz"):
        if field in expected_rf and request.get("radio", {}).get(field) != expected_rf[field]:
            raise CampaignError(f"scenario RF {field} does not match the simulation request")
    network = request.get("solver", {}).get("parameters", {}).get("network")
    expected_network = scenario["network"].get("parameters", {})
    if isinstance(network, dict):
        for field in ("spreading_factor", "payload_bytes", "traffic_interval_s"):
            if field in expected_network and network.get(field) != expected_network[field]:
                raise CampaignError(f"scenario network {field} does not match the simulation request")
    request_tag_by_id = {tag["tag_ref"]: tag for tag in request.get("tags", [])}
    request_trajectory_ids = set()
    for sample in request.get("trajectory", {}).get("samples") or []:
        tag = request_tag_by_id.get(sample.get("tag_ref"))
        if tag is None:
            raise CampaignError("simulation trajectory refers to an undeclared tag")
        animal = source_to_target.get(("animal_id", tag.get("animal_ref")))
        device = source_to_target.get(("device_id", tag.get("device_ref")))
        tag_identity = source_to_target.get(("transmitter_id", tag.get("transmitter_ref")))
        request_trajectory_ids.add((animal[1] if animal else None,
                                    tag_identity[1] if tag_identity else None,
                                    float(sample["timestamp_s"]), tuple(sample["position_m"])))
    declared_trajectory_ids = {(row["animal_id"], row["tag_id"], float(row["timestamp_s"]),
                               tuple(row["position_m"])) for row in scenario["trajectory"]["samples"]}
    if not declared_trajectory_ids.issubset(request_trajectory_ids):
        raise CampaignError("scenario trajectory identity/time/position is not present in the simulation request")


def campaign_digest(document: dict[str, Any]) -> str:
    return content_hash(document)


def build_campaign_manifest(*, campaign: dict[str, Any], scenario_files: list[tuple[Path, dict[str, Any]]],
                            runs: list[dict[str, Any]], riose: dict[str, Any],
                            frequencia: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": "riose.beta.campaign-manifest/v1",
        "campaign_id": campaign["campaign_id"],
        "created_at": _utc_now(),
        "campaign_spec_sha256": campaign_digest(campaign),
        "riose": riose,
        "simulator": {"repository": "GUZZBR1/frequencia", **frequencia},
        "classification": "SIMULATED",
        "scenario_inputs": [
            {"scenario_id": scenario["scenario_id"],
             "path": path.relative_to(ROOT).as_posix(),
             "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
             "classification": scenario["expected_evidence"]}
            for path, scenario in scenario_files
        ],
        "runs": runs,
        "denominator_policy": {
            "scheduled_runs": len(runs),
            "successful_runs": sum(item["status"] == "COMPLETED" for item in runs),
            "failed_runs": sum(item["status"] != "COMPLETED" for item in runs),
            "failures_are_retained": True,
        },
    }
    repeat_groups = []
    for repeat in campaign.get("reproducibility_repeats", []):
        pair = [item for item in runs if item.get("scenario_id") == repeat["scenario_id"]
                and item.get("seed") == repeat["seed"]]
        request_hashes = {item.get("request_sha256") for item in pair}
        output_hashes = {item.get("output_sha256") for item in pair}
        successful = all(item.get("status") == "COMPLETED" for item in pair)
        repeat_groups.append({
            "scenario_id": repeat["scenario_id"], "seed": repeat["seed"],
            "expected_copies": repeat["copies"], "observed_copies": len(pair),
            "same_request": len(request_hashes) == 1 and None not in request_hashes,
            "same_output": len(output_hashes) == 1 and None not in output_hashes,
            "status": "PASS" if successful and len(pair) == repeat["copies"]
                      and len(request_hashes) == 1 and len(output_hashes) == 1
                      else "PARTIAL" if any(item.get("status") == "COMPLETED" for item in pair)
                      else "NOT_READY",
            "runs": [{"run_key": item.get("run_key"), "request_sha256": item.get("request_sha256"),
                      "output_sha256": item.get("output_sha256"), "status": item.get("status")}
                     for item in pair],
        })
    payload["reproducibility"] = repeat_groups
    payload["manifest_sha256"] = content_hash(payload)
    return payload


def run_campaign(spec_path: str | Path = DEFAULT_SPEC, *, repo: str | Path | None = None,
                 output_root: str | Path | None = None, timeout_seconds: float = 300,
                 expected_frequencia_sha: str = EXPECTED_FREQUENCIA_SHA) -> dict[str, Any]:
    spec_file = Path(spec_path).resolve()
    campaign = _read_json(spec_file)
    if campaign.get("schema_version") != "riose.beta.campaign-spec/v1":
        raise CampaignError("unsupported campaign spec version")
    repo_path = Path(repo).expanduser().resolve() if repo else None
    if repo_path is None:
        raise CampaignError("pass an explicit pinned FREQUENCIA --repo checkout")
    riose = _provenance(ROOT)
    frequencia_status = doctor(repo_path, expected_sha=expected_frequencia_sha)
    if riose["dirty"]:
        raise CampaignError("RIOSE checkout must be clean before campaign execution")
    if frequencia_status["status"] != "READY" or frequencia_status["dirty"] is not False:
        raise CampaignError("pinned FREQUENCIA checkout is not clean and READY")
    if frequencia_status["actual_sha"] != expected_frequencia_sha:
        raise CampaignError("FREQUENCIA revision differs from campaign pin")

    scenario_files: list[tuple[Path, dict[str, Any]]] = []
    seen_seeds = campaign.get("seeds")
    if (not isinstance(seen_seeds, list) or not seen_seeds
            or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seen_seeds)
            or len(set(seen_seeds)) != len(seen_seeds)):
        raise CampaignError("campaign seeds must be a non-empty list of distinct non-negative integers")
    scenario_ids = [row.get("scenario_id") for row in campaign.get("scenarios", [])]
    if not scenario_ids or len(set(scenario_ids)) != len(scenario_ids):
        raise CampaignError("campaign scenarios must have unique IDs")
    for row in campaign["scenarios"]:
        path = (ROOT / row["scenario"]).resolve()
        scenario = load_scenario(path)
        if scenario["scenario_id"] != row["scenario_id"]:
            raise CampaignError(f"scenario id mismatch in {path}")
        scenario_files.append((path, scenario))

    run_root = Path(output_root).expanduser().resolve() if output_root else (
        Path.home() / ".cache/riose-beta-final" / campaign["campaign_id"])
    run_root.mkdir(parents=True, exist_ok=True)
    run_records: list[dict[str, Any]] = []
    jobs = [(row, path, scenario, seed, f"{scenario['scenario_id']}-seed-{seed}")
            for row, (path, scenario) in zip(campaign["scenarios"], scenario_files, strict=True)
            for seed in campaign["seeds"]]
    for repeat in campaign.get("reproducibility_repeats", []):
        matching = [(row, path, scenario) for row, (path, scenario) in
                    zip(campaign["scenarios"], scenario_files, strict=True)
                    if scenario["scenario_id"] == repeat.get("scenario_id")]
        if (len(matching) != 1 or repeat.get("seed") not in campaign["seeds"]
                or isinstance(repeat.get("copies"), bool) or not isinstance(repeat.get("copies"), int)
                or repeat["copies"] < 2):
            raise CampaignError("invalid reproducibility repeat specification")
        row, path, scenario = matching[0]
        jobs.extend((row, path, scenario, repeat["seed"],
                     f"{scenario['scenario_id']}-seed-{repeat['seed']}-repeat-{index}")
                    for index in range(1, repeat["copies"]))
    total = len(jobs)
    request_paths: dict[tuple[str, int], Path] = {}
    for row, source_path, scenario, seed, run_key in jobs:
        del source_path
        cache_key = (scenario["scenario_id"], seed)
        request_path = request_paths.get(cache_key)
        if request_path is None:
            template = _read_json((ROOT / row["request_template"]).resolve())
            request = json.loads(json.dumps(template))
            request["campaign_id"] = campaign["campaign_id"]
            request["scenario_id"] = scenario["scenario_id"]
            request["seed"] = seed
            request["expected_evidence"] = "SIMULATED"
            request["provenance"] = {
                "riose_revision": riose["revision"],
                "frequencia_revision": frequencia_status["actual_sha"],
                "dirty": False,
                "created_at": _utc_now(),
            }
            validate_request_alignment(scenario, request)
            request_path = run_root / "requests" / f"{scenario['scenario_id']}-seed-{seed}.json"
            _write_json(request_path, request)
            request_paths[cache_key] = request_path
        try:
            output = run(request_path, repo=repo_path,
                         expected_sha=expected_frequencia_sha,
                         output_root=run_root / "workspaces",
                         timeout_seconds=timeout_seconds,
                         allow_dirty=False)
            validate_run_evidence(output, expected_riose=riose["revision"],
                                  expected_frequencia=expected_frequencia_sha)
            run_manifest = output["manifest"]
            summary_path = Path(output["workspace"]) / "summary.md"
            result_path = Path(output["workspace"]) / "result" / "result.json"
            network_path = Path(output["workspace"]) / "network" / "summary.json"
            score_path = Path(output["workspace"]) / "network" / "scoring.json"
            artifacts = {}
            for name, path in (("summary", summary_path), ("result", result_path),
                               ("network", network_path), ("scoring", score_path)):
                if path.is_file():
                    artifacts[name] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            run_records.append({
                "run_key": run_key, "run_id": run_manifest.get("run_id"),
                "scenario_id": scenario["scenario_id"], "seed": seed,
                "status": "COMPLETED", "classification": "SIMULATED",
                "workspace": str(output["workspace"]),
                "manifest_sha256": content_hash(run_manifest),
                "request_sha256": run_manifest.get("request_sha256"),
                "output_sha256": run_manifest.get("output_sha256"),
                "parameter_binding": run_manifest.get("parameter_binding"),
                "metrics": run_manifest.get("metrics"),
                "artifacts": artifacts,
            })
        except Exception as exc:
            run_records.append({"run_key": run_key, "scenario_id": scenario["scenario_id"],
                                "seed": seed, "status": "FAILED", "classification": "SIMULATED",
                                "error": f"{type(exc).__name__}: {exc}"})

    manifest = build_campaign_manifest(campaign=campaign, scenario_files=scenario_files,
                                        runs=run_records, riose=riose,
                                        frequencia={"revision": frequencia_status["actual_sha"],
                                                    "dirty": False, "capabilities": frequencia_status["capabilities"]})
    manifest_path = run_root / "campaign-manifest.json"
    _write_json(manifest_path, manifest)
    summary = {"status": "COMPLETED" if all(item["status"] == "COMPLETED" for item in run_records)
               else "PARTIAL", "manifest_path": str(manifest_path), "manifest": manifest,
               "scheduled_runs": total, "completed_runs": manifest["denominator_policy"]["successful_runs"],
               "failed_runs": manifest["denominator_policy"]["failed_runs"]}
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m riose.beta_final.campaign")
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--repo", type=Path, required=True, help="clean FREQUENCIA checkout at the declared SHA")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--expected-frequencia-sha", default=EXPECTED_FREQUENCIA_SHA)
    args = parser.parse_args(argv)
    try:
        result = run_campaign(args.spec, repo=args.repo, output_root=args.output_root,
                              timeout_seconds=args.timeout,
                              expected_frequencia_sha=args.expected_frequencia_sha)
    except (CampaignError, BetaContractError, RunnerError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["status"] == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
