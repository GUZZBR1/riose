"""Narrow CLI commands for explicitly configured local publication."""

from __future__ import annotations

import argparse
import json


def add_publication_commands(commands: argparse._SubParsersAction) -> None:
    publication = commands.add_parser("publication", help="inspect or publish a private commitment (opt-in)")
    actions = publication.add_subparsers(dest="publication_action", required=True)
    queue = actions.add_parser("queue", help="atomically queue an existing verified event")
    queue.add_argument("--db", required=True)
    queue.add_argument("--event-id", required=True, type=int)
    queue.add_argument("--destination", default="solana-memo")
    queue.add_argument("--network", required=True, help="explicit identifier including the expected cluster genesis hash")
    queue.add_argument("--idempotency-key")
    status = actions.add_parser("status", help="show a local publication request")
    status.add_argument("--db", required=True)
    status.add_argument("--publication-id", required=True)
    send = actions.add_parser("send", help="sign, persist, and submit one devnet/testnet Memo")
    send.add_argument("--db", required=True)
    send.add_argument("--publication-id", required=True)
    send.add_argument("--rpc-url", required=True)
    send.add_argument("--expected-genesis-hash", required=True)
    send.add_argument("--keypair", required=True)
    reconcile = actions.add_parser("reconcile", help="query the exact persisted signature; never creates a new attempt")
    reconcile.add_argument("--db", required=True)
    reconcile.add_argument("--publication-id", required=True)
    reconcile.add_argument("--rpc-url", required=True)
    reconcile.add_argument("--expected-genesis-hash", required=True)


def run_publication_command(args: argparse.Namespace) -> int:
    from .adapters.persistence import Store
    from .adapters.persistence.publication_outbox import SQLitePublicationOutbox

    store = Store(args.db)
    outbox = SQLitePublicationOutbox(store)
    try:
        if args.publication_action == "queue":
            request = outbox.enqueue_event(
                args.event_id, destination=args.destination, network=args.network,
                idempotency_key=args.idempotency_key,
            )
            print(json.dumps(_public_status(request, outbox), sort_keys=True))
            return 0
        if args.publication_action == "status":
            request = outbox.get(args.publication_id)
            if request is None:
                raise ValueError("publication request was not found")
            print(json.dumps({**_public_status(request, outbox), "receipts": outbox.receipts(args.publication_id)}, sort_keys=True))
            return 0
        if args.publication_action in {"send", "reconcile"}:
            return _send_or_reconcile(args, outbox)
        return 2
    finally:
        store.close()


