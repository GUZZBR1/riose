"""Nonce reservation across independent SQLite Store connections."""

from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
from threading import Barrier, Event

import pytest

from riose.products.livestock_tracking.adapters.persistence import Store
from riose.products.livestock_tracking.adapters.persistence.evm_nonce import EVMNonceCoordinator
from riose.products.livestock_tracking.adapters.persistence.publication_outbox import SQLitePublicationOutbox


NETWORK = "evm-local:31337"
SENDER = "0x" + "ab" * 20


def _reserve_in_process(path, publication_id, start, output):
    store = Store(path)
    try:
        outbox = SQLitePublicationOutbox(store)
        assert outbox.claim_processing(publication_id)
        coordinator = EVMNonceCoordinator(store)
        start.wait(timeout=10)
        output.put(coordinator.reserve(publication_id, NETWORK, SENDER, 4)[0])
    finally:
        store.close()


def _requests(path, count=3):
    store = Store(path)
    store.create_animal("cow-1", "tag-1", "crypto-1")
    outbox = SQLitePublicationOutbox(store)
    publications = []
    for i in range(count):
        event = store.append_animal_event("cow-1", "WEIGHT_RECORDED", {"weight_kg": 420 + i}, 10.0 + i)
        request = outbox.enqueue_event(event.event_id, chain="evm", destination="evm-rpc", network=NETWORK)
        publications.append(request["publication_id"])
    store.close()
    return publications


def test_two_store_connections_reserve_distinct_nonces_for_one_signer(tmp_path):
    path = tmp_path / "nonces.sqlite3"
    first_id, second_id, _ = _requests(path)
    first_store, second_store = Store(path), Store(path)
    first_outbox, second_outbox = SQLitePublicationOutbox(first_store), SQLitePublicationOutbox(second_store)
    first = EVMNonceCoordinator(first_store)
    second = EVMNonceCoordinator(second_store)
    assert first_outbox.claim_processing(first_id)
    assert second_outbox.claim_processing(second_id)
    barrier = Barrier(2)

    def reserve(coordinator, publication_id, sender):
        barrier.wait()
        return coordinator.reserve(publication_id, NETWORK, sender, 7)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(reserve, first, first_id, SENDER)
            b = pool.submit(reserve, second, second_id, SENDER.upper().replace("0X", "0x"))
            one, two = a.result(), b.result()
        assert {one[0], two[0]} == {7, 8}
        assert one[1] != two[1]
        assert first.reserve(first_id, NETWORK, SENDER, 7) == one
        assert second.reserve(second_id, NETWORK, SENDER, 7) == two
    finally:
        first_store.close()
        second_store.close()


def test_two_processes_reserve_distinct_nonces_for_one_signer(tmp_path):
    path = tmp_path / "processes.sqlite3"
    first_id, second_id, _ = _requests(path)
    context = get_context("spawn")
    start = context.Event()
    output = context.Queue()
    processes = [
        context.Process(target=_reserve_in_process, args=(path, publication_id, start, output))
        for publication_id in (first_id, second_id)
    ]
    for process in processes:
        process.start()
    start.set()
    try:
        assert {output.get(timeout=20), output.get(timeout=20)} == {4, 5}
    finally:
        for process in processes:
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)
    assert all(process.exitcode == 0 for process in processes)


def test_two_contract_targets_share_chain_nonce_scope(tmp_path):
    path = tmp_path / "same-chain.sqlite3"
    store = Store(path)
    try:
        store.create_animal("cow", "tag", "secret")
        event = store.append_animal_event("cow", "WEIGHT_RECORDED", {"weight_kg": 420}, 1)
        outbox = SQLitePublicationOutbox(store)
        first_network = "evm-local-31337-0x" + "11" * 20
        second_network = "evm-local-31337-0x" + "22" * 20
        first = outbox.enqueue_event(event.event_id, chain="local", destination="evm-registry", network=first_network)
        second = outbox.enqueue_event(event.event_id, chain="local", destination="evm-registry", network=second_network)
        assert outbox.claim_processing(first["publication_id"])
        assert outbox.claim_processing(second["publication_id"])
        coordinator = EVMNonceCoordinator(store)
        a = coordinator.reserve(first["publication_id"], first_network, SENDER, 1,
                                nonce_scope="evm-chain-31337")
        b = coordinator.reserve(second["publication_id"], second_network, SENDER, 1,
                                nonce_scope="evm-chain-31337")
        assert (a[0], b[0]) == (1, 2)
        assert first["commitment"] == second["commitment"]
    finally:
        store.close()


