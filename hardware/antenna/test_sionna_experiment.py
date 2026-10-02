import json
import sys
import types

from hardware.antenna import sionna_experiment as experiment


def test_cpu_only_sionna_experiment_writes_skipped_scenario_schema(tmp_path):
    caps = {"GPU_AVAILABLE": False, "GPU_TYPE": "NONE_DETECTED",
            "CUDA_AVAILABLE": False, "SIONNA_AVAILABLE": False,
            "status": "SKIPPED_OPTIONAL"}
    result = experiment.run_experiment(tmp_path, capabilities=caps)
    assert result["schema_version"] == experiment.SCHEMA_VERSION
    assert result["required"] is False
    assert result["status"] == "SKIPPED_OPTIONAL"
    assert [row["scenario"] for row in result["scenarios"]] == list(experiment.SCENARIOS)
    assert all(row["metrics"] is None and row["status"] == "SKIPPED_OPTIONAL"
               for row in result["scenarios"])
    saved = json.loads((tmp_path / "sionna_experiment.json").read_text())
    assert saved["physical_hardware_used"] is False


def test_gpu_capability_runs_builtin_sionna_adapter(tmp_path, monkeypatch):
    caps = {"GPU_AVAILABLE": True, "GPU_TYPE": "test-gpu",
            "CUDA_AVAILABLE": True, "SIONNA_AVAILABLE": True}
    calls = []

    def simulate(**kwargs):
        calls.append(kwargs["scenario"])
        return {
            "status": "COMPLETED",
            "metrics": {"path_count": 1, "tag_receiver_distance_m": 10.0},
            "evidence": {"solver": "Sionna RT PathSolver", "solver_version": "test",
                         "mitsuba_variant": "cuda_ad_mono_polarized", "seed": 42,
                         "deterministic": True, "frequency_hz": 915000000.0,
                         "spec_sha256": None, "obstacle_sha256": None},
        }

    monkeypatch.setitem(sys.modules, "hardware.antenna.sionna_adapter",
                        types.SimpleNamespace(simulate=simulate))
    result = experiment.run_experiment(tmp_path, capabilities=caps, adapter_name="")
    assert result["status"] == "COMPLETED"
    assert calls == list(experiment.SCENARIOS)
    assert all(row["metrics"]["path_count"] == 1 for row in result["scenarios"])


def test_invalid_adapter_completion_is_not_promoted_to_simulated(tmp_path, monkeypatch):
    caps = {"GPU_AVAILABLE": True, "GPU_TYPE": "test-gpu",
            "CUDA_AVAILABLE": True, "SIONNA_AVAILABLE": True}
    bad_adapter = types.SimpleNamespace(simulate=lambda **kwargs: {"status": "COMPLETED"})
    monkeypatch.setitem(sys.modules, "fake_sionna_adapter", bad_adapter)
    result = experiment.run_experiment(tmp_path, capabilities=caps,
                                       adapter_name="fake_sionna_adapter")
    assert result["status"] == "PARTIAL_OR_BLOCKED"
    assert all(row["status"] == "FAILED" and row["metrics"] is None
               for row in result["scenarios"])
