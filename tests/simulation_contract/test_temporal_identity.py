import pytest

from riose.simulation_contract.temporal_identity import RequestState, RequestTimeline


def test_timelines_attribute_overlapping_requests_by_identity_not_order():
    first = RequestTimeline(
        run_id="run-1", request_id="req-a", state=RequestState.RECEIVED,
        requested_at_s=1.0, scheduled_at_s=3.0, transmitted_at_s=3.2,
        received_at_s=3.3, packet_id="packet-a", sequence_id="seq-7",
    )
    second = RequestTimeline(
        run_id="run-1", request_id="req-b", state=RequestState.RECEIVED,
        requested_at_s=2.0, scheduled_at_s=2.5, transmitted_at_s=2.6,
        received_at_s=2.7, packet_id="packet-b", sequence_id="seq-8",
    )
    # The second request completes first; request IDs preserve attribution.
    assert second.received_at_s < first.received_at_s
    assert first.request_id != second.request_id
    assert first.packet_id != second.packet_id


def test_created_and_superseded_are_distinct_from_transmit_outcomes():
    created = RequestTimeline(
        run_id="run-1", request_id="req-new", state=RequestState.CREATED,
        requested_at_s=10.0,
    )
    superseded = RequestTimeline(
        run_id="run-1", request_id="req-old", state=RequestState.SUPERSEDED,
        requested_at_s=9.0, superseded_by_request_id="req-new",
    )
    assert created.transmitted_at_s is None
    assert superseded.superseded_by_request_id == created.request_id


@pytest.mark.parametrize("updates", [
    {"transmitted_at_s": 2.0, "packet_id": "packet-a"},
    {"state": RequestState.RECEIVED, "scheduled_at_s": 2.0,
     "transmitted_at_s": 3.0, "received_at_s": 2.9, "packet_id": "packet-a"},
    {"state": RequestState.SUPERSEDED},
    {"state": RequestState.SUPERSEDED, "superseded_by_request_id": "req-1"},
    {"requested_at_s": float("nan")},
    {"state": "RECEIVED"},
])
def test_invalid_milestone_or_identity_is_rejected(updates):
    values = dict(run_id="run-1", request_id="req-1", state=RequestState.CREATED,
                  requested_at_s=1.0)
    values.update(updates)
    with pytest.raises((TypeError, ValueError)):
        RequestTimeline(**values)