@pytest.mark.parametrize("nonce_scope", [
    "evm-chain-421614-" + ("3" * 64),
    "evm-chain-84532-" + ("3" * 64),
])
def test_evm_submission_waits_for_lower_reserved_nonce(tmp_path, nonce_scope):
    path = tmp_path / "evm-order.sqlite3"
    first_id, second_id = _requests(path, count=2)[:2]
    store = Store(path)
    outbox = SQLitePublicationOutbox(store)
    coordinator = EVMNonceCoordinator(store)
    network = NETWORK
    try:
        assert outbox.claim_processing(first_id)
        assert outbox.claim_processing(second_id)
        first_nonce, first_token = coordinator.reserve(
            first_id, network, SENDER, 0, nonce_scope=nonce_scope,
        )
        second_nonce, second_token = coordinator.reserve(
            second_id, network, SENDER, 0, nonce_scope=nonce_scope,
        )
        assert (first_nonce, second_nonce) == (0, 1)
        sent = []

        with pytest.raises(RuntimeError, match="lower nonce"):
            coordinator.submit_in_nonce_order(
                second_id, second_nonce, second_token, lambda: 0,
                lambda: sent.append(1),
            )
        assert sent == []
        coordinator.submit_in_nonce_order(
            first_id, first_nonce, first_token, lambda: 0,
            lambda: sent.append(0),
        )
        coordinator.submit_in_nonce_order(
            second_id, second_nonce, second_token, lambda: 1,
            lambda: sent.append(1),
        )
        assert sent == [0, 1]
    finally:
        store.close()


def test_arbitrum_replays_signed_attempt_after_pending_nonce_advances(tmp_path):
    path = tmp_path / "arbitrum-replay.sqlite3"
    publication_id = _requests(path, count=1)[0]
    store = Store(path)
    outbox = SQLitePublicationOutbox(store)
    coordinator = EVMNonceCoordinator(store)
    try:
        assert outbox.claim_processing(publication_id)
        nonce, token = coordinator.reserve(
            publication_id, NETWORK, SENDER, 4,
            nonce_scope="evm-chain-421614-" + ("6" * 64),
        )
        sent = []
        result = coordinator.submit_in_nonce_order(
            publication_id, nonce, token, lambda: 5,
            lambda: sent.append("same-signed-wire"),
        )
        assert result is None
        assert sent == ["same-signed-wire"]
    finally:
        store.close()


def test_arbitrum_submission_lease_serializes_store_connections(tmp_path):
    path = tmp_path / "arbitrum-lease.sqlite3"
    first_id, second_id = _requests(path, count=2)[:2]
    store, other_store = Store(path), Store(path)
    first_outbox, other_outbox = SQLitePublicationOutbox(store), SQLitePublicationOutbox(other_store)
    first_coordinator, other_coordinator = EVMNonceCoordinator(store), EVMNonceCoordinator(other_store)
    scope = "evm-chain-421614-" + ("4" * 64)
    try:
        assert first_outbox.claim_processing(first_id)
        assert first_outbox.claim_processing(second_id)
        first_nonce, first_token = first_coordinator.reserve(
            first_id, NETWORK, SENDER, 0, nonce_scope=scope,
        )
        second_nonce, second_token = first_coordinator.reserve(
            second_id, NETWORK, SENDER, 0, nonce_scope=scope,
        )
        entered, release = Event(), Event()
        sent = []

        def blocked_nonce_read():
            entered.set()
            assert release.wait(timeout=5)
            return 0

        with ThreadPoolExecutor(max_workers=1) as pool:
            first_send = pool.submit(
                first_coordinator.submit_in_nonce_order,
                first_id, first_nonce, first_token, blocked_nonce_read,
                lambda: sent.append(0),
            )
            assert entered.wait(timeout=5)
            with pytest.raises(RuntimeError, match="another EVM sender submission"):
                other_coordinator.submit_in_nonce_order(
                    second_id, second_nonce, second_token, lambda: 0,
                    lambda: sent.append(1),
                )
            assert sent == []
            release.set()
            first_send.result(timeout=5)

        other_coordinator.submit_in_nonce_order(
            second_id, second_nonce, second_token, lambda: 1,
            lambda: sent.append(1),
        )
        assert sent == [0, 1]
    finally:
        store.close()
        other_store.close()


