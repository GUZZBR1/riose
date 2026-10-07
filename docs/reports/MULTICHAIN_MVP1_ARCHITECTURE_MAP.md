# Multichain Mini-MVP 1: architecture map

Base: `b2de3a9a58f911e24dc9a8395717f520542282b3` (`GUZZBR1/riose`, `main`).
The isolated worktree `riose-multichain-mvp1` starts at this exact commit. Git fetch
could not resolve `github.com`; repository metadata and the base commit were also
verified through the GitHub connector. No remote branch was changed.

## Existing components

| Current component | Responsibility | Generic already? | Solana-specific? | Decision |
|---|---|---|---|---|
| `domain/identity.py`: `canonical_event`, `event_digest`, `append_event`, `verify_event_chain` | Event V1 canonical bytes, SHA-256 chain, local SQLite append/verification | Yes; contains no chain imports or fields | No | Keep unchanged; protect with golden and offline tests |
| `domain/commitment.py`: `CommitmentV1`, `create_commitment_v1`, `public_envelope` | Deterministic digest from verified source digest and persisted subject reference | Yes; no chain parameter | No | Reuse; make the event binding shared across targets |
| `domain/publication_state.py`: `PublicationState`, `require_transition` | Publication lifecycle states and legal transitions | Mostly | No | Reuse, extend only if evidence requires a state |
| `adapters/persistence/publication_outbox.py`: `publication_requests`, `publication_outbox`, `publication_attempts`, `publication_receipts` | Durable opt-in per-event target, queue, retry attempt, receipt journal | Request/outbox are target-shaped; attempt and receipt code are not | Yes: base58 signatures, signed Solana bytes, block height, slot and literal `solana-memo` | Extend with shared event commitment and an adapter-neutral contract; preserve Solana attempt data as adapter metadata |
| `adapters/solana_memo.py`: `SolanaMemoConfig`, `SolanaMemoClient` | Solana cluster selection, Memo transaction prepare/submit/verify | No | Yes | Keep as current concrete adapter; add a thin conforming boundary only where required |
| `publication_cli.py` and `cli.py` | Queue/status/send/reconcile operations | Queue/status are partly generic | Send/reconcile is Solana-only | Keep current CLI behavior; keep chain-specific configuration outside Event V1 |
| `adapters/persistence/sqlite_store.py`: `Store` | Shared SQLite connection, WAL, process-local lock and local event/behavior persistence | Yes | No | Reuse; publication writes continue using `BEGIN IMMEDIATE` and the same connection/lock |
| `tests/livestock_tracking/test_event_contract.py`, `test_commitment_privacy.py`, `test_publication_outbox.py`, `test_solana_memo.py`, `test_event_chain_concurrency.py` | Canonicalization, commitment, atomic queue, receipts, adapter behavior, write serialization | Partial | Solana test file is specific | Extend tests at current boundaries; do not duplicate domain logic |

## Findings before migration

- No common chain adapter protocol or normalized chain-receipt value type exists.
- `enqueue_event` generates a fresh random `subject_ref` per target request. Therefore two target rows for one Event V1 can currently receive different commitments, contrary to a shared multichain commitment.
- `publication_requests` already models separate target state rows and the outbox isolates scheduling by `publication_id`; this is the reusable basis for partial failure isolation.
- The attempt and receipt schema is materially Solana-specific (`signature`, signed wire transaction, last valid block height, slot, base58 validation, fixed `solana-memo` receipt adapter). Those fields must remain adapter metadata and must not become Event V1 fields.
- Event creation, local persistence and publication enqueue are already separate; `append_event_and_enqueue` is an explicit optional atomic convenience. Network access is not needed for event validity.
- No separate retry system exists; retries/recovery are per publication request using the persisted attempt and exact signature. Ambiguous send outcomes are `UNKNOWN`, then reconciled without creating a new attempt.

## Direction

Keep Event V1 and the canonical commitment implementation chain-neutral. Persist one
commitment binding per event, then associate independent target requests with that
binding. Define only the adapter operations needed by the current publication flow;
map Solana receipt identifiers and block location into optional generic fields while
retaining protocol-specific details in adapter metadata. Do not create EVM adapters,
contracts, or speculative capability registries in this phase.

## Resulting architecture

- Event V1, local append, and commitment/envelope generation remain unchanged and
  contain no chain selection.
- `domain/publication.py` adds `PreparedPublication`, `ChainReceipt`, and the
  narrow `ChainAdapter` protocol (`prepare`, `submit`, `get_receipt`, `verify`,
  `healthcheck`). The adapter consumes the existing public commitment envelope.
- `canonical_event_commitments` stores one immutable local commitment binding per
  event. Every target request reuses it; inconsistent legacy bindings fail closed.
- `publication_requests` and the outbox keep independent chain, adapter, network,
  lifecycle, and retry identity per target. A stable digest of `(chain, adapter)`
  is the internal target key; outputs retain the adapter identifier.
- Attempts persist a generic transaction identifier, opaque payload, and JSON
  metadata. Receipts persist normalized chain, transaction identifier, block
  reference, timestamps, safe error code, retry metadata, and evidence status.
  Solana signature, signed transaction, slot, and block-height values remain
  available through compatibility fields or metadata.
- `SolanaMemoAdapter` conforms to the protocol over the existing client. The
  existing CLI send/reconcile path remains Solana-specific; generic persistence
  is not yet wired to a multi-adapter execution service.
- The state machine adds `RETRYABLE`, which keeps a target pending in the durable
  outbox while allowing another attempt. Stale attempt observations cannot mutate
  the active target; terminal `VERIFIED` or `REJECTED` completes only that target.

No EVM adapter or network call is part of this migration. The code establishes
shared domain and persistence boundaries for a later adapter-specific phase.
