"""Chain-neutral, durable publication execution and reconciliation."""

from __future__ import annotations

from collections.abc import Iterable
from contextvars import ContextVar
import re
from threading import Event, Thread
import time

from ..domain.privacy import parse_public_envelope_json
from ..domain.publication import ChainAdapter, ChainReceipt, PreparedPublication
from ..domain.publication_state import PublicationState


_TECHNICAL_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z", re.ASCII)


class PublicationDispatcher:
    def __init__(self, outbox: object, adapters: Iterable[ChainAdapter]) -> None:
        self.outbox = outbox
        self._claim: ContextVar[tuple[str, str, Event] | None] = ContextVar("publication_claim", default=None)
        self.adapters = tuple(adapters)
        keys = [(item.chain, item.network, item.adapter_id) for item in self.adapters]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate publication adapter target")

    def process(self, publication_id: str) -> dict:
        return self._run(publication_id, prepare_new=True)

    def reconcile(self, publication_id: str) -> dict:
        return self._run(publication_id, prepare_new=False)

    def _run(self, publication_id: str, *, prepare_new: bool) -> dict:
        request = self.outbox.get(publication_id)
        if request is None:
            raise ValueError("publication request was not found")
        token = self.outbox.claim_processing(publication_id, force=not prepare_new)
        if token is None:
            return self.outbox.get(publication_id)
        stopped = Event()
        lost = Event()

        def renew_claim() -> None:
            while not stopped.wait(20):
                try:
                    if not self.outbox.renew_processing(publication_id, token):
                        lost.set()
                        return
                except Exception:
                    lost.set()
                    return

        heartbeat = Thread(target=renew_claim, daemon=True)
        heartbeat.start()
        claim_context = self._claim.set((publication_id, token, lost))
        try:
            request = self.outbox.get(publication_id)
            state = PublicationState(request["status"])
            retry_due = float(request["available_at"]) <= time.time()
            if state in {
                PublicationState.VERIFIED,
                PublicationState.REJECTED,
                PublicationState.PERMANENT_FAILURE,
                PublicationState.MANUAL_INTERVENTION,
            }:
                return request
            if prepare_new and request["retry_count"] >= self.outbox.retry_policy.max_retries:
                return self.outbox.require_manual_intervention(
                    publication_id, claim_token=token
                )
            try:
                adapter = self._adapter(request)
            except ValueError:
                return self._terminal_local_failure(
                    publication_id, "ADAPTER_UNAVAILABLE", token
                )
            if not self.outbox.verify_local_binding(publication_id):
                return self._terminal_local_failure(
                    publication_id, "LOCAL_BINDING_INVALID", token
                )
            envelope = parse_public_envelope_json(request["envelope"])
            if state in {PublicationState.QUEUED, PublicationState.RETRYABLE}:
                if not prepare_new:
                    return request
                try:
                    if not adapter.healthcheck():
                        return self._defer_retry(
                            publication_id, token, "TARGET_UNAVAILABLE",
                            "TRANSIENT_PRE_SUBMISSION",
                        )
                except Exception:
                    return self._defer_retry(
                        publication_id, token, "HEALTHCHECK_UNAVAILABLE",
                        "TRANSIENT_PRE_SUBMISSION",
                    )
                try:
                    prepared = adapter.prepare(envelope)
                except ValueError:
                    return self.outbox.fail_permanently(
                        publication_id, reason_code="PREPARATION_REJECTED", claim_token=token
                    )
                except Exception:
                    return self._defer_retry(
                        publication_id, token, "PREPARATION_UNAVAILABLE",
                        "TRANSIENT_PRE_SUBMISSION",
                    )
                try:
                    self._check_prepared(prepared)
                    adapter.validate_prepared(prepared, envelope)
                except Exception:
                    return self.outbox.fail_permanently(
                        publication_id, reason_code="PREPARED_PAYLOAD_INVALID", claim_token=token
                    )
                self._ensure_claim(publication_id)
                attempt = self.outbox.prepare_publication_attempt(
                    publication_id, adapter_id=adapter.adapter_id,
                    transaction_id=prepared.transaction_id, payload=prepared.payload,
                    metadata=prepared.metadata, claim_token=token,
                )
                return self._submit_and_observe(publication_id, attempt, prepared, adapter, envelope)
            attempt = self.outbox.latest_attempt(publication_id)
            if attempt is None:
                raise ValueError("publication state has no persisted attempt")
            if attempt["adapter_id"] != adapter.adapter_id:
                return self.outbox.require_manual_intervention(
                    publication_id, reason_code="PERSISTED_ADAPTER_MISMATCH",
                    claim_token=token,
                )
            prepared = PreparedPublication(attempt["transaction_id"], attempt["payload"], attempt["metadata"])
            try:
                self._check_prepared(prepared)
                adapter.validate_prepared(prepared, envelope)
            except Exception:
                return self._terminal_local_failure(
                    publication_id, "PERSISTED_PAYLOAD_INVALID", token
                )
            observed = self._observe(publication_id, attempt, adapter, envelope)
            if observed is not None:
                return self.outbox.get(publication_id)
            state = PublicationState(self.outbox.get(publication_id)["status"])
            if state in {PublicationState.PREPARED, PublicationState.UNKNOWN}:
                # Reconciliation may observe at any time, but backoff only allows
                # the scheduler to replay saved signed bytes once the retry is due.
                if not retry_due:
                    return self.outbox.get(publication_id)
                can_replay = getattr(adapter, "can_replay", None)
                if callable(can_replay):
                    try:
                        replay_allowed = can_replay(prepared)
                    except Exception:
                        return self._defer_retry(
                            publication_id, token, "REPLAY_SAFETY_UNAVAILABLE",
                            "REPLAY_SAFETY_PENDING",
                        )
                    if replay_allowed is not True:
                        return self.outbox.require_manual_intervention(
                            publication_id, reason_code="PERSISTED_ATTEMPT_EXPIRED",
                            claim_token=token,
                        )
                return self._submit_and_observe(publication_id, attempt, prepared, adapter, envelope)
            return self.outbox.get(publication_id)
        finally:
            stopped.set()
            heartbeat.join()
            self._claim.reset(claim_context)
            self.outbox.release_processing(publication_id, token)

    def _ensure_claim(self, publication_id: str) -> None:
        claim = self._claim.get()
        if claim is None or claim[0] != publication_id or claim[2].is_set() or not self.outbox.owns_processing(publication_id, claim[1]):
            raise RuntimeError("publication processing claim was lost")

    def _adapter(self, request: dict) -> ChainAdapter:
        target = (request["chain"], request["network"], request["adapter_id"])
        matched = [item for item in self.adapters if (item.chain, item.network, item.adapter_id) == target]
        if len(matched) != 1:
            raise ValueError("no publication adapter matches the queued target")
        return matched[0]

    @staticmethod
    def _check_prepared(prepared: PreparedPublication) -> None:
        if not isinstance(prepared, PreparedPublication):
            raise ValueError("adapter returned an invalid prepared publication")
        if type(prepared.transaction_id) is not str or not prepared.transaction_id:
            raise ValueError("adapter returned an invalid transaction identifier")
        if type(prepared.payload) is not bytes or not prepared.payload or type(prepared.metadata) is not dict:
            raise ValueError("adapter returned an invalid prepared payload")

    def _submit_and_observe(self, publication_id, attempt, prepared, adapter, envelope) -> dict:
        self._ensure_claim(publication_id)
        try:
            transaction_id = adapter.submit(prepared)
            if type(transaction_id) is not str or transaction_id != prepared.transaction_id:
                raise ValueError("adapter returned a mismatched transaction identifier")
        except Exception:
            self._unknown(publication_id, attempt, adapter, "SUBMIT_AMBIGUOUS")
            return self.outbox.get(publication_id)
        state = PublicationState(self.outbox.get(publication_id)["status"])
        accepted_before = any(
            item["attempt_id"] == attempt["attempt_id"] and item["state"] == PublicationState.RPC_ACCEPTED.value
            for item in self.outbox.receipts(publication_id)
        )
        if state in {PublicationState.PREPARED, PublicationState.UNKNOWN} and not accepted_before:
            self._record(publication_id, attempt, adapter, PublicationState.RPC_ACCEPTED)
        self._observe(publication_id, attempt, adapter, envelope)
        return self.outbox.get(publication_id)

    def _observe(self, publication_id, attempt, adapter, envelope) -> ChainReceipt | None:
        try:
            receipt = adapter.get_receipt(attempt["transaction_id"], envelope)
        except Exception:
            self._unknown(publication_id, attempt, adapter, "RECEIPT_UNAVAILABLE")
            return None
        if receipt is None:
            self._defer_retry(
                publication_id, self._claim.get()[1], "RECEIPT_PENDING",
                "RECEIPT_PENDING",
            )
            return None
        if (
            not isinstance(receipt, ChainReceipt)
            or receipt.chain != adapter.chain
            or receipt.network != adapter.network
            or receipt.transaction_id != attempt["transaction_id"]
            or receipt.status not in {"CONFIRMED", "REJECTED", "RETRYABLE"}
            or receipt.evidence_status not in {"ASSUMED", "SIMULATED", "MOCKED", "VALIDATED"}
            or (receipt.block_ref is not None and (
                type(receipt.block_ref) is not str or _TECHNICAL_ID.fullmatch(receipt.block_ref) is None
            ))
            or type(receipt.retry_metadata) is not dict
            or any(key not in {"safe_to_retry", "slot"} for key in receipt.retry_metadata)
            or ("safe_to_retry" in receipt.retry_metadata and type(receipt.retry_metadata["safe_to_retry"]) is not bool)
            or ("slot" in receipt.retry_metadata and (
                type(receipt.retry_metadata["slot"]) is not int or receipt.retry_metadata["slot"] < 0
            ))
        ):
            self._unknown(publication_id, attempt, adapter, "MALFORMED_ADAPTER_RESPONSE")
            return None
        state = PublicationState(self.outbox.get(publication_id)["status"])
        if receipt.status == "RETRYABLE":
            if receipt.retry_metadata.get("safe_to_retry") is not True:
                self._unknown(publication_id, attempt, adapter, "RETRY_NOT_PROVEN_SAFE")
                return None
            if state in {PublicationState.PREPARED, PublicationState.RPC_ACCEPTED, PublicationState.UNKNOWN}:
                self._record(publication_id, attempt, adapter, PublicationState.RETRYABLE, receipt=receipt)
                self._defer_retry(
                    publication_id, self._claim.get()[1], "SAFE_RETRY_CONFIRMED",
                    "SAFE_RETRY",
                )
            return receipt
        if receipt.status == "REJECTED":
            if state in {PublicationState.PREPARED, PublicationState.RPC_ACCEPTED, PublicationState.UNKNOWN}:
                self._record(publication_id, attempt, adapter, PublicationState.REJECTED, receipt=receipt, reason_code="TRANSACTION_REJECTED")
            return receipt
        if state in {PublicationState.PREPARED, PublicationState.RPC_ACCEPTED, PublicationState.UNKNOWN}:
            self._record(publication_id, attempt, adapter, PublicationState.CONFIRMED, receipt=receipt)
        if PublicationState(self.outbox.get(publication_id)["status"]) is PublicationState.CONFIRMED:
            try:
                verified = adapter.verify(envelope, receipt)
            except Exception:
                self._defer_retry(
                    publication_id, self._claim.get()[1], "VERIFICATION_UNAVAILABLE",
                    "VERIFICATION_PENDING",
                )
                return receipt
            if verified is True:
                self._record(publication_id, attempt, adapter, PublicationState.VERIFIED, receipt=receipt)
            elif verified is None:
                self._defer_retry(
                    publication_id, self._claim.get()[1], "VERIFICATION_PENDING",
                    "VERIFICATION_PENDING",
                )
            else:
                self.outbox.require_manual_intervention(
                    publication_id, reason_code="VERIFICATION_CONFLICT",
                    claim_token=self._claim.get()[1],
                )
            # A failed second query cannot erase the observed confirmation.
            # A conflicting result is escalated instead of hot-polling forever.
        return receipt

    def _unknown(self, publication_id, attempt, adapter, reason_code: str) -> None:
        if PublicationState(self.outbox.get(publication_id)["status"]) in {
            PublicationState.PREPARED, PublicationState.RPC_ACCEPTED
        }:
            self._record(publication_id, attempt, adapter, PublicationState.UNKNOWN, reason_code=reason_code)
        self._defer_retry(
            publication_id, self._claim.get()[1], reason_code,
            "AMBIGUOUS_SUBMISSION",
        )

    def _defer_retry(self, publication_id, token, reason_code, failure_class) -> dict:
        self._ensure_claim(publication_id)
        return self.outbox.defer_retry(
            publication_id,
            failure_class=failure_class,
            reason_code=reason_code,
            claim_token=token,
        )

    def _terminal_local_failure(self, publication_id: str, reason_code: str, token: str) -> dict:
        if self.outbox.latest_attempt(publication_id) is not None:
            return self.outbox.require_manual_intervention(
                publication_id, reason_code=reason_code, claim_token=token,
            )
        return self.outbox.fail_permanently(
            publication_id, reason_code=reason_code, claim_token=token,
        )

    def _record(self, publication_id, attempt, adapter, state, *, receipt=None, reason_code=None) -> None:
        self._ensure_claim(publication_id)
        block_ref = receipt.block_ref if receipt is not None else None
        slot = int(block_ref) if block_ref is not None and block_ref.isdigit() else None
        self.outbox.record_observation(
            publication_id, attempt["attempt_id"], state=state,
            adapter_id=adapter.adapter_id, transaction_id=attempt["transaction_id"],
            block_ref=block_ref, slot=slot, reason_code=reason_code,
            retry_metadata=receipt.retry_metadata if receipt is not None else {},
            evidence_status=receipt.evidence_status if receipt is not None else "ASSUMED",
            claim_token=self._claim.get()[1],
        )