def test_base_and_arbitrum_nonce_scopes_do_not_collide(tmp_path):
    path = tmp_path / "cross-chain-nonces.sqlite3"
    store = Store(path)
    try:
        store.create_animal("cow", "tag", "secret")
        event = store.append_animal_event("cow", "WEIGHT_RECORDED", {"weight_kg": 420}, 1)
        outbox = SQLitePublicationOutbox(store)
        base_network = "base-test-network"
        arbitrum_network = "arbitrum-test-network"
        base = outbox.enqueue_event(event.event_id, chain="base", destination="evm-registry", network=base_network)
        arbitrum = outbox.enqueue_event(event.event_id, chain="arbitrum", destination="evm-registry", network=arbitrum_network)
        assert outbox.claim_processing(base["publication_id"])
        assert outbox.claim_processing(arbitrum["publication_id"])
        coordinator = EVMNonceCoordinator(store)
        base_nonce, _ = coordinator.reserve(
            base["publication_id"], base_network, SENDER, 0,
            nonce_scope="evm-chain-84532-" + ("a" * 64),
        )
        arbitrum_nonce, _ = coordinator.reserve(
            arbitrum["publication_id"], arbitrum_network, SENDER, 0,
            nonce_scope="evm-chain-421614-" + ("a" * 64),
        )
        assert (base_nonce, arbitrum_nonce) == (0, 0)
        assert base["commitment"] == arbitrum["commitment"]
    finally:
        store.close()


def test_expired_arbitrum_submission_lease_blocks_send(tmp_path):
    path = tmp_path / "arbitrum-expired-lease.sqlite3"
    publication_id = _requests(path, count=1)[0]
    store = Store(path)
    outbox = SQLitePublicationOutbox(store)
    coordinator = EVMNonceCoordinator(store)
    scope = "evm-chain-421614-" + ("5" * 64)
    try:
        assert outbox.claim_processing(publication_id)
        nonce, token = coordinator.reserve(
            publication_id, NETWORK, SENDER, 0, nonce_scope=scope,
        )
        sent = []

        def expire_lease():
            store.connection.execute(
                "UPDATE evm_nonce_submission_locks SET expires_at=0 WHERE sender=?",
                (SENDER.lower(),),
            )
            store.connection.commit()
            return 0

        with pytest.raises(RuntimeError, match="lease expired"):
            coordinator.submit_in_nonce_order(
                publication_id, nonce, token, expire_lease,
                lambda: sent.append(0),
            )
        assert sent == []
    finally:
        store.close()