def _send_or_reconcile(args: argparse.Namespace, outbox: object) -> int:
    from .adapters.solana_memo import SolanaMemoClient, SolanaMemoConfig, SolanaRpcError, load_keypair
    from .domain.privacy import parse_public_envelope_json
    from .domain.publication_state import PublicationState

    request = outbox.get(args.publication_id)
    if request is None:
        raise ValueError("publication request was not found")
    config = SolanaMemoConfig(args.rpc_url, args.expected_genesis_hash)
    if request["network"] != config.network_id or request["destination"] != "solana-memo":
        raise ValueError("configured network does not match the queued request")
    client = SolanaMemoClient(config)
    evidence_status = getattr(client, "evidence_status", "ASSUMED")
    if not outbox.verify_local_binding(args.publication_id):
        raise ValueError("local event prefix or commitment binding failed verification")

    if args.publication_action == "send":
        if PublicationState(request["status"]) is not PublicationState.QUEUED:
            raise ValueError("request is not QUEUED; use reconcile to inspect its persisted attempt")
        keypair = load_keypair(args.keypair)
        envelope = parse_public_envelope_json(request["envelope"])
        signed_tx, signature, last_valid_height = client.prepare(envelope, keypair)
        attempt = outbox.prepare_attempt(
            args.publication_id, signature=signature, signed_transaction=signed_tx,
            last_valid_block_height=last_valid_height,
        )
        try:
            client.submit(attempt["signed_transaction"], attempt["signature"])
            outbox.record_observation(args.publication_id, attempt["attempt_id"], state=PublicationState.RPC_ACCEPTED,
                                      evidence_status=evidence_status)
        except SolanaRpcError:
            outbox.record_observation(args.publication_id, attempt["attempt_id"], state=PublicationState.UNKNOWN,
                                      reason_code="RPC_UNAVAILABLE", evidence_status=evidence_status)
            print(json.dumps({**_public_status(outbox.get(args.publication_id), outbox), "recovery": "query persisted signature; no new transaction was created"}, sort_keys=True))
            return 3
    attempt = outbox.latest_attempt(args.publication_id)
    if attempt is None:
        raise ValueError("no signed attempt exists to reconcile")
    envelope = parse_public_envelope_json(request["envelope"])
    try:
        matched, slot = client.verify(attempt["signature"], envelope)
    except SolanaRpcError:
        state = PublicationState(request["status"])
        if state in {PublicationState.PREPARED, PublicationState.RPC_ACCEPTED}:
            outbox.record_observation(args.publication_id, attempt["attempt_id"], state=PublicationState.UNKNOWN,
                                      reason_code="RPC_UNAVAILABLE", evidence_status=evidence_status)
        print(json.dumps({**_public_status(outbox.get(args.publication_id), outbox), "recovery": "retry reconciliation later"}, sort_keys=True))
        return 3
    current = PublicationState(outbox.get(args.publication_id)["status"])
    if matched is None:
        if current in {PublicationState.PREPARED, PublicationState.RPC_ACCEPTED}:
            outbox.record_observation(args.publication_id, attempt["attempt_id"], state=PublicationState.UNKNOWN,
                                      reason_code="NOT_OBSERVED", evidence_status=evidence_status)
    elif matched:
        if current in {PublicationState.PREPARED, PublicationState.RPC_ACCEPTED, PublicationState.UNKNOWN}:
            outbox.record_observation(args.publication_id, attempt["attempt_id"], state=PublicationState.CONFIRMED,
                                      slot=slot, evidence_status=evidence_status)
            current = PublicationState.CONFIRMED
        if current is PublicationState.CONFIRMED:
            outbox.record_observation(args.publication_id, attempt["attempt_id"], state=PublicationState.VERIFIED,
                                      slot=slot, evidence_status=evidence_status)
    else:
        if current is not PublicationState.REJECTED:
            outbox.record_observation(args.publication_id, attempt["attempt_id"], state=PublicationState.REJECTED,
                                      slot=slot, reason_code="TRANSACTION_OR_MEMO_MISMATCH",
                                      evidence_status=evidence_status)
    print(json.dumps({**_public_status(outbox.get(args.publication_id), outbox), "receipts": outbox.receipts(args.publication_id)}, sort_keys=True))
    return 0 if matched else 3


def _public_status(request: dict[str, object], outbox: object | None = None) -> dict[str, object]:
    result = {
        "publication_id": request["publication_id"],
        "event_id": request["event_id"],
        "destination": request["destination"],
        "network": request["network"],
        "commitment": request["commitment"],
        "status": request["status"],
    }
    if outbox is not None:
        receipts = outbox.receipts(request["publication_id"])
        local_valid = outbox.verify_local_binding(request["publication_id"])
        validated_receipt = lambda item: item["evidence_status"] == "VALIDATED"
        result["verification"] = {
            "LOCAL_HASH_VALID": local_valid,
            "RECEIPT_PRESENT": bool(receipts),
            "CHAIN_CONFIRMED": any(item["state"] in {"CONFIRMED", "VERIFIED"} and validated_receipt(item) for item in receipts),
            "CHAIN_VERIFIED": local_valid and request["status"] == "VERIFIED" and any(item["state"] == "VERIFIED" and validated_receipt(item) for item in receipts),
            "CHAIN_OBSERVED_ASSUMED": any(item["state"] in {"CONFIRMED", "VERIFIED"} and item["evidence_status"] == "ASSUMED" for item in receipts),
        }
    return result
