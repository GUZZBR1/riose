import json
import sys
import types

from hardware.antenna import sionna_experiment as experiment
from hardware.antenna import sionna_adapter as adapter


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
            "metrics": {"path_count": 1, "tag_receiver_distance_m": 10.0,
                        "summed_path_coefficient_power_linear": 0.25},
            "evidence": {"solver": "Sionna RT PathSolver", "solver_version": "test",
                         "mitsuba_variant": "cuda_ad_mono_polarized", "seed": 42,
                         "deterministic": True, "frequency_hz": 915000000.0,
                         "spec_sha256": None, "obstacle_sha256": None},
        }

    monkeypatch.setattr(adapter, "simulate", simulate)
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


def test_obstacle_scene_uses_scene_object_position_property(tmp_path, monkeypatch):
    class FakeScene:
        def __init__(self):
            self.items = []

        def add(self, item):
            self.items.extend(item if isinstance(item, list) else [item])

    class FakeSceneObject:
        def __init__(self, *, fname, name, radio_material):
            self.fname = fname
            self.name = name
            self.radio_material = radio_material

    class FakePathSolver:
        def __init__(self, *, deterministic):
            assert deterministic is True

        def __call__(self, scene, **kwargs):
            assert kwargs["seed"] == 42
            tensor = lambda values: types.SimpleNamespace(numpy=lambda: values)
            return types.SimpleNamespace(
                interactions=types.SimpleNamespace(shape=(1, 1, 1, 1, 1, 2)),
                a=(tensor([0.3, 0.4]), tensor([0.0, 0.0])),
            )

    fake_scene = FakeScene()
    fake_rt = types.ModuleType("sionna.rt")
    fake_rt.PathSolver = FakePathSolver
    fake_rt.PlanarArray = lambda **kwargs: kwargs
    fake_rt.RadioMaterial = lambda **kwargs: kwargs
    fake_rt.Receiver = lambda **kwargs: types.SimpleNamespace(**kwargs)
    fake_rt.SceneObject = FakeSceneObject
    fake_rt.Transmitter = lambda **kwargs: types.SimpleNamespace(**kwargs)
    fake_rt.load_scene = lambda: fake_scene
    fake_sionna = types.ModuleType("sionna")
    fake_sionna.__path__ = []
    fake_mitsuba = types.SimpleNamespace(Point3f=lambda *values: values,
                                         variant=lambda: "cuda_ad_mono_polarized")
    monkeypatch.setitem(sys.modules, "sionna", fake_sionna)
    monkeypatch.setitem(sys.modules, "sionna.rt", fake_rt)
    monkeypatch.setitem(sys.modules, "mitsuba", fake_mitsuba)

    output = tmp_path / "scenarios"
    result = adapter.simulate(scenario="TAG_TO_RECEIVER_WITH_OBSTACLE",
                              spec_path=None, output_dir=output)
    obstacle = next(item for item in fake_scene.items if isinstance(item, FakeSceneObject))
    assert obstacle.position == (5.0, 0.0, 1.5)
    assert result["metrics"]["path_count"] == 2
    assert result["metrics"]["summed_path_coefficient_power_linear"] == 0.25
    assert (output / "obstacle.obj").is_file()
    assert (output / "tag_to_receiver_with_obstacle.json").is_file()