def test_expired_unpersisted_reservation_reuses_gap_after_crash(tmp_path):
    path = tmp_path / "recovery.sqlite3"
    first_id, second_id, _ = _requests(path)
    store = Store(path)
    outbox = SQLitePublicationOutbox(store)
    first_claim = outbox.claim_processing(first_id)
    assert first_claim
    coordinator = EVMNonceCoordinator(store)
    assert coordinator.reserve(first_id, NETWORK, SENDER, 3)[0] == 3
    store.connection.execute("UPDATE evm_nonce_reservations SET expires_at=0 WHERE publication_id=?", (first_id,))
    store.connection.execute("UPDATE publication_processing_claims SET expires_at=0 WHERE publication_id=?", (first_id,))
    store.connection.commit()
    store.close()

    restarted = Store(path)
    restarted_outbox = SQLitePublicationOutbox(restarted)
    assert restarted_outbox.claim_processing(second_id)
    try:
        assert EVMNonceCoordinator(restarted).reserve(second_id, NETWORK, SENDER, 3)[0] == 3
        assert restarted.connection.execute(
            "SELECT COUNT(*) FROM evm_nonce_reservations WHERE publication_id=?", (first_id,)
        ).fetchone()[0] == 0
    finally:
        restarted.close()


def test_expired_persisted_reservation_survives_restart(tmp_path):
    path = tmp_path / "persisted.sqlite3"
    first_id, second_id, _ = _requests(path)
    store = Store(path)
    outbox = SQLitePublicationOutbox(store)
    claim = outbox.claim_processing(first_id)
    assert claim
    coordinator = EVMNonceCoordinator(store)
    nonce, token = coordinator.reserve(first_id, NETWORK, SENDER, 9)
    outbox.prepare_publication_attempt(
        first_id,
        adapter_id="evm-rpc",
        transaction_id="0x" + "cd" * 32,
        payload=b"signed EVM transaction",
        metadata={"nonce": nonce, "nonce_reservation_token": token},
        claim_token=claim,
    )
    store.connection.execute("UPDATE evm_nonce_reservations SET expires_at=0 WHERE publication_id=?", (first_id,))
    store.connection.execute("UPDATE publication_processing_claims SET expires_at=0 WHERE publication_id=?", (first_id,))
    store.connection.commit()
    store.close()

    restarted = Store(path)
    restarted_outbox = SQLitePublicationOutbox(restarted)
    assert restarted_outbox.claim_processing(second_id)
    try:
        assert EVMNonceCoordinator(restarted).reserve(second_id, NETWORK, SENDER, 9)[0] == 10
        assert restarted.connection.execute(
            "SELECT token FROM evm_nonce_reservations WHERE publication_id=?", (first_id,)
        ).fetchone()[0] == token
    finally:
        restarted.close()


def test_live_claim_protects_expired_unpersisted_reservation(tmp_path):
    path = tmp_path / "live-claim.sqlite3"
    first_id, second_id, _ = _requests(path)
    store = Store(path)
    outbox = SQLitePublicationOutbox(store)
    assert outbox.claim_processing(first_id)
    assert outbox.claim_processing(second_id)
    coordinator = EVMNonceCoordinator(store)
    assert coordinator.reserve(first_id, NETWORK, SENDER, 1)[0] == 1
    store.connection.execute("UPDATE evm_nonce_reservations SET expires_at=0 WHERE publication_id=?", (first_id,))
    store.connection.commit()
    try:
        assert coordinator.reserve(second_id, NETWORK, SENDER, 1)[0] == 2
    finally:
        store.close()


def test_reservation_rejects_missing_claim_wrong_network_and_bad_inputs(tmp_path):
    path = tmp_path / "reject.sqlite3"
    publication_id, _, _ = _requests(path)
    store = Store(path)
    SQLitePublicationOutbox(store)
    coordinator = EVMNonceCoordinator(store)
    try:
        with pytest.raises(RuntimeError, match="claim"):
            coordinator.reserve(publication_id, NETWORK, SENDER, 0)
        assert SQLitePublicationOutbox(store).claim_processing(publication_id)
        with pytest.raises(ValueError, match="network"):
            coordinator.reserve(publication_id, "other-network", SENDER, 0)
        with pytest.raises(ValueError, match="sender"):
            coordinator.reserve(publication_id, NETWORK, "not-an-address", 0)
        with pytest.raises(ValueError, match="pending_nonce"):
            coordinator.reserve(publication_id, NETWORK, SENDER, -1)
    finally:
        store.close()
