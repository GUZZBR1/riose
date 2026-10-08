"""Hard process-exit injection around the durable publication boundaries."""

import os
from pathlib import Path
from multiprocessing import get_context

from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.adapters.persistence.publication_outbox import SQLitePublicationOutbox
from riose.products.livestock_tracking.application.publication_dispatcher import PublicationDispatcher
from riose.products.livestock_tracking.domain.publication import ChainReceipt, PreparedPublication


TX_ID = "0x" + "ab" * 32
NETWORK = "base-test-network"
ADAPTER_ID = "evm-registry"


class CrashAdapter:
    chain = "base"
    network = NETWORK
    adapter_id = ADAPTER_ID

    def __init__(self, stage: str, state_path: str):
        self.stage = stage
        self.state_path = Path(state_path)

    def prepare(self, _commitment):
        return PreparedPublication(TX_ID, b"signed-publication", {"version": 1})

    def validate_prepared(self, prepared, _commitment):
        assert prepared.transaction_id == TX_ID
        assert prepared.payload == b"signed-publication"

    def submit(self, prepared):
        assert prepared.transaction_id == TX_ID
        with self.state_path.open("a", encoding="utf-8") as stream:
            stream.write("submit\n")
        if self.stage in {"C", "D"}:
            marker = "accepted" if self.stage == "D" else "send-started"
            self.state_path.with_suffix(".remote").write_text(marker, encoding="utf-8")
            os._exit(70 + ord(self.stage))
        if self.stage in {"E", "F"}:
            self.state_path.with_suffix(".remote").write_text("accepted", encoding="utf-8")
        return prepared.transaction_id

    def get_receipt(self, transaction_id, _commitment):
        if self.stage == "G":
            os._exit(77)
        remote = self.state_path.with_suffix(".remote")
        if not remote.exists() or remote.read_text(encoding="utf-8") != "accepted":
            return None
        if self.stage == "E" and not self.state_path.with_suffix(".receipt-known").exists():
            self.state_path.with_suffix(".receipt-known").write_text("yes", encoding="utf-8")
            os._exit(75)
        return ChainReceipt(
            chain=self.chain,
            network=self.network,
            transaction_id=transaction_id,
            status="CONFIRMED",
            block_ref="123",
            evidence_status="SIMULATED",
        )

    def verify(self, _commitment, _receipt):
        return True

    def healthcheck(self):
        return True


def _crash_worker(db_path: str, state_path: str, stage: str):
    store = Store(db_path)
    outbox = SQLitePublicationOutbox(store)
    adapter = CrashAdapter(stage, state_path)
    if stage == "A":
        outbox.prepare_publication_attempt = lambda *_args, **_kwargs: os._exit(71)
    elif stage == "B":
        original = outbox.prepare_publication_attempt

        def persist_then_crash(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(72)

        outbox.prepare_publication_attempt = persist_then_crash
    elif stage == "F":
        original = outbox.record_observation

        def persist_receipt_then_crash(*args, **kwargs):
            original(*args, **kwargs)
            state = kwargs.get("state")
            if state is not None and state.value == "CONFIRMED":
                os._exit(76)

        outbox.record_observation = persist_receipt_then_crash
    dispatcher = PublicationDispatcher(outbox, [adapter])
    publication_id = _publication_id(store)
    if stage == "G":
        dispatcher.reconcile(publication_id)
    else:
        dispatcher.process(publication_id)


def _publication_id(store):
    row = store.connection.execute(
        "SELECT publication_id FROM publication_requests ORDER BY created_at LIMIT 1"
    ).fetchone()
    return row[0]


def _new_database(path):
    store = Store(path)
    store.create_animal("cow", "tag", "secret")
    event = store.append_animal_event("cow", "WEIGHT_RECORDED", {"weight_kg": 420}, 1)
    outbox = SQLitePublicationOutbox(store)
    request = outbox.enqueue_event(
        event.event_id, chain="base", destination=ADAPTER_ID, network=NETWORK,
    )
    store.close()
    return request


def test_process_crashes_at_publication_side_effect_boundaries_and_recovers(tmp_path):
    expected_exit = {"A": 71, "B": 72, "C": 137, "D": 138, "E": 75, "F": 76, "G": 77}
    for stage, exit_code in expected_exit.items():
        db = tmp_path / f"crash-{stage}.sqlite3"
        state_path = tmp_path / f"crash-{stage}.events"
        request = _new_database(db)
        if stage == "G":
            seeded = Store(db)
            try:
                SQLitePublicationOutbox(seeded).prepare_publication_attempt(
                    request["publication_id"], adapter_id=ADAPTER_ID,
                    transaction_id=TX_ID, payload=b"signed-publication",
                    metadata={"version": 1},
                )
            finally:
                seeded.close()
        context = get_context("spawn")
        process = context.Process(target=_crash_worker, args=(str(db), str(state_path), stage))
        process.start()
        process.join(timeout=15)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
            raise AssertionError(f"crash worker for {stage} did not exit")
        assert process.exitcode == exit_code

        store = Store(db)
        try:
            outbox = SQLitePublicationOutbox(store)
            publication_id = request["publication_id"]
            store.connection.execute(
                "UPDATE publication_processing_claims SET expires_at=0 WHERE publication_id=?",
                (publication_id,),
            )
            store.connection.commit()
            before = outbox.get(publication_id)
            before_attempt = outbox.latest_attempt(publication_id)
            if stage == "A":
                assert before["status"] == "QUEUED"
                assert before_attempt is None
            else:
                assert before["status"] in {"PREPARED", "RPC_ACCEPTED", "CONFIRMED"}
                assert before_attempt["attempt_number"] == 1

            adapter = CrashAdapter("recovered", str(state_path))
            dispatcher = PublicationDispatcher(outbox, [adapter])
            operation = dispatcher.process if stage in {"A", "B", "C"} else dispatcher.reconcile
            recovered = operation(publication_id)

            if stage in {"D", "E", "F"}:
                assert recovered["status"] == "VERIFIED"
            else:
                assert recovered["status"] in {"RPC_ACCEPTED", "UNKNOWN", "VERIFIED"}
            attempt = outbox.latest_attempt(publication_id)
            assert attempt["attempt_number"] == 1
            assert attempt["transaction_id"] == TX_ID
            assert outbox.get(publication_id)["commitment"] == request["commitment"]
            total_submits = state_path.read_text(encoding="utf-8").splitlines().count("submit") if state_path.exists() else 0
            if stage in {"D", "E", "F"}:
                assert total_submits == 1
            elif stage == "A":
                assert total_submits == 1
            elif stage == "C":
                assert total_submits == 2  # exact signed bytes replayed after the ambiguous send
        finally:
            store.close()
