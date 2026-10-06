from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from riose.simulation_contract import content_hash
from riose.simulation_contract.v1 import REQUEST_SCHEMA
from riose.simulation_lab import RunnerError, doctor, run
from riose.simulation_lab.runner import FREQUENCIA_URL


def make_request(**overrides):
    value = {
        "schema_version": REQUEST_SCHEMA, "campaign_id": "campaign smoke", "scenario_id": "scenario-1",
        "seed": 11, "backend": "analytic", "coordinate_frame": "ENU_LOCAL",
        "units": {"position": "m", "timestamp": "s", "frequency": "Hz", "bandwidth": "Hz",
                  "power": "dBm", "delay": "s", "phase": "rad"},
        "tags": [{"tag_ref": "tag-1", "transmitter_ref": "tx-1", "position_m": [1, 2, 3], "trajectory_ref": None}],
        "receivers": [{"receiver_ref": "rx-1", "anchor_ref": "anchor-1", "position_m": [4, 5, 6]}],
        "id_mappings": [
            {"source_system": "frequencia", "source_kind": "transmitter_id", "source_id": "tx-1",
             "riose_kind": "tag_id", "riose_id": "tag-1"},
            {"source_system": "frequencia", "source_kind": "receiver_id", "source_id": "rx-1",
             "riose_kind": "anchor_id", "riose_id": "anchor-1"},
        ], "trajectory": {"samples": [{"tag_ref": "tag-1", "timestamp_s": 0,
                                                           "position_m": [1, 2, 3]}], "reference": None},
        "radio": {"frequency_hz": 915000000, "bandwidth_hz": 125000, "tx_power_dbm": 14, "phy": {}},
        "solver": {"parameters": {}}, "input_references": [],
        "provenance": {"riose_revision": None, "frequencia_revision": None,
                       "dirty": False, "created_at": "2026-10-03T00:00:00Z"},
        "expected_evidence": "SIMULATED",
    }
    value.update(overrides)
    return value


def write_request(path: Path, value=None):
    path.write_text(json.dumps(value or make_request()), encoding="utf-8")
    return path


def make_engine(tmp_path: Path, *, source: str | None = None, remote: str = FREQUENCIA_URL) -> tuple[Path, str]:
    repo = tmp_path / "frequencia engine with spaces"
    (repo / "experiments" / "farm_rf").mkdir(parents=True)
    script = source or """import json, pathlib, sys
out = pathlib.Path(sys.argv[sys.argv.index('--output-dir') + 1])
out.mkdir(parents=True, exist_ok=True)
(out / 'summary.json').write_text(json.dumps({'classification': 'SIMULAÇÃO', 'backend': 'analytic_free_space_plus_flat_ground_reflection'}), encoding='utf-8')
print('analytic smoke complete')
"""
    entry = repo / "experiments" / "farm_rf" / "run_experiment.py"
    entry.write_text(script, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "RIOSE tests"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "tests@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", remote], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "Add analytic entrypoint fixture"], check=True)
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                         capture_output=True, text=True).stdout.strip()
    return repo, sha


def test_doctor_reports_repository_identity_sha_dirty_and_individual_capabilities(tmp_path):
    repo, sha = make_engine(tmp_path)
    report = doctor(repo, expected_sha=sha)
    assert report["status"] == "READY"
    assert report["remote_matches"] and report["actual_sha"] == sha and report["dirty"] is False
    assert report["capabilities"]["analytic"] == "AVAILABLE"
    assert set(report["capabilities"]) >= {"core_python", "analytic", "sionna_rt", "ns3", "lorawan", "gpu"}
    (repo / "local.txt").write_text("preserve me", encoding="utf-8")
    dirty = doctor(repo, expected_sha=sha)
    assert dirty["dirty"] is True and dirty["status"] == "BLOCKED"
    assert (repo / "local.txt").read_text(encoding="utf-8") == "preserve me"


@pytest.mark.parametrize("path,remote", [("absent", FREQUENCIA_URL), ("not-git", FREQUENCIA_URL),
                                          ("valid", "https://github.com/someone/else.git")])
def test_doctor_fails_closed_for_missing_non_git_and_wrong_repository(tmp_path, path, remote):
    target = tmp_path / path
    if path == "valid":
        repo, sha = make_engine(tmp_path, remote=remote)
    else:
        sha = "a" * 40
        if path == "not-git":
            target.mkdir()
    report = doctor(target, expected_sha=sha)
    assert report["status"] == "BLOCKED"


def test_run_dry_run_validates_pin_and_writes_a_plan_without_running_engine(tmp_path):
    repo, sha = make_engine(tmp_path)
    request = write_request(tmp_path / "request file.json")
    result = run(request, repo=repo, expected_sha=sha, output_root=tmp_path / "runs with spaces", dry_run=True)
    workspace = Path(result["workspace"])
    assert result["status"] == "PLANNED" and result["result"] is None
    assert result["manifest"]["backend_used"] is None and result["manifest"]["exit_code"] is None
    assert not (workspace / "outputs").exists()
    assert json.loads((workspace / "manifest.json").read_text())["request_sha256"] == content_hash(make_request())


