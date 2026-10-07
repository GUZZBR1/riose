"""Reliability checks for event appends through independent SQLite connections."""

from __future__ import annotations

import multiprocessing
import os
import sqlite3
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from riose.products.livestock_tracking.adapters.persistence import Store


def test_store_persistence_pragmas_match_the_local_reliability_contract(tmp_path):
    store = Store(tmp_path / "reliability-pragmas.sqlite3")
    try:
        assert store.connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert store.connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert store.connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert store.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        store.close()


def _append_from_process(path: str, worker: int, count: int, results) -> None:
    store = Store(path)
    try:
        for index in range(count):
            store.append_animal_event(
                "cow-1", "WEIGHT_RECORDED",
                {"worker": worker, "sequence": index},
                timestamp=float(worker * 100_000 + index),
            )
        results.put((worker, "ok", count))
    except Exception as exc:  # send child failures to the parent for assertion
        results.put((worker, type(exc).__name__, str(exc)))
        raise
    finally:
        store.close()


def _append_from_thread(path: Path, worker: int, count: int) -> int:
    store = Store(path)
    try:
        for index in range(count):
            store.append_animal_event(
                "cow-1", "WEIGHT_RECORDED",
                {"worker": worker, "sequence": index},
                timestamp=float(worker * 100_000 + index),
            )
        return count
    finally:
        store.close()


def _write_until_parent_kills(path: str, ready) -> None:
    store = Store(path)
    ready.set()
    index = 0
    try:
        while True:
            store.append_animal_event(
                "cow-1", "WEIGHT_RECORDED", {"worker": "kill-test", "sequence": index},
                timestamp=float(200_000 + index),
            )
            index += 1
    finally:
        store.close()


@pytest.fixture
def event_database(tmp_path):
    path = tmp_path / "events.sqlite3"
    store = Store(path)
    store.create_animal("cow-1", "tag-1", "crypto-1")
    store.close()
    return path


@pytest.mark.parametrize("writer_count", [2, 4, 8])
def test_independent_processes_serialize_event_chain_appends(event_database, writer_count):
    count_per_writer = 40
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    processes = [
        context.Process(
            target=_append_from_process,
            args=(str(event_database), worker, count_per_writer, results),
        )
        for worker in range(writer_count)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=45)

    still_running = [process.pid for process in processes if process.is_alive()]
    for process in processes:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    assert not still_running, f"writer processes did not finish: {still_running}"
    assert [process.exitcode for process in processes] == [0] * writer_count
    messages = [results.get(timeout=2) for _ in processes]
    assert sorted(message[0] for message in messages) == list(range(writer_count))
    assert all(message[1:] == ("ok", count_per_writer) for message in messages)

    store = Store(event_database)
    try:
        rows = store.connection.execute(
            "SELECT COUNT(*) FROM animal_events WHERE animal_id='cow-1'"
        ).fetchone()[0]
        assert rows == 1 + writer_count * count_per_writer
        assert store.verify_animal_chain("cow-1")
        assert store.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        store.close()


def test_independent_thread_connections_serialize_event_chain_appends(event_database):
    writer_count, count_per_writer = 8, 40
    with ThreadPoolExecutor(max_workers=writer_count) as executor:
        results = list(executor.map(
            lambda worker: _append_from_thread(event_database, worker, count_per_writer),
            range(writer_count),
        ))

    store = Store(event_database)
    try:
        rows = store.connection.execute(
            "SELECT COUNT(*) FROM animal_events WHERE animal_id='cow-1'"
        ).fetchone()[0]
        assert results == [count_per_writer] * writer_count
        assert rows == 1 + writer_count * count_per_writer
        assert store.verify_animal_chain("cow-1")
        assert store.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        store.close()


def test_append_failure_rolls_back_owned_write_transaction(event_database):
    store = Store(event_database)
    store.connection.execute(
        "CREATE TRIGGER reject_event BEFORE INSERT ON animal_events "
        "WHEN NEW.event_type='TRANSFER' BEGIN SELECT RAISE(ABORT,'injected failure'); END"
    )
    store.connection.commit()
    before = store.connection.execute("SELECT COUNT(*) FROM animal_events").fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        store.append_animal_event("cow-1", "TRANSFER", {"to": "farm-2"}, 10.0)

    assert not store.connection.in_transaction
    assert store.connection.execute("SELECT COUNT(*) FROM animal_events").fetchone()[0] == before
    store.connection.execute("DROP TRIGGER reject_event")
    store.connection.commit()
    store.append_animal_event("cow-1", "TRANSFER", {"to": "farm-2"}, 10.0)
    assert store.verify_animal_chain("cow-1")
    store.close()


def test_killing_writer_during_load_leaves_reopenable_verified_database(event_database):
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    process = context.Process(target=_write_until_parent_kills, args=(str(event_database), ready))
    process.start()
    assert ready.wait(timeout=15)

    deadline = time.monotonic() + 15
    observed = 0
    while time.monotonic() < deadline:
        connection = sqlite3.connect(event_database, timeout=5)
        try:
            observed = connection.execute(
                "SELECT COUNT(*) FROM animal_events WHERE animal_id='cow-1'"
            ).fetchone()[0]
        finally:
            connection.close()
        if observed >= 3:
            break
        time.sleep(0.01)
    assert observed >= 3, "writer did not begin event load"

    process.terminate()
    process.join(timeout=10)
    assert not process.is_alive()
    assert process.exitcode != 0

    store = Store(event_database)
    try:
        assert store.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert store.verify_animal_chain("cow-1")
        assert store.connection.execute(
            "SELECT COUNT(*) FROM animal_events WHERE animal_id='cow-1'"
        ).fetchone()[0] >= observed
        store.append_animal_event(
            "cow-1", "WEIGHT_RECORDED", {"after_restart": True}, 999_999.0
        )
        assert store.verify_animal_chain("cow-1")
    finally:
        store.close()


def test_episode_write_failure_rolls_back_earlier_table_inserts(event_database):
    store = Store(event_database)
    store.connection.execute(
        "CREATE TRIGGER reject_position BEFORE INSERT ON positions "
        "BEGIN SELECT RAISE(ABORT,'injected position failure'); END"
    )
    store.connection.commit()
    observation = SimpleNamespace(
        timestamp_s=1.0, tag_id="tag-1", anchor_id="anchor-1", rssi_dbm=-40.0,
        snr_db=20.0, packet_received=True, imu_accel_norm_g=1.0,
        behavior_state="REST", status=SimpleNamespace(value="SIMULATED"),
    )
    estimate = SimpleNamespace(
        timestamp_s=1.0, tag_id="tag-1", x=1.0, y=2.0, method="test",
        quality=0.9, status=SimpleNamespace(value="SIMULATED"),
    )

    with pytest.raises(sqlite3.IntegrityError, match="injected position failure"):
        store.save_episode([observation], [estimate], [])

    assert not store.connection.in_transaction
    assert store.connection.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0] == 0
    assert store.connection.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0
    store.close()


def test_event_append_waits_for_existing_sqlite_writer_lock(event_database):
    holder = Store(event_database)
    writer = Store(event_database)
    holder.connection.execute("BEGIN IMMEDIATE")
    assert writer.connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    release = threading.Timer(0.2, holder.connection.commit)
    release.start()
    started = time.monotonic()
    try:
        event = writer.append_animal_event(
            "cow-1", "WEIGHT_RECORDED", {"after_lock": True}, 123.0
        )
    finally:
        release.join()
    elapsed = time.monotonic() - started
    assert elapsed >= 0.15
    assert event.previous_hash
    assert writer.verify_animal_chain("cow-1")
    holder.close()
    writer.close()
