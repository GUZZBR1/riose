#!/usr/bin/env python3
"""Exercise the existing event, SQLite outbox, commitment, and mock adapter path."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.adapters.persistence.publication_outbox import SQLitePublicationOutbox
from riose.products.livestock_tracking.application.publication_dispatcher import PublicationDispatcher
from riose.products.livestock_tracking.domain.publication import ChainReceipt, PreparedPublication


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class LocalMockAdapter:
    adapter_id: str = "sc3-local-mock-evm"
    chain: str = "base"
    network: str = "local-mock"
    transaction_id: str = "0x" + "ab" * 32
    receipt: ChainReceipt | None = None

    def healthcheck(self) -> bool:
        return True

    def prepare(self, commitment: Any) -> PreparedPublication:
        return PreparedPublication(self.transaction_id, b"SC3-SYNTHETIC-PUBLICATION", {"mode": "mock"})

    def validate_prepared(self, prepared: PreparedPublication, commitment: Any) -> None:
        if prepared.transaction_id != self.transaction_id or not prepared.payload:
            raise ValueError("mock publication payload did not validate")

    def submit(self, prepared: PreparedPublication) -> str:
        return prepared.transaction_id

    def get_receipt(self, transaction_id: str, commitment: Any) -> ChainReceipt | None:
        return self.receipt

    def verify(self, commitment: Any, receipt: ChainReceipt) -> bool:
        return receipt.transaction_id == self.transaction_id and receipt.evidence_status == "SIMULATED"


def git_head() -> str | None:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def run_smoke() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="riose-sc3-db-") as temp_dir:
        db_path = Path(temp_dir) / "fresh.sqlite3"
        store = Store(db_path)
        store.create_animal("sc3-synthetic-animal", "sc3-synthetic-tag", "sc3-synthetic-crypto-id")
        event = store.append_animal_event(
            "sc3-synthetic-animal", "WEIGHT_RECORDED", {"weight_kg": 421.0, "evidence": "SIMULATED"}, 1_800_000_000.0
        )
        event_evidence = store.event_chain_evidence("sc3-synthetic-animal")
        if event_evidence is None or not event_evidence.valid:
            raise RuntimeError("fresh Event V1 chain did not verify")

        outbox = SQLitePublicationOutbox(store)
        request = outbox.enqueue_event(
            event.event_id, chain="base", destination="sc3-local-mock-evm", network="local-mock", now=1_800_000_001.0
        )
        if not outbox.verify_local_binding(request["publication_id"]):
            raise RuntimeError("fresh Commitment V1 binding did not verify")
        store.close()

        restarted = Store(db_path)
        recovered_outbox = SQLitePublicationOutbox(restarted)
        persisted = recovered_outbox.get(request["publication_id"])
        if persisted is None or not recovered_outbox.verify_local_binding(request["publication_id"]):
            raise RuntimeError("publication queue did not survive a clean database reopen")

        adapter = LocalMockAdapter()
        dispatcher = PublicationDispatcher(recovered_outbox, [adapter])
        processed = dispatcher.process(request["publication_id"])
        adapter.receipt = ChainReceipt(
            chain=adapter.chain,
            network=adapter.network,
            transaction_id=adapter.transaction_id,
            status="CONFIRMED",
            block_ref="local-mock-block-1",
            evidence_status="SIMULATED",
        )
        reconciled = dispatcher.reconcile(request["publication_id"])
        receipts = recovered_outbox.receipts(request["publication_id"])
        restarted.close()

        verified = reconciled.get("status") == "VERIFIED" and any(item.get("state") == "VERIFIED" for item in receipts)
        if not verified:
            raise RuntimeError(f"mock publication reconciliation did not verify: {reconciled}")
        return {
            "schema_version": 1,
            "kind": "integrated_smoke",
            "status": "PASS",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_sha": git_head(),
            "flow": [
                "synthetic input",
                "Event V1 append and chain verification",
                "SQLite persistence in a new temporary database",
                "Commitment V1 binding verification",
                "publication queue persistence",
                "database close and reopen",
                "local mock adapter submit",
                "local mock receipt reconciliation",
            ],
            "event_status": "SIMULATED",
            "publication_network": "local-mock",
            "process_status": processed.get("status"),
            "reconcile_status": reconciled.get("status"),
            "verified_receipt_count": sum(item.get("state") == "VERIFIED" for item in receipts),
            "real_on_chain": "NOT_EXECUTED",
            "limitations": ["Uses the existing mock adapter boundary; does not start Ganache or contact a public chain."],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="reproducibility/integrated_smoke.json")
    args = parser.parse_args()
    report = run_smoke()
    target = Path(args.output)
    if not target.is_absolute():
        target = ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
