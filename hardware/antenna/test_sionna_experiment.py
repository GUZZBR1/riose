import json

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


def test_gpu_capability_without_adapter_does_not_invent_result(tmp_path):
    caps = {"GPU_AVAILABLE": True, "GPU_TYPE": "test-gpu",
            "CUDA_AVAILABLE": True, "SIONNA_AVAILABLE": True}
    result = experiment.run_experiment(tmp_path, capabilities=caps, adapter_name="")
    assert result["status"] == "PARTIAL_OR_BLOCKED"
    assert all(row["status"] == "NOT_AVAILABLE" and row["metrics"] is None
               for row in result["scenarios"])
