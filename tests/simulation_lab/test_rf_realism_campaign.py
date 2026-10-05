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


def test_percentile_summary_is_interpolated_and_empty_is_explicit():
    assert campaign.stats([0.0, 10.0]) == {
        "min": 0.0, "p10": 1.0, "p50": 5.0, "mean": 5.0,
        "p90": 9.0, "p95": 9.5, "max": 10.0,
    }
    assert all(value is None for value in campaign.stats([]).values())
