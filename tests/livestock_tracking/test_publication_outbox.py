"""Persistence, opt-in, and concurrency tests for the local outbox."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from riose.products.livestock_tracking.adapters.persistence import (
    OutboxEnvelope,
    Store,
)
from riose.products.livestock_tracking.adapters.persistence.publication_outbox import (
    MAX_OUTBOX_ENVELOPE_BYTES,
)


def envelope(data: bytes = b'{"version":1,"fixture":"synthetic"}') -> OutboxEnvelope:
    return OutboxEnvelope(version=1, data=data)


def test_outbox_is_opt_in_and_default_store_stays_operational(tmp_path):
    path = tmp_path / "existing.sqlite3"
    store = Store(path)
    assert store.publication_outbox is None
    assert store.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='publication_outbox'"
    ).fetchone() is None
    store.create_animal("synthetic-animal", "synthetic-tag", "a" * 64)
    assert store.verify_animal_chain("synthetic-animal")
    store.close()

    enabled = Store(path, enable_publication_outbox=True)
    assert enabled.publication_outbox is not None
    assert enabled.verify_animal_chain("synthetic-animal")
    enabled.close()


def test_enqueue_get_reopen_and_claim_preserve_exact_versioned_bytes(tmp_path):
    path = tmp_path / "outbox.sqlite3"
    store = Store(path, enable_publication_outbox=True)
    ticket = store.publication_outbox.enqueue("ticket-1", envelope(), available_at=20.0)
    assert ticket.envelope == envelope()
    assert store.publication_outbox.get("ticket-1") == ticket
    assert store.publication_outbox.claim_due(now=19.9, limit=10, claim_token="worker-1") == []
    claimed = store.publication_outbox.claim_due(now=20.0, limit=10, claim_token="worker-1")
    assert len(claimed) == 1
    assert claimed[0].claim_token == "worker-1"
    assert claimed[0].claimed_at == 20.0
    store.close()

    reopened = Store(path, enable_publication_outbox=True)
    assert reopened.publication_outbox.get("ticket-1") == claimed[0]
    assert reopened.publication_outbox.list_pending(limit=10) == []
    reopened.close()


def test_pending_order_limit_and_claim_select_are_deterministic(tmp_path):
    store = Store(tmp_path / "order.sqlite3", enable_publication_outbox=True)
    outbox = store.publication_outbox
    outbox.enqueue("b", envelope(b"b"), 1.0)
    outbox.enqueue("a", envelope(b"a"), 1.0)
    outbox.enqueue("later", envelope(b"c"), 2.0)

    assert [ticket.ticket_id for ticket in outbox.list_pending(2)] == ["a", "b"]
    claimed = outbox.claim_due(now=1.0, limit=1, claim_token="worker")
    assert [ticket.ticket_id for ticket in claimed] == ["a"]
    assert [ticket.ticket_id for ticket in outbox.list_pending(10)] == ["b", "later"]
    store.close()


def test_duplicate_ticket_conflicts_without_overwriting(tmp_path):
    store = Store(tmp_path / "duplicate.sqlite3", enable_publication_outbox=True)
    outbox = store.publication_outbox
    outbox.enqueue("stable-id", envelope(b"first"), 1)

    with pytest.raises(sqlite3.IntegrityError):
        outbox.enqueue("stable-id", envelope(b"replacement"), 2)

    assert outbox.get("stable-id").envelope.data == b"first"
    assert outbox.get("stable-id").available_at == 1.0
    store.close()


def test_two_connections_never_claim_the_same_ticket(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    writer = Store(path, enable_publication_outbox=True)
    outbox = writer.publication_outbox
    for index in range(20):
        outbox.enqueue(f"ticket-{index:02d}", envelope(str(index).encode()), 1)
    writer.close()

    left = Store(path, enable_publication_outbox=True)
    right = Store(path, enable_publication_outbox=True)
    barrier = Barrier(2)

    def claim(store, token):
        barrier.wait()
        return store.publication_outbox.claim_due(1, 20, token)

    with ThreadPoolExecutor(max_workers=2) as executor:
        left_future = executor.submit(claim, left, "left-worker")
        right_future = executor.submit(claim, right, "right-worker")
        left_claimed = left_future.result()
        right_claimed = right_future.result()

    left_ids = {ticket.ticket_id for ticket in left_claimed}
    right_ids = {ticket.ticket_id for ticket in right_claimed}
    assert left_ids.isdisjoint(right_ids)
    assert len(left_ids | right_ids) == 20
    left.close()
    right.close()


def test_claim_rolls_back_all_tickets_on_database_failure(tmp_path):
    store = Store(tmp_path / "rollback.sqlite3", enable_publication_outbox=True)
    outbox = store.publication_outbox
    outbox.enqueue("first", envelope(b"one"), 1)
    outbox.enqueue("second", envelope(b"two"), 1)
    store.connection.execute(
        "CREATE TRIGGER fail_claim BEFORE UPDATE ON publication_outbox "
        "BEGIN SELECT RAISE(ABORT,'synthetic test failure'); END"
    )
    store.connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        outbox.claim_due(1, 2, "worker")

    assert [ticket.ticket_id for ticket in outbox.list_pending(10)] == ["first", "second"]
    assert outbox.get("first").claim_token is None
    store.close()


def test_enqueue_failure_does_not_change_previously_committed_event(tmp_path):
    store = Store(tmp_path / "isolation.sqlite3", enable_publication_outbox=True)
    store.create_animal("synthetic-animal", "synthetic-tag", "a" * 64)
    assert store.verify_animal_chain("synthetic-animal")
    store.connection.execute(
        "CREATE TRIGGER fail_enqueue BEFORE INSERT ON publication_outbox "
        "BEGIN SELECT RAISE(ABORT,'synthetic test failure'); END"
    )
    store.connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        store.publication_outbox.enqueue("ticket", envelope(), 1)

    assert store.verify_animal_chain("synthetic-animal")
    assert store.connection.execute("SELECT COUNT(*) FROM animal_events").fetchone()[0] == 1
    store.close()


@pytest.mark.parametrize(
    "make_invalid",
    [
        lambda: OutboxEnvelope(True, b"x"),
        lambda: OutboxEnvelope(1, b""),
        lambda: OutboxEnvelope(1, b"x" * (MAX_OUTBOX_ENVELOPE_BYTES + 1)),
    ],
)
def test_envelope_validation_is_bounded_and_typed(make_invalid):
    with pytest.raises(ValueError):
        make_invalid()


@pytest.mark.parametrize(
    ("operation", "values"),
    [
        ("enqueue", {"ticket_id": "bad/id", "available_at": 1}),
        ("enqueue", {"ticket_id": "ticket", "available_at": float("nan")}),
        ("claim", {"now": float("nan"), "limit": 1, "claim_token": "worker"}),
        ("claim", {"now": 0, "limit": True, "claim_token": "worker"}),
        ("claim", {"now": 0, "limit": 1, "claim_token": "secret value"}),
    ],
)
def test_outbox_rejects_invalid_identifiers_timestamps_and_limits(tmp_path, operation, values):
    store = Store(tmp_path / "invalid.sqlite3", enable_publication_outbox=True)
    if operation == "enqueue":
        with pytest.raises(ValueError):
            store.publication_outbox.enqueue(
                values["ticket_id"], envelope(), values["available_at"]
            )
    else:
        with pytest.raises(ValueError):
            store.publication_outbox.claim_due(
                values["now"], values["limit"], values["claim_token"]
            )
    assert store.publication_outbox.list_pending(1) == []
    store.close()
