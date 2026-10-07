from cattle_rf.contracts import EvidenceStatus, GroundTruth
from cattle_rf.experimental import simulate_wifi_csi
from cattle_rf.virtual_fence import FenceState, FenceZone, simulate_fence


def test_wifi_csi_is_deterministic_and_marked_experimental():
    first = simulate_wifi_csi(0, "tag-1", "anchor-1", 0.8, seed=12)
    second = simulate_wifi_csi(0, "tag-1", "anchor-1", 0.8, seed=12)
    assert first == second
    assert len(first.amplitude) == len(first.phase_rad) == 32
    assert first.status == EvidenceStatus.EXPERIMENTAL


def test_virtual_fence_only_emits_simulated_audio_or_vibration_cues():
    forbidden = FenceZone("north", "FORBIDDEN_ZONE",
                          ((0, 0), (10, 0), (10, 10), (0, 10)))
    truth = [GroundTruth(0, "tag-1", 12, 5),
             GroundTruth(1, "tag-1", 9, 5),
             GroundTruth(2, "tag-1", 20, 5)]
    events = simulate_fence(truth, [forbidden], warning_distance_m=3)
    assert [event.state for event in events] == [
        FenceState.WARNING, FenceState.SIMULATED_AUDIO_CUE, FenceState.NORMAL]
    assert all(event.status == EvidenceStatus.SIMULATED for event in events)
    assert all("electric" not in event.simulated_response for event in events)
