"""Opt-in CLI commands for durable publication processing."""

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
    queue.add_argument("--chain", help="chain identifier; defaults from the destination adapter")
    queue.add_argument("--network", help="explicit network identifier")
    queue.add_argument("--evm-config", help="explicit EVM deployment JSON; derives chain and network")
    queue.add_argument("--idempotency-key")
    status = actions.add_parser("status", help="show a local publication request")
    status.add_argument("--db", required=True)
    status.add_argument("--publication-id", required=True)
    for name, help_text in (
        ("send", "prepare, persist, submit, and observe one publication"),
        ("process", "process a queued publication or resume its persisted attempt"),
        ("reconcile", "observe or safely resend the exact persisted attempt"),
    ):
        command = actions.add_parser(name, help=help_text)
        command.add_argument("--db", required=True)
        command.add_argument("--publication-id", required=True)
        command.add_argument("--rpc-url", help="explicit Solana RPC URL")
        command.add_argument("--expected-genesis-hash", help="expected Solana cluster genesis hash")
        command.add_argument("--evm-config", help="explicit EVM deployment JSON")
        if name != "reconcile":
            command.add_argument("--keypair", help="required only when preparing a new Solana attempt")
            command.add_argument("--evm-key-file", help="restricted local key file for a new EVM attempt")


def run_publication_command(args: argparse.Namespace) -> int:
    from .adapters.persistence import Store
    from .adapters.persistence.publication_outbox import SQLitePublicationOutbox

    store = Store(args.db)
    outbox = SQLitePublicationOutbox(store)
    try:
        if args.publication_action == "queue":
            if args.evm_config:
                from .adapters.evm_config import EVMNetworkConfig
                config = EVMNetworkConfig.from_json_file(args.evm_config)
                if args.network is not None or args.chain is not None or args.destination != "solana-memo":
                    raise ValueError("EVM config determines destination, chain, and network")
                destination, chain, network = "evm-registry", config.chain, config.network_id
            else:
                if not args.network:
                    raise ValueError("an explicit network or EVM config is required")
                destination, chain, network = args.destination, args.chain, args.network
            request = outbox.enqueue_event(
                args.event_id, destination=destination, network=network,
                chain=chain, idempotency_key=args.idempotency_key,
            )
            print(json.dumps(_public_status(request, outbox), sort_keys=True))
            return 0
        if args.publication_action == "status":
            request = outbox.get(args.publication_id)
            if request is None:
                raise ValueError("publication request was not found")
            print(json.dumps({**_public_status(request, outbox), "receipts": outbox.receipts(args.publication_id)}, sort_keys=True))
            return 0
        if args.publication_action in {"send", "process", "reconcile"}:
            return _send_or_reconcile(args, outbox)
        return 2
    finally:
        store.close()


def _send_or_reconcile(args: argparse.Namespace, outbox: object) -> int:
    from .application.publication_dispatcher import PublicationDispatcher
    from .domain.publication_state import PublicationState

    request = outbox.get(args.publication_id)
    if request is None:
        raise ValueError("publication request was not found")
    state = PublicationState(request["status"])
    if args.publication_action == "send" and state is not PublicationState.QUEUED:
        raise ValueError("request is not QUEUED; use process or reconcile")
    preparing = args.publication_action != "reconcile" and state in {
        PublicationState.QUEUED, PublicationState.RETRYABLE
    }
    if request["adapter_id"] == "solana-memo":
        from .adapters.solana_memo import SolanaMemoAdapter, SolanaMemoClient, SolanaMemoConfig, load_keypair
        if not args.rpc_url or not args.expected_genesis_hash or args.evm_config:
            raise ValueError("Solana RPC URL and expected genesis hash are required")
        config = SolanaMemoConfig(args.rpc_url, args.expected_genesis_hash)
        if (request["chain"], request["network"]) != ("solana", config.network_id):
            raise ValueError("configured network does not match the queued request")
        keypair_path = getattr(args, "keypair", None)
        if preparing and not keypair_path:
            raise ValueError("a keypair is required to prepare a new attempt")
        signer = load_keypair(keypair_path) if preparing else None
        adapter = SolanaMemoAdapter(SolanaMemoClient(config), signer)
    elif request["adapter_id"] == "evm-registry":
        from .adapters.evm_config import EVMNetworkConfig
        from .adapters.evm_registry import EVMRegistryAdapter, load_evm_signer
        from .adapters.persistence.evm_nonce import EVMNonceCoordinator
        if not args.evm_config or args.rpc_url or args.expected_genesis_hash:
            raise ValueError("an explicit EVM deployment config is required")
        config = EVMNetworkConfig.from_json_file(args.evm_config)
        if (request["chain"], request["network"]) != (config.chain, config.network_id):
            raise ValueError("configured network does not match the queued request")
        key_file = getattr(args, "evm_key_file", None)
        if preparing and not key_file:
            raise ValueError("an EVM key file is required to prepare a new attempt")
        signer = load_evm_signer(key_file) if preparing else None
        adapter = EVMRegistryAdapter(
            config, signer=signer,
            nonce_coordinator=EVMNonceCoordinator(outbox.store),
            publication_id=args.publication_id,
        )
    else:
        raise ValueError("no supported adapter matches the queued target")
    dispatcher = PublicationDispatcher(outbox, [adapter])
    result = (
        dispatcher.reconcile(args.publication_id)
        if args.publication_action == "reconcile"
        else dispatcher.process(args.publication_id)
    )
    print(json.dumps({
        **_public_status(result, outbox),
        "receipts": outbox.receipts(args.publication_id),
    }, sort_keys=True))
    return 0 if result["status"] == PublicationState.VERIFIED.value else 3


def _public_status(request: dict[str, object], outbox: object | None = None) -> dict[str, object]:
    result = {
        "publication_id": request["publication_id"],
        "event_id": request["event_id"],
        "chain": request.get("chain", str(request["destination"]).split("-", 1)[0]),
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
