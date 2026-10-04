"""Deterministic offline event-to-receipt demo in a disposable SQLite file."""

from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path

from ..adapters.persistence import Store
from ..application.integrity_verifier import (
    IntegrityVerificationRequest,
    IntegrityVerifier,
)
from ..domain.commitment import create_commitment_from_chain_evidence, public_envelope
from ..domain.contracts import EvidenceStatus
from ..domain.publication import CommitmentPublicationRequest, publication_capabilities
from ..domain.receipt import PublicationReceipt, ReceiptStatus
from .blockchain import FakeBlockchainAdapter, FakeSubmitOutcome

DEMO_TIMESTAMP = 1_700_000_000.0
DEMO_ANIMAL_ID = "demo-animal-001"
DEMO_COMMITMENT_VERSION = 1


def run_blockchain_demo() -> int:
    """Run offline and print one stable JSON report; temporary storage is scoped."""
    with tempfile.TemporaryDirectory(prefix="riose-blockchain-demo-") as temp_dir:
        report = _run_scenario(Path(temp_dir) / "demo.sqlite3")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


def _run_scenario(database_path: Path) -> dict[str, object]:
    store = Store(database_path, enable_publication_receipts=True)
    try:
        store.connection.execute(
            "INSERT INTO animals(animal_id,hardware_id,cryptographic_id,created_at) VALUES(?,?,?,?)",
            (DEMO_ANIMAL_ID, "demo-tag-001", "d" * 64, DEMO_TIMESTAMP),
        )
        store.connection.commit()
        event = store.append_animal_event(
            DEMO_ANIMAL_ID,
            "HEALTH_EVENT",
            {"event": "DEMO_EVENT", "value": "synthetic"},
            timestamp=DEMO_TIMESTAMP,
        )
        chain = store.event_chain_evidence(DEMO_ANIMAL_ID)
        if chain is None or not chain.valid or chain.head_digest != event.hash:
            raise RuntimeError("synthetic event chain did not validate")
        simulated_chain = replace(chain, evidence_status=EvidenceStatus.SIMULATED)
        commitment = create_commitment_from_chain_evidence(chain, "d" * 64)
        adapter = FakeBlockchainAdapter([FakeSubmitOutcome.CONFIRMED])
        request = CommitmentPublicationRequest(
            public_envelope(commitment),
            destination="fake-chain",
            network="offline",
        )
        submitted = adapter.submit(request)
        observed = adapter.query(
            commitment=commitment.digest,
            destination="fake-chain",
            network="offline",
            reference=submitted.reference,
        )
        if submitted.reference is None:
            raise RuntimeError("fake publication did not return a reference")
        receipt = PublicationReceipt(
            receipt_id="demo-receipt-0001",
            version=DEMO_COMMITMENT_VERSION,
            commitment=commitment.digest,
            destination="fake-chain",
            network="offline",
            status=ReceiptStatus.CONFIRMED,
            evidence_status=EvidenceStatus.SIMULATED,
            source="fake-blockchain",
            observed_at=DEMO_TIMESTAMP + 1,
            reference=submitted.reference,
        )
        stored_receipt = store.publication_receipts.save(receipt)
        verification_request = IntegrityVerificationRequest(
            commitment.digest, "fake-chain", "offline", submitted.reference
        )
        verifier = IntegrityVerifier()
        pre_tamper = verifier.verify(
            verification_request,
            local_chain=simulated_chain,
            commitment_binding=commitment,
            receipt=stored_receipt,
            observation=observed,
        )
        before = store.verify_animal_chain(DEMO_ANIMAL_ID)
        store.connection.execute(
            "UPDATE animal_events SET payload=? WHERE animal_id=? AND event_id=?",
            ('{"tampered":true}', DEMO_ANIMAL_ID, event.event_id),
        )
        store.connection.commit()
        tampered_chain = store.event_chain_evidence(DEMO_ANIMAL_ID)
        if tampered_chain is None:
            raise RuntimeError("synthetic event chain disappeared during demo")
        after = store.verify_animal_chain(DEMO_ANIMAL_ID)
        post_tamper = verifier.verify(
            verification_request,
            local_chain=replace(tampered_chain, evidence_status=EvidenceStatus.SIMULATED),
            commitment_binding=commitment,
            receipt=stored_receipt,
            observation=observed,
        )
        return {
            "scenario": "riose-blockchain-demo-v1",
            "evidence": EvidenceStatus.SIMULATED.value,
            "commitment": commitment.digest,
            "steps": {
                "event": "SYNTHETIC",
                "local_chain_before_tamper": "VALID" if before else "INVALID",
                "publication_submit": {
                    "status": submitted.status.value,
                    "evidence": submitted.evidence_status.value,
                },
                "publication_observation": {
                    "status": observed.status.value,
                    "evidence": observed.evidence_status.value,
                },
                "receipt": {
                    "status": stored_receipt.status.value,
                    "evidence": stored_receipt.evidence_status.value,
                },
                "verification": {
                    "status": pre_tamper.status.value,
                    "reason": pre_tamper.reason.value,
                    "evidence": pre_tamper.evidence_status.value,
                },
                "local_chain_after_tamper": "VALID" if after else "INVALID",
                "tamper_verification": {
                    "status": post_tamper.status.value,
                    "reason": post_tamper.reason.value,
                    "evidence": post_tamper.evidence_status.value,
                },
            },
            "real_adapter_capability": publication_capabilities(None).evidence_status.value,
            "network_used": False,
        }
    finally:
        store.close()
