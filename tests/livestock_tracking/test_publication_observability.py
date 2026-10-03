"""Privacy and state-semantics tests for local publication observability."""

from __future__ import annotations

import urllib.request

import pytest
from fastapi.testclient import TestClient

from cattle_rf.api import create_app
from riose.products.livestock_tracking.application.publication_observability import (
    AttemptConditionCounts,
    LifecycleCounts,
    PublicationErrorCode,
    PublicationObservabilityService,
    PublicationObservabilitySnapshot,
)


def test_missing_backend_keeps_counts_unknown_instead_of_zero(tmp_path, monkeypatch):
    def no_network(*_args, **_kwargs):
        raise AssertionError("observability attempted network I/O")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    client = TestClient(create_app(tmp_path / "observe.sqlite3"))
    response = client.get("/api/publication/observability")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["state_available"] is False
    assert body["lifecycle"] is None
    assert body["attempts"] is None
    assert body["retries_total"] is None
    assert "animal_id" not in body and "commitment" not in body


def test_lifecycle_and_attempt_dimensions_remain_separate_and_unknown_counts_stay_null():
    snapshot = PublicationObservabilitySnapshot(
        captured_at=10.0,
        enabled=True,
        state_available=True,
        lifecycle=LifecycleCounts(queued=2, submitted=1, confirmed=None),
        attempts=AttemptConditionCounts(in_flight=1, retry_wait=2, unknown=0, failed=None),
        retries_total=None,
        last_attempt_at=9.0,
        last_observed_success_at=None,
        last_error_code=PublicationErrorCode.RPC_UNAVAILABLE,
    )
    assert snapshot.lifecycle.queued == 2
    assert snapshot.lifecycle.confirmed is None
    assert snapshot.attempts.retry_wait == 2
    assert snapshot.attempts.failed is None
    assert snapshot.last_error_code is PublicationErrorCode.RPC_UNAVAILABLE


def test_unavailable_snapshot_builder_never_infers_success_or_zero_counts():
    snapshot = PublicationObservabilityService().unavailable_snapshot(now=25.0)
    assert snapshot.enabled is False
    assert snapshot.state_available is False
    assert snapshot.lifecycle is None and snapshot.attempts is None
    assert snapshot.retries_total is None
    assert snapshot.last_observed_success_at is None


@pytest.mark.parametrize(
    "factory",
    [
        lambda: LifecycleCounts(queued=-1),
        lambda: AttemptConditionCounts(unknown=True),
        lambda: PublicationObservabilitySnapshot(
            1.0, False, False, LifecycleCounts(confirmed=0), None, None
        ),
        lambda: PublicationObservabilitySnapshot(
            float("nan"), False, False, None, None, None
        ),
        lambda: PublicationObservabilitySnapshot(
            1.0, True, True, None, None, None, last_error_code="secret-token"
        ),
    ],
)
def test_malformed_metrics_and_unallowlisted_errors_are_rejected(factory):
    with pytest.raises(ValueError):
        factory()