def test_run_executes_real_process_boundary_and_records_simulated_v1_provenance(tmp_path):
    repo, sha = make_engine(tmp_path)
    request = write_request(tmp_path / "request.json")
    before = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], check=True,
                            capture_output=True, text=True).stdout
    result = run(request, repo=repo, expected_sha=sha, output_root=tmp_path / "runs")
    workspace = Path(result["workspace"])
    manifest = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
    v1_result = json.loads((workspace / "result" / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "SIMULATED" and manifest["exit_code"] == 0
    assert manifest["backend_requested"] == "analytic" and manifest["backend_used"] == "frequencia.analytic"
    assert manifest["engine"]["actual_sha"] == sha and manifest["engine"]["dirty"] is False
    binding = manifest["parameter_binding"]
    assert binding["radio_and_backend"]["status"] == "REQUEST_SPECIFIC_PARAMETERS_UNSUPPORTED"
    assert binding["radio_and_backend"]["requested"]["seed"] == 11
    assert binding["radio_and_backend"]["effective"]["seed"] is None
    assert binding["trajectory"]["status"] == "NOT_BOUND"
    assert v1_result["status"] == "SIMULATED" and v1_result["observations"] == []
    assert v1_result["provenance"]["request_sha256"] == content_hash(make_request())
    assert manifest["command"][0] == sys.executable and "--backend" in manifest["command"]
    assert (workspace / "logs" / "stdout.log").is_file()
    after = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], check=True,
                           capture_output=True, text=True).stdout
    assert after == before


def test_request_strings_never_become_shell_commands(tmp_path):
    repo, sha = make_engine(tmp_path)
    marker = tmp_path / "owned.txt"
    malicious = make_request(campaign_id=f"x & echo injected > {marker}")
    request = write_request(tmp_path / "malicious.json", malicious)
    run(request, repo=repo, expected_sha=sha, output_root=tmp_path / "runs")
    assert not marker.exists()


def test_mismatched_sha_dirty_checkout_and_remote_are_rejected_without_checkout_mutation(tmp_path):
    repo, sha = make_engine(tmp_path)
    request = write_request(tmp_path / "request.json")
    with pytest.raises(RunnerError, match="expected commit SHA"):
        run(request, repo=repo, expected_sha="0" * 40, output_root=tmp_path / "runs")
    (repo / "work.txt").write_text("existing work", encoding="utf-8")
    with pytest.raises(RunnerError, match="dirty"):
        run(request, repo=repo, expected_sha=sha, output_root=tmp_path / "runs")
    assert (repo / "work.txt").exists()
    subprocess.run(["git", "-C", str(repo), "remote", "set-url", "origin", "https://github.com/someone/else.git"], check=True)
    with pytest.raises(RunnerError, match="remote"):
        run(request, repo=repo, expected_sha=sha, output_root=tmp_path / "runs", allow_dirty=True)


def test_symlinked_engine_entrypoint_is_not_executed(tmp_path):
    repo, sha = make_engine(tmp_path)
    entrypoint = repo / "experiments" / "farm_rf" / "run_experiment.py"
    outside = tmp_path / "outside.py"
    outside.write_text("raise SystemExit(99)\n", encoding="utf-8")
    entrypoint.unlink()
    entrypoint.symlink_to(outside)
    report = doctor(repo, expected_sha=sha)
    assert report["status"] == "BLOCKED" and not report["entrypoint_available"]


@pytest.mark.parametrize("source,match", [
    ("import sys; sys.exit(7)\n", "exited with code 7"),
    ("pass\n", "did not produce summary.json"),
    ("import pathlib,sys; p=pathlib.Path(sys.argv[sys.argv.index('--output-dir')+1]); p.mkdir(parents=True); (p/'summary.json').write_text('{bad')\n", "malformed"),
    ("import time; time.sleep(3)\n", "timed out"),
    ("import sys; sys.stdout.write('X' * 3000000); sys.stdout.flush()\n", "output exceeded"),
])
def test_process_failure_output_timeout_and_malformed_response_are_structured(tmp_path, source, match):
    repo, sha = make_engine(tmp_path, source=source)
    request = write_request(tmp_path / "request.json")
    with pytest.raises(RunnerError, match=match) as failure:
        run(request, repo=repo, expected_sha=sha, output_root=tmp_path / "runs", timeout_seconds=0.2)
    manifest_path = Path(str(failure.value).split("manifest: ", 1)[1])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["execution_status"] == "FAILED"
    assert manifest["error"] and manifest["backend_used"] is None


def test_generated_output_size_is_limited(tmp_path):
    source = "import pathlib, sys, time\nout = pathlib.Path(sys.argv[sys.argv.index('--output-dir') + 1]); out.mkdir(parents=True)\nwith (out / 'oversized.bin').open('wb') as f: f.truncate(257 * 1024 * 1024)\ntime.sleep(2)\n"
    repo, sha = make_engine(tmp_path, source=source)
    request = write_request(tmp_path / "request.json")
    with pytest.raises(RunnerError, match="workspace limit"):
        run(request, repo=repo, expected_sha=sha, output_root=tmp_path / "runs", timeout_seconds=3)


def test_unavailable_backend_does_not_silently_fallback(tmp_path):
    repo, sha = make_engine(tmp_path)
    value = make_request(backend="sionna-rt")
    request = write_request(tmp_path / "request.json", value)
    with pytest.raises(RunnerError, match="ExperimentSpec runner is unavailable"):
        run(request, repo=repo, expected_sha=sha, output_root=tmp_path / "runs")


def test_duplicate_or_parallel_invocations_get_isolated_workspaces(tmp_path):
    repo, sha = make_engine(tmp_path)
    request = write_request(tmp_path / "request.json")
    root = tmp_path / "runs"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(request, repo=repo, expected_sha=sha, output_root=root), range(2)))
    assert results[0]["run_id"] != results[1]["run_id"]
    assert len({result["workspace"] for result in results}) == 2
