"""Offline contract tests for generic publication dispatch and reconciliation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Event
import time

import pytest

from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.adapters.persistence.publication_outbox import SQLitePublicationOutbox
from riose.products.livestock_tracking.application.publication_dispatcher import PublicationDispatcher
from riose.products.livestock_tracking.domain.publication import ChainReceipt, PreparedPublication


@dataclass
class FakeAdapter:
    adapter_id: str = "fake-rpc"
    chain: str = "base"
    network: str = "local-testnet"
    transaction_id: str = "0x" + "ab" * 32
    payload: bytes = b"prepared-publication"
    receipt: ChainReceipt | None = None
    verification: bool | None = True
    submit_error: Exception | None = None
    receipt_error: Exception | None = None
    calls: list[tuple] = field(default_factory=list)
    outbox: SQLitePublicationOutbox | None = None
    publication_id: str | None = None

    def healthcheck(self) -> bool:
        self.calls.append(("healthcheck",))
        return True

    def prepare(self, commitment):
        self.calls.append(("prepare", commitment))
        return PreparedPublication(self.transaction_id, self.payload, {"test": True})

    def validate_prepared(self, prepared, commitment) -> None:
        self.calls.append(("validate_prepared", prepared, commitment))
        if prepared.transaction_id != self.transaction_id or prepared.payload != self.payload:
            raise ValueError("persisted payload mismatch")

    def submit(self, prepared) -> str:
        self.calls.append(("submit", prepared))
        if self.outbox is not None:
            persisted = self.outbox.latest_attempt(self.publication_id)
            assert persisted is not None, "submit occurred before durable attempt"
            assert persisted["transaction_id"] == prepared.transaction_id
            assert persisted["payload"] == prepared.payload
        if self.submit_error is not None:
            raise self.submit_error
        return prepared.transaction_id

    def get_receipt(self, transaction_id, commitment):
        self.calls.append(("get_receipt", transaction_id, commitment))
        if self.receipt_error is not None:
            raise self.receipt_error
        return self.receipt

    def verify(self, commitment, receipt):
        self.calls.append(("verify", commitment, receipt))
        return self.verification


@pytest.fixture
def publication(tmp_path):
    store = Store(tmp_path / "dispatcher.sqlite3")
    store.create_animal("cow-1", "tag-1", "crypto-1")
    event = store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"weight_kg": 421}, 10.0)
    outbox = SQLitePublicationOutbox(store)
    request = outbox.enqueue_event(
        event.event_id, chain="base", destination="fake-rpc", network="local-testnet"
    )
    try:
        yield store, outbox, event, request
    finally:
        store.close()


def _dispatcher(outbox, adapter, publication_id):
    adapter.outbox = outbox
    adapter.publication_id = publication_id
    return PublicationDispatcher(outbox, [adapter])


def _receipt(adapter, status="CONFIRMED", **changes):
    fields = {
        "chain": adapter.chain,
        "network": adapter.network,
        "transaction_id": adapter.transaction_id,
        "status": status,
        "block_ref": "12345",
        "evidence_status": "ASSUMED",
    }
    fields.update(changes)
    return ChainReceipt(**fields)


def test_process_routes_target_and_persists_exact_payload_before_submit(publication):
    _store, outbox, _event, request = publication
    original_envelope = request["envelope"]
    original_commitment = request["commitment"]
    adapter = FakeAdapter()
    dispatcher = _dispatcher(outbox, adapter, request["publication_id"])

    result = dispatcher.process(request["publication_id"])

    assert result["status"] == "RPC_ACCEPTED"
    assert [call[0] for call in adapter.calls].count("prepare") == 1
    assert [call[0] for call in adapter.calls].count("submit") == 1
    attempt = outbox.latest_attempt(request["publication_id"])
    assert attempt["attempt_number"] == 1
    assert attempt["adapter_id"] == adapter.adapter_id
    assert attempt["transaction_id"] == adapter.transaction_id
    assert attempt["payload"] == adapter.payload
    assert next(call[1] for call in adapter.calls if call[0] == "prepare").commitment == original_commitment
    assert outbox.get(request["publication_id"])["envelope"] == original_envelope
    assert outbox.verify_local_binding(request["publication_id"])


def test_repeated_process_does_not_prepare_a_second_transaction(publication):
    _store, outbox, _event, request = publication
    adapter = FakeAdapter()
    dispatcher = _dispatcher(outbox, adapter, request["publication_id"])
    dispatcher.process(request["publication_id"])

    dispatcher.process(request["publication_id"])

    assert [call[0] for call in adapter.calls].count("prepare") == 1
    assert outbox.latest_attempt(request["publication_id"])["attempt_number"] == 1


def test_reconcile_confirmed_receipt_verifies_and_finishes(publication):
    _store, outbox, _event, request = publication
    adapter = FakeAdapter()
    dispatcher = _dispatcher(outbox, adapter, request["publication_id"])
    dispatcher.process(request["publication_id"])
    adapter.receipt = _receipt(adapter)

    result = dispatcher.reconcile(request["publication_id"])

    assert result["status"] == "VERIFIED"
    states = [receipt["state"] for receipt in outbox.receipts(request["publication_id"])]
    assert "CONFIRMED" in states
    assert states[-1] == "VERIFIED"
    receipts = outbox.receipts(request["publication_id"])
    assert len({item["attempt_id"] for item in receipts}) == 1
    assert all(item["chain"] == request["chain"] for item in receipts)
    assert all(item["network"] == request["network"] for item in receipts)
    assert all(item["adapter_id"] == request["adapter_id"] for item in receipts)
    assert all(item["transaction_id"] == adapter.transaction_id for item in receipts)
    assert receipts[-1]["block_ref"] == "12345"
    assert receipts[-1]["submitted_at"] is not None
    assert receipts[-1]["confirmed_at"] is not None


def test_confirmed_state_is_retained_if_receipt_disappears_before_verified(publication):
    _store, outbox, _event, request = publication
    adapter = FakeAdapter()
    adapter.receipt = _receipt(adapter)
    adapter.verification = None
    dispatcher = _dispatcher(outbox, adapter, request["publication_id"])

    first = dispatcher.process(request["publication_id"])
    assert first["status"] == "CONFIRMED"
    adapter.receipt = None

    later = dispatcher.reconcile(request["publication_id"])

    assert later["status"] == "CONFIRMED"
    assert outbox.get(request["publication_id"])["status"] == "CONFIRMED"


def test_conflicting_verification_stops_for_manual_review(publication):
    _store, outbox, _event, request = publication
    adapter = FakeAdapter(verification=False)
    adapter.receipt = _receipt(adapter)
    result = _dispatcher(outbox, adapter, request["publication_id"]).process(
        request["publication_id"],
    )

    assert result["status"] == "MANUAL_INTERVENTION"
    assert result["last_failure_code"] == "VERIFICATION_CONFLICT"
    assert any(row["state"] == "CONFIRMED" for row in outbox.receipts(request["publication_id"]))
    assert not any(row["state"] == "VERIFIED" for row in outbox.receipts(request["publication_id"]))


def test_reconcile_without_receipt_keeps_same_attempt_and_explicit_uncertainty(publication):
    _store, outbox, _event, request = publication
    adapter = FakeAdapter()
    dispatcher = _dispatcher(outbox, adapter, request["publication_id"])
    dispatcher.process(request["publication_id"])

    dispatcher.reconcile(request["publication_id"])

    assert outbox.get(request["publication_id"])["status"] in {"UNKNOWN", "RPC_ACCEPTED", "PREPARED"}
    assert outbox.latest_attempt(request["publication_id"])["attempt_number"] == 1


def test_forced_reconcile_observes_but_does_not_replay_before_backoff(publication):
    store, outbox, _event, request = publication
    adapter = FakeAdapter(submit_error=RuntimeError("simulated transport timeout"))
    dispatcher = _dispatcher(outbox, adapter, request["publication_id"])
    first = dispatcher.process(request["publication_id"])
    assert first["status"] == "UNKNOWN"
    store.connection.execute(
        "UPDATE publication_outbox SET available_at=? WHERE publication_id=?",
        (time.time() + 60, request["publication_id"]),
    )
    store.connection.commit()
    adapter.calls.clear()

    result = dispatcher.reconcile(request["publication_id"])

    assert result["status"] == "UNKNOWN"
    assert not any(call[0] == "submit" for call in adapter.calls)


def test_missing_adapter_after_ambiguous_submit_requires_manual_intervention(publication):
    store, outbox, _event, request = publication
    adapter = FakeAdapter(submit_error=RuntimeError("simulated transport timeout"))
    _dispatcher(outbox, adapter, request["publication_id"]).process(request["publication_id"])
    store.connection.execute(
        "UPDATE publication_outbox SET available_at=0 WHERE publication_id=?",
        (request["publication_id"],),
    )
    store.connection.commit()

    result = PublicationDispatcher(outbox, []).process(request["publication_id"])

    assert result["status"] == "MANUAL_INTERVENTION"
    assert result["last_failure_code"] == "ADAPTER_UNAVAILABLE"
    assert outbox.latest_attempt(request["publication_id"]) is not None
    assert [call[0] for call in adapter.calls].count("prepare") == 1


@pytest.mark.parametrize("bad_field,new_value", [
    ("chain", "solana"),
    ("network", "other-network"),
    ("transaction_id", "0x" + "cd" * 32),
    ("status", "MAGIC"),
])
def test_malformed_or_uncorrelated_receipt_cannot_verify(publication, bad_field, new_value):
    _store, outbox, _event, request = publication
    adapter = FakeAdapter()
    dispatcher = _dispatcher(outbox, adapter, request["publication_id"])
    dispatcher.process(request["publication_id"])
    adapter.receipt = _receipt(adapter, **{bad_field: new_value})

    try:
        dispatcher.reconcile(request["publication_id"])
    except (TypeError, ValueError):
        pass

    assert outbox.get(request["publication_id"])["status"] != "VERIFIED"
    assert not any(call[0] == "verify" for call in adapter.calls)


def test_failure_of_one_target_does_not_change_sibling_target(publication):
    store, outbox, event, request = publication
    sibling = outbox.enqueue_event(
        event.event_id, chain="arbitrum", destination="fake-rpc", network="local-testnet"
    )
    adapter = FakeAdapter(submit_error=TimeoutError("timed out"))
    dispatcher = _dispatcher(outbox, adapter, request["publication_id"])

    dispatcher.process(request["publication_id"])

    assert outbox.get(sibling["publication_id"])["status"] == "QUEUED"
    assert outbox.latest_attempt(sibling["publication_id"]) is None
    assert outbox.get(request["publication_id"])["status"] in {"UNKNOWN", "RETRYABLE"}
    assert store.verify_animal_chain("cow-1")


def test_submit_timeout_is_recoverable_with_exact_persisted_transaction(publication):
    _store, outbox, _event, request = publication
    adapter = FakeAdapter(submit_error=TimeoutError("timed out"))
    dispatcher = _dispatcher(outbox, adapter, request["publication_id"])

    dispatcher.process(request["publication_id"])
    first_attempt = outbox.latest_attempt(request["publication_id"])
    adapter.submit_error = None
    dispatcher.reconcile(request["publication_id"])

    assert outbox.latest_attempt(request["publication_id"])["attempt_id"] == first_attempt["attempt_id"]
    assert [call[0] for call in adapter.calls].count("prepare") == 1
    assert all(call[1].payload == first_attempt["payload"]
               for call in adapter.calls if call[0] == "submit")


def test_reconcile_prepared_after_restart_never_prepares_new_payload(publication):
    store, outbox, _event, request = publication
    path = store.path
    attempt = outbox.prepare_publication_attempt(
        request["publication_id"], adapter_id="fake-rpc",
        transaction_id="0x" + "ab" * 32, payload=b"prepared-publication", metadata={"test": True},
    )
    store.close()
    reopened = Store(path)
    try:
        recovered_outbox = SQLitePublicationOutbox(reopened)
        adapter = FakeAdapter()
        dispatcher = _dispatcher(recovered_outbox, adapter, request["publication_id"])

        dispatcher.reconcile(request["publication_id"])

        assert recovered_outbox.latest_attempt(request["publication_id"])["attempt_id"] == attempt["attempt_id"]
        assert [call[0] for call in adapter.calls].count("prepare") == 0
        assert [call[0] for call in adapter.calls].count("validate_prepared") >= 1
    finally:
        reopened.close()


def test_missing_adapter_is_recorded_as_permanent_failure(publication):
    _store, outbox, _event, request = publication
    dispatcher = PublicationDispatcher(outbox, [])

    result = dispatcher.process(request["publication_id"])

    assert result["status"] == "PERMANENT_FAILURE"
    assert result["last_failure_code"] == "ADAPTER_UNAVAILABLE"
    assert outbox.latest_attempt(request["publication_id"]) is None


def test_adapter_for_wrong_chain_or_network_cannot_publish(publication):
    _store, outbox, _event, request = publication
    for adapter in (FakeAdapter(chain="solana"), FakeAdapter(network="wrong-network")):
        result = _dispatcher(outbox, adapter, request["publication_id"]).process(request["publication_id"])
        assert result["status"] == "PERMANENT_FAILURE"
    assert outbox.latest_attempt(request["publication_id"]) is None


def test_prepare_failure_leaves_request_queued_and_does_not_submit(publication):
    _store, outbox, _event, request = publication

    class FailingPrepare(FakeAdapter):
        def prepare(self, commitment):
            self.calls.append(("prepare", commitment))
            raise RuntimeError("signer unavailable")

    adapter = FailingPrepare()
    dispatcher = _dispatcher(outbox, adapter, request["publication_id"])
    result = dispatcher.process(request["publication_id"])

    assert result["status"] == "QUEUED"
    assert result["retry_count"] == 1
    assert result["last_failure_code"] == "PREPARATION_UNAVAILABLE"
    assert outbox.latest_attempt(request["publication_id"]) is None
    assert not any(call[0] == "submit" for call in adapter.calls)


def test_invalid_prepared_response_never_reaches_persistence_or_network(publication):
    _store, outbox, _event, request = publication

    class InvalidPrepare(FakeAdapter):
        def prepare(self, commitment):
            self.calls.append(("prepare", commitment))
            return object()

    adapter = InvalidPrepare()
    result = _dispatcher(outbox, adapter, request["publication_id"]).process(request["publication_id"])

    assert result["status"] == "PERMANENT_FAILURE"
    assert result["last_failure_code"] == "PREPARED_PAYLOAD_INVALID"
    assert outbox.latest_attempt(request["publication_id"]) is None
    assert not any(call[0] == "submit" for call in adapter.calls)


def test_submit_returning_different_transaction_id_is_ambiguous(publication):
    _store, outbox, _event, request = publication

    class WrongSubmitId(FakeAdapter):
        def submit(self, prepared):
            super().submit(prepared)
            return "0x" + "cd" * 32

    adapter = WrongSubmitId()
    result = _dispatcher(outbox, adapter, request["publication_id"]).process(request["publication_id"])

    assert result["status"] == "UNKNOWN"
    assert outbox.latest_attempt(request["publication_id"])["transaction_id"] == adapter.transaction_id
    assert not any(call[0] == "verify" for call in adapter.calls)


def test_receipt_rpc_timeout_preserves_prepared_transaction(publication):
    _store, outbox, _event, request = publication
    adapter = FakeAdapter(receipt_error=TimeoutError("receipt RPC timeout"))
    dispatcher = _dispatcher(outbox, adapter, request["publication_id"])

    dispatcher.process(request["publication_id"])

    assert outbox.get(request["publication_id"])["status"] == "UNKNOWN"
    assert outbox.latest_attempt(request["publication_id"])["attempt_number"] == 1
    assert not any(call[0] == "verify" for call in adapter.calls)


def test_uncertain_verification_never_marks_verified(publication):
    _store, outbox, _event, request = publication
    adapter = FakeAdapter(verification=None)
    adapter.receipt = _receipt(adapter)
    dispatcher = _dispatcher(outbox, adapter, request["publication_id"])

    dispatcher.process(request["publication_id"])

    assert outbox.get(request["publication_id"])["status"] != "VERIFIED"
    assert outbox.latest_attempt(request["publication_id"])["attempt_number"] == 1


def test_confirmed_survives_later_receipt_rpc_failures_without_resubmit(publication):
    _store, outbox, _event, request = publication
    adapter = FakeAdapter(verification=None)
    adapter.receipt = _receipt(adapter)
    dispatcher = _dispatcher(outbox, adapter, request["publication_id"])
    assert dispatcher.process(request["publication_id"])["status"] == "CONFIRMED"
    submit_count = [call[0] for call in adapter.calls].count("submit")
    receipt_count = len(outbox.receipts(request["publication_id"]))
    adapter.receipt_error = TimeoutError("receipt RPC unavailable")

    assert dispatcher.reconcile(request["publication_id"])["status"] == "CONFIRMED"
    assert dispatcher.reconcile(request["publication_id"])["status"] == "CONFIRMED"

    assert [call[0] for call in adapter.calls].count("submit") == submit_count == 1
    assert len(outbox.receipts(request["publication_id"])) == receipt_count
    assert outbox.latest_attempt(request["publication_id"])["attempt_number"] == 1


def test_verified_target_never_resubmits(publication):
    _store, outbox, _event, request = publication
    adapter = FakeAdapter()
    adapter.receipt = _receipt(adapter)
    dispatcher = _dispatcher(outbox, adapter, request["publication_id"])
    assert dispatcher.process(request["publication_id"])["status"] == "VERIFIED"
    calls_after_verify = list(adapter.calls)

    assert dispatcher.process(request["publication_id"])["status"] == "VERIFIED"
    assert dispatcher.reconcile(request["publication_id"])["status"] == "VERIFIED"
    assert adapter.calls == calls_after_verify
    assert outbox.latest_attempt(request["publication_id"])["attempt_number"] == 1


def test_retryable_requires_explicit_safe_to_retry_evidence(publication):
    _store, outbox, _event, request = publication
    adapter = FakeAdapter()
    adapter.receipt = _receipt(adapter, status="RETRYABLE", retry_metadata={})
    dispatcher = _dispatcher(outbox, adapter, request["publication_id"])

    dispatcher.process(request["publication_id"])

    assert outbox.get(request["publication_id"])["status"] != "RETRYABLE"
    assert outbox.latest_attempt(request["publication_id"])["attempt_number"] == 1


def test_proven_retryable_creates_one_new_attempt_on_next_process(publication):
    _store, outbox, _event, request = publication
    adapter = FakeAdapter()
    adapter.receipt = _receipt(adapter, status="RETRYABLE", retry_metadata={"safe_to_retry": True})
    dispatcher = _dispatcher(outbox, adapter, request["publication_id"])

    assert dispatcher.process(request["publication_id"])["status"] == "RETRYABLE"
    first = outbox.latest_attempt(request["publication_id"])
    adapter.transaction_id = "0x" + "cd" * 32
    adapter.payload = b"second-prepared-publication"
    adapter.receipt = None
    outbox.store.connection.execute(
        "UPDATE publication_outbox SET available_at=0 WHERE publication_id=?",
        (request["publication_id"],),
    )
    outbox.store.connection.commit()
    dispatcher.process(request["publication_id"])

    second = outbox.latest_attempt(request["publication_id"])
    assert second["attempt_number"] == 2
    assert second["attempt_id"] != first["attempt_id"]
    assert second["transaction_id"] != first["transaction_id"]
    assert [call[0] for call in adapter.calls].count("prepare") == 2


def test_rejected_target_cannot_later_become_verified(publication):
    _store, outbox, _event, request = publication
    adapter = FakeAdapter()
    adapter.receipt = _receipt(adapter, status="REJECTED")
    dispatcher = _dispatcher(outbox, adapter, request["publication_id"])

    assert dispatcher.process(request["publication_id"])["status"] == "REJECTED"
    calls_after_reject = list(adapter.calls)
    adapter.receipt = _receipt(adapter, status="CONFIRMED")
    assert dispatcher.process(request["publication_id"])["status"] == "REJECTED"
    assert dispatcher.reconcile(request["publication_id"])["status"] == "REJECTED"
    assert adapter.calls == calls_after_reject
    assert outbox.get(request["publication_id"])["status"] == "REJECTED"


def test_two_store_connections_cannot_prepare_same_target_concurrently(publication):
    store, outbox, _event, request = publication
    publication_id = request["publication_id"]
    submitting = Event()
    release = Event()

    class PausedAdapter(FakeAdapter):
        def submit(self, prepared):
            submitting.set()
            assert release.wait(5), "first submit did not resume"
            return super().submit(prepared)

    first_adapter = PausedAdapter()
    first_dispatcher = _dispatcher(outbox, first_adapter, publication_id)
    second_store = Store(store.path)
    try:
        second_outbox = SQLitePublicationOutbox(second_store)
        second_adapter = FakeAdapter()
        second_dispatcher = _dispatcher(second_outbox, second_adapter, publication_id)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(first_dispatcher.process, publication_id)
            assert submitting.wait(5), "first worker did not reach submit"
            try:
                contested = second_dispatcher.process(publication_id)
                assert contested["status"] in {"PREPARED", "RPC_ACCEPTED", "UNKNOWN"}
                assert not any(call[0] in {"prepare", "submit"} for call in second_adapter.calls)
            finally:
                release.set()
            future.result(timeout=5)

        assert second_outbox.latest_attempt(publication_id)["attempt_number"] == 1
        assert [call[0] for call in first_adapter.calls].count("prepare") == 1
    finally:
        release.set()
        second_store.close()


def test_expired_processing_claim_can_be_recovered_without_new_attempt(publication):
    store, outbox, _event, request = publication
    publication_id = request["publication_id"]
    original = outbox.prepare_publication_attempt(
        publication_id, adapter_id="fake-rpc", transaction_id="0x" + "ab" * 32,
        payload=b"prepared-publication", metadata={"test": True},
    )
    stale_token = outbox.claim_processing(publication_id, lease_seconds=1)
    assert stale_token is not None
    store.connection.execute(
        "UPDATE publication_processing_claims SET expires_at=0 WHERE publication_id=?",
        (publication_id,),
    )
    store.connection.commit()
    restarted = Store(store.path)
    try:
        recovered_outbox = SQLitePublicationOutbox(restarted)
        adapter = FakeAdapter()
        dispatcher = _dispatcher(recovered_outbox, adapter, publication_id)
        dispatcher.reconcile(publication_id)

        assert recovered_outbox.latest_attempt(publication_id)["attempt_id"] == original["attempt_id"]
        assert [call[0] for call in adapter.calls].count("prepare") == 0
        assert [call[0] for call in adapter.calls].count("submit") == 1
        # The stale owner may finish late; token matching must preserve a new claim.
        fresh_token = recovered_outbox.claim_processing(publication_id, force=True)
        assert fresh_token is not None
        outbox.release_processing(publication_id, stale_token)
        assert recovered_outbox.claim_processing(publication_id) is None
        recovered_outbox.release_processing(publication_id, fresh_token)
    finally:
        restarted.close()
