"""Durable retry scheduling stays bounded and leaves ambiguous states explicit."""

import pytest

from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.adapters.persistence.publication_outbox import SQLitePublicationOutbox
from riose.products.livestock_tracking.domain.publication_retry import PublicationRetryPolicy


def _request(path, policy):
    store = Store(path)
    store.create_animal("cow", "tag", "secret")
    event = store.append_animal_event("cow", "WEIGHT_RECORDED", {"weight_kg": 420}, 1)
    outbox = SQLitePublicationOutbox(store, retry_policy=policy, jitter_source=lambda: 0.5)
    request = outbox.enqueue_event(
        event.event_id,
        chain="base",
        destination="evm-registry",
        network="base-test-network",
    )
    return store, outbox, request


def test_retry_policy_uses_exponential_backoff_with_bounded_jitter():
    policy = PublicationRetryPolicy(
        max_retries=4, initial_delay_s=10, max_delay_s=30, jitter_ratio=0.2,
    )

    assert policy.delay(1, 0) == 8
    assert policy.delay(2, 1) == pytest.approx(24)
    assert policy.delay(3, 1) == 30


def test_retry_schedule_survives_reopen_and_is_not_claimable_early(tmp_path):
    policy = PublicationRetryPolicy(
        max_retries=4, initial_delay_s=10, max_delay_s=40, jitter_ratio=0,
    )
    db = tmp_path / "retry.sqlite3"
    store, outbox, request = _request(db, policy)
    token = outbox.claim_processing(request["publication_id"], force=True)
    assert token is not None
    deferred = outbox.defer_retry(
        request["publication_id"], failure_class="TRANSIENT_PRE_SUBMISSION",
        reason_code="TARGET_UNAVAILABLE", claim_token=token, now=100,
    )
    assert (deferred["retry_count"], deferred["available_at"]) == (1, 110)
    assert deferred["last_failure_class"] == "TRANSIENT_PRE_SUBMISSION"
    assert deferred["last_failure_code"] == "TARGET_UNAVAILABLE"
    outbox.release_processing(request["publication_id"], token)
    store.close()

    reopened = Store(db)
    try:
        recovered = SQLitePublicationOutbox(
            reopened, retry_policy=policy, jitter_source=lambda: 0.5,
        )
        assert recovered.get(request["publication_id"])["retry_count"] == 1
        assert recovered.claim_processing(request["publication_id"], now=109) is None
        assert recovered.claim_processing(request["publication_id"], now=110) is not None
    finally:
        reopened.close()


def test_retry_exhaustion_stops_as_manual_intervention_not_false_failure(tmp_path):
    policy = PublicationRetryPolicy(
        max_retries=2, initial_delay_s=1, max_delay_s=2, jitter_ratio=0,
    )
    store, outbox, request = _request(tmp_path / "bounded.sqlite3", policy)
    publication_id = request["publication_id"]
    try:
        for timestamp in (100, 102):
            token = outbox.claim_processing(publication_id, force=True)
            assert token is not None
            result = outbox.defer_retry(
                publication_id, failure_class="AMBIGUOUS_SUBMISSION",
                reason_code="SUBMIT_AMBIGUOUS", claim_token=token, now=timestamp,
            )
            outbox.release_processing(publication_id, token)

        assert result["retry_count"] == 2
        token = outbox.claim_processing(publication_id, force=True)
        stopped = outbox.defer_retry(
            publication_id, failure_class="AMBIGUOUS_SUBMISSION",
            reason_code="SUBMIT_AMBIGUOUS", claim_token=token, now=104,
        )
        assert stopped["status"] == "MANUAL_INTERVENTION"
        assert stopped["last_failure_code"] == "RETRY_LIMIT_REACHED"
        assert stopped["completed_at"] is not None
        assert stopped["status"] != "REJECTED"
        assert outbox.claim_processing(publication_id, force=True) is None
    finally:
        store.close()
