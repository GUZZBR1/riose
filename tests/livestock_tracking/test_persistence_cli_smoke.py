from argparse import Namespace

from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.cli import run_demo


def test_cli_demo_writes_simulation_and_animals_through_store(tmp_path, monkeypatch):
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)
    database = tmp_path / "cli-demo.sqlite3"
    result = run_demo(Namespace(
        db=str(database), host="127.0.0.1", port=0, animals=1, anchors=1,
    ))

    assert result == 0
    store = Store(database)
    try:
        assert len(store.list_animals()) == 1
        assert store.verify_animal_chain("cow-0001")
        assert store.connection.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0] > 0
        assert store.connection.execute("SELECT COUNT(*) FROM positions").fetchone()[0] > 0
        assert store.get_metrics()
        assert store.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        store.close()
