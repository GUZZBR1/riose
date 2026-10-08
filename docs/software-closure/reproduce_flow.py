"""Audit harness: local simulation and existing mock dispatcher, no network writes.

Run from the repository root with PYTHONPATH=src and the locked dev environment.
The dispatcher fixture is deliberately MOCK; VERIFIED is local software state.
The Event V1 recording/queue step is explicit orchestration by this harness.
"""
import argparse
import json
from pathlib import Path
import runpy
import tempfile

from fastapi.testclient import TestClient
from riose.products.livestock_tracking.adapters.api import create_app
from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.adapters.persistence.publication_outbox import SQLitePublicationOutbox
from riose.products.livestock_tracking.application.publication_dispatcher import PublicationDispatcher


def reproduce():
    fixtures = runpy.run_path("tests/livestock_tracking/test_publication_dispatcher.py")
    FakeAdapter, receipt = fixtures["FakeAdapter"], fixtures["_receipt"]
    with tempfile.TemporaryDirectory(prefix="riose-audit-flow-") as directory:
        database = Path(directory) / "flow.sqlite3"
        app = create_app(database)
        with TestClient(app) as client:
            response = client.post("/api/simulation/run", json={
                "animal_count": 1, "anchor_count": 4, "duration_s": 90,
                "sample_period_s": 30, "seed": 19, "method": "path_loss",
            })
            assert response.status_code == 200, response.text
            simulation = response.json()
            assert simulation["evidence"] == "SIMULATED"
            positions = client.get("/api/positions").json()
            assert all("ground_truth_x" not in item for item in positions)
            recorded = client.post("/api/events", json={
                "animal_id": "cow-0001", "event_type": "SIMULATION_RUN_RECORDED",
                "timestamp": 90.0,
                "payload": {"evidence": "SIMULATED", "observations": simulation["observations"]},
            })
            assert recorded.status_code == 201 and recorded.json()["chain_valid"]
            event = recorded.json()
            outbox = SQLitePublicationOutbox(app.state.store)
            requests = [outbox.enqueue_event(event["event_id"], chain=chain,
                        destination="fake-rpc", network="audit-local-mock")
                        for chain in ("solana", "base", "arbitrum")]
            assert len({item["commitment"] for item in requests}) == 1
            assert all(item["status"] == "QUEUED" for item in requests)
            assert all(outbox.verify_local_binding(item["publication_id"]) for item in requests)
            wire = requests[0]["envelope"]
            assert b"cow-0001" not in wire and b"SIMULATION_RUN_RECORDED" not in wire
        restarted = Store(database)
        try:
            outbox = SQLitePublicationOutbox(restarted)
            assert len(outbox.list_pending()) == 3
            assert restarted.verify_animal_chain("cow-0001")
            adapters = [FakeAdapter(chain=item["chain"], network=item["network"],
                        transaction_id="audit-mock-" + item["chain"])
                        for item in requests]
            dispatcher = PublicationDispatcher(outbox, adapters)
            for item, adapter in zip(requests, adapters):
                adapter.outbox, adapter.publication_id = outbox, item["publication_id"]
                assert dispatcher.process(item["publication_id"])["status"] == "RPC_ACCEPTED"
            restarted.close()
            restarted = Store(database)
            outbox = SQLitePublicationOutbox(restarted)
            dispatcher = PublicationDispatcher(outbox, adapters)
            states = {}
            for item, adapter in zip(requests, adapters):
                adapter.outbox = outbox
                adapter.receipt = receipt(adapter)
                recovered = dispatcher.reconcile(item["publication_id"])
                assert recovered["status"] == "VERIFIED"
                assert recovered["commitment"] == item["commitment"]
                assert recovered["envelope"] == wire
                assert outbox.latest_attempt(item["publication_id"])["attempt_number"] == 1
                assert sum(call[0] == "submit" for call in adapter.calls) == 1
                states[item["chain"]] = recovered["status"]
            assert not outbox.list_pending()
            assert restarted.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            return {"classification": "SIMULATED", "publication_backend": "MOCK_TEST_FIXTURE",
                    "integrated_flow": "VERIFIED_REPRODUCIBLE_LOCAL_HARNESS",
                    "simulation": simulation, "telemetry_count": simulation["observations"],
                    "positions_returned": len(positions), "normal_api_truth_hidden": True,
                    "explicit_harness_event_recording": True,
                    "offline_queue_size_before_restart": 3, "restart_count": 2,
                    "canonical_commitment_same_for_all_targets": True,
                    "mock_target_states": states, "remaining_pending": 0,
                    "one_attempt_and_submit_per_target": True,
                    "public_payload_minimal": True, "sqlite_integrity": "ok",
                    "public_chain_evidence": "UNVERIFIED",
                    "external_frequencia_scenario_reexecuted": False,
                    "hardware_or_field_validation": False}
        finally:
            restarted.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.output.write_text(json.dumps(reproduce(), indent=2) + "\n")
