# Publication Architecture Before SC-1

Source inspected: fork ref `fork/main`, commit `b2ddf11098ecd87b954bf97af26f8ecb8862b58a`, tree `2ee3930e5ae6b96cef6134840151c17f7c85f0e4`. This describes code, not public-chain deployment.

## Reused capabilities

| Capability | Existing implementation | SC-1 disposition |
|---|---|---|
| Event V1 identity | `domain/identity.py`: canonical event serialization/digest, per-animal hash chain, `append_event`, prefix verification | REUSE; preserve bytes and hash behavior |
| Commitment V1 | `domain/commitment.py`: domain-separated SHA-256 over source digest and local random subject reference; `canonical_event_commitments` persists one immutable commitment per event | REUSE; never recalculate during recovery |
| Persistence | `adapters/persistence/sqlite_store.py`: one SQLite `Store`, WAL, foreign keys, `synchronous=FULL`, 5-second busy timeout, `BEGIN IMMEDIATE` for event writes | REUSE |
| Publication queue | `adapters/persistence/publication_outbox.py`: same Store connection; atomic request/outbox insert; target-scoped unique request/idempotency keys | REUSE and EXTEND in place |
| Attempts and receipts | Existing generic `publication_attempts` and append-only `publication_receipts`; signed payload is persisted before submit; receipts correlate to target, attempt, transaction and commitment | REUSE; do not add a second journal |
| Dispatcher | `application/publication_dispatcher.py`: one chain-neutral `PublicationDispatcher`, durable per-request claim/heartbeat, adapter routing, prepared replay and receipt reconciliation | REUSE and EXTEND in place |
| Adapter boundary | `domain/publication.py`: one `ChainAdapter` protocol and normalized `PreparedPublication`/`ChainReceipt` values | REUSE |
| Solana | `adapters/solana_memo.py`: explicit cluster identity, signed Memo transaction, transaction bytes + signature + block-height metadata, receipt lookup by signature | REUSE; do not use real funds or public transaction submission |
| EVM | `adapters/evm_registry.py` + `adapters/evm_config.py`: one generic EVM registry adapter with explicit chain/deployment identity; Base and Arbitrum are configurations of this adapter | REUSE; no chain-specific duplicate adapter |
| Nonce coordination | `adapters/persistence/evm_nonce.py`: persisted reservation, chain/sender nonce scope, processing claims and expiring sender submission lock | REUSE; extend shared behavior if tests show Base gap |

## Existing state and recovery shape

The durable request is target-specific (`chain`, `network`, adapter id); the canonical event commitment is shared across targets. Each target has independent attempts, receipts, status and completion time. A failure on one target does not need to mutate sibling target state. The same SQLite Store contains event, commitment, outbox, claim, attempt, receipt and nonce records.

The dispatcher persists an adapter-prepared payload before RPC submission. When submission is ambiguous, it retains that exact payload and transaction id. `process` and `reconcile` can query the persisted transaction and replay the exact signed bytes rather than prepare a new transaction while the same attempt remains uncertain. `CONFIRMED` is durably recorded before a second verification query; a later invocation can resume from `CONFIRMED`.

## Observed limits before changes

- The state model is evidence-oriented but does not have a distinct `SUBMITTING` state; an in-flight submission remains `PREPARED` until an RPC response or receipt observation is persisted.
- No bounded retry count, exponential backoff, jitter, or due-time gate was found in the publication code. `available_at` is initialized when queued and `list_pending` does not filter by current time.
- Adapter health/preparation errors propagate while leaving the request `QUEUED`; repeated invocations can retry with no durable schedule or cap.
- Ambiguous send errors correctly avoid claiming failure, but `UNKNOWN` recovery can replay the same signed payload. The semantic safety depends on exact payload identity and the chain adapter/RPC behavior; it does not prove exactly-once processing.
- `RETRYABLE` is accepted only when an adapter receipt explicitly sets `safe_to_retry=true`; the next `process` may create another signed attempt immediately, with no bounded policy.
- EVM nonce reservations are shared by chain id + genesis + sender, but only chain id `421614` (Arbitrum Sepolia) uses `submit_in_nonce_order`. Other EVM configurations, including Base, send without the coordinator’s per-sender submission lock. Reservation uniqueness alone does not establish ordered submission.
- Existing documentation explicitly says persisted `PREPARED` transaction resubmission after unobserved signature/RPC ambiguity was not implemented or validated, while current code does replay the exact persisted payload. SC-1 must replace this stale ambiguity with tests and precise claims.
- Current Solana keypair loader reads JSON bytes but does not enforce the file ownership/permission/no-symlink checks used by the EVM key loader. This corresponds to the named `SEC-SOLANA-001` concern and remains a SC-2 observation; this mission must not weaken the loader or use real funds.

## Anti-duplication decision

No new Event model, Commitment, outbox, dispatcher, receipt model, or blockchain architecture is justified. Required reliability changes should fit the existing `publication_outbox`, state transitions, dispatcher, adapters, and tests. A small shared policy value/helper is acceptable only if the existing modules cannot express the bounded scheduling semantics clearly.
