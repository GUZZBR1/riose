from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/run_rf_realism_campaign.py"
SPEC = importlib.util.spec_from_file_location("rf_campaign", SCRIPT)
assert SPEC and SPEC.loader
campaign = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(campaign)


def test_direct_path_wall_intersection_uses_segment_and_wall_bounds():
    assert campaign.segment_crosses_wall((200, 500, 1.5), (800, 500, 8))
    assert campaign.segment_crosses_wall((200, 500, 1.5), (800, 350, 8))
    assert not campaign.segment_crosses_wall((200, 500, 1.5), (800, 100, 8))
    assert not campaign.segment_crosses_wall((200, 500, 1.5), (400, 500, 8))


def test_geometric_nlos_classification_requires_blocked_direct_path_received_power_and_interaction():
    reflected_path = {"interactions": [{"type": "specular", "vertex_m": [500, 300, 8]}]}
    geometry = {"tx": (200, 500, 8), "rx": (800, 500, 8), "reflector_y_m": 300}
    assert campaign.classify_geometric_path(True, "NLOS", -77.7, [reflected_path], **geometry) == (
        "GEOMETRIC_NLOS_WITH_RECEIVED_PATH")
    assert campaign.classify_geometric_path(True, "NLOS", -77.7, [], **geometry) == "UNPROVEN"
    assert campaign.classify_geometric_path(True, "NLOS", None, [reflected_path], **geometry) == "UNPROVEN"
    invalid_reflection = {"interactions": [{"type": "specular", "vertex_m": [500, 450, 8]}]}
    assert campaign.classify_geometric_path(
        True, "NLOS", -77.7, [invalid_reflection], **geometry) == "UNPROVEN"
    bounce_on_blocker = {"interactions": [{"type": "specular", "vertex_m": [500, 550, 8]}]}
    assert campaign.classify_geometric_path(
        True, "NLOS", -77.7, [bounce_on_blocker], tx=(200, 500, 8),
        rx=(800, 500, 8), reflector_y_m=550) == "UNPROVEN"
    assert campaign.classify_geometric_path(False, "LOS", -68.3, []) == "LOS_RECEIVED"


def test_no_path_remains_a_distinct_state_without_imputed_power():
    assert campaign.classify_geometric_path(True, "NO_PATH", None, []) == "NO_PATH"


def test_percentile_summary_is_interpolated_and_empty_is_explicit():
    assert campaign.stats([0.0, 10.0]) == {
        "min": 0.0, "p10": 1.0, "p50": 5.0, "mean": 5.0,
        "p90": 9.0, "p95": 9.5, "max": 10.0,
    }
    assert all(value is None for value in campaign.stats([]).values())
