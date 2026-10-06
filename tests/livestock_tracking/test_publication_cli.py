import json

from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.adapters.persistence.publication_outbox import SQLitePublicationOutbox
from riose.products.livestock_tracking.cli import main
from riose.products.livestock_tracking.domain.publication_state import PublicationState


def test_publication_cli_queue_and_status_are_offline_and_minimal(tmp_path, capsys):
    db = tmp_path / "cli.sqlite3"
    store = Store(db)
    store.create_animal("animal-secret", "tag-secret", "crypto-secret")
    event = store.append_animal_event("animal-secret", "WEIGHT_RECORDED", {"weight": 1, "location": "private"}, 2)
    store.close()
    assert main(["publication", "queue", "--db", str(db), "--event-id", str(event.event_id),
                 "--network", "solana-devnet-GH7ome3EiwEr7tu9JuTh2dpYWBJK3z69Xm1ZE3MEE6JC"]) == 0
    queued = json.loads(capsys.readouterr().out)
    assert queued["status"] == "QUEUED"
    assert queued["verification"] == {
        "LOCAL_HASH_VALID": True, "RECEIPT_PRESENT": False,
        "CHAIN_CONFIRMED": False, "CHAIN_VERIFIED": False,
    }
    assert "animal-secret" not in str(queued)
    assert "location" not in str(queued)

    assert main(["publication", "status", "--db", str(db), "--publication-id", queued["publication_id"]]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["commitment"] == queued["commitment"]
    assert status["receipts"] == []


def test_publication_cli_does_not_select_or_use_a_network_by_default():
    import pytest
    with pytest.raises(SystemExit) as exc:
        main(["publication", "send", "--help"])
    assert exc.value.code == 0


def test_unknown_send_recovers_by_same_signature_without_duplicate_submission(tmp_path, monkeypatch, capsys):
    db = tmp_path / "recover.sqlite3"
    store = Store(db)
    store.create_animal("cow-1", "tag-1", "crypto-1")
    event = store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"weight": 421}, 10)
    outbox = SQLitePublicationOutbox(store)
    request = outbox.enqueue_event(
        event.event_id, destination="solana-memo",
        network="solana-devnet-GH7ome3EiwEr7tu9JuTh2dpYWBJK3z69Xm1ZE3MEE6JC",
    )
    store.close()

    class FakeClient:
        submits = 0
        signatures = []
        observed = None

        def __init__(self, config):
            self.config = config

        def prepare(self, envelope, keypair):
            return b"signed-wire", "1" * 64, 500

        def submit(self, transaction, signature):
            type(self).submits += 1
            return signature

        def verify(self, signature, envelope):
            self.signatures.append(signature)
            return self.observed, 7 if self.observed else None

    from riose.products.livestock_tracking.adapters import solana_memo
    monkeypatch.setattr(solana_memo, "SolanaMemoClient", FakeClient)
    monkeypatch.setattr(solana_memo, "load_keypair", lambda _path: object())
    common = ["--db", str(db), "--publication-id", request["publication_id"],
              "--rpc-url", "https://rpc.example", "--expected-genesis-hash",
              "GH7ome3EiwEr7tu9JuTh2dpYWBJK3z69Xm1ZE3MEE6JC"]
    assert main(["publication", "send", *common, "--keypair", str(tmp_path / "key.json")]) == 3
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "UNKNOWN"
    assert FakeClient.submits == 1

    FakeClient.observed = True
    assert main(["publication", "reconcile", *common]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "VERIFIED"
    assert FakeClient.submits == 1
    assert FakeClient.signatures == ["1" * 64, "1" * 64]

    reopened = Store(db)
    outbox = SQLitePublicationOutbox(reopened)
    attempts = reopened.connection.execute("SELECT COUNT(*) FROM publication_attempts").fetchone()[0]
    assert attempts == 1
    assert outbox.latest_attempt(request["publication_id"])["signature"] == "1" * 64
    assert PublicationState(outbox.get(request["publication_id"])["status"]) is PublicationState.VERIFIED
    reopened.close()
