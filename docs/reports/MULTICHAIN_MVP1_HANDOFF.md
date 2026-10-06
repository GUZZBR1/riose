# RIOSE Multichain Mini-MVP 1: architecture migration handoff

## Governed scope

- Canonical base: `b2de3a9a58f911e24dc9a8395717f520542282b3`
- Work branch: `multichain/mvp1-core-migration`
- This phase changes local architecture and persistence only. It does not add an
  EVM adapter, Solidity, or a chain call.
- `REAL_ON_CHAIN` remains `UNVERIFIED`; field validation was not performed.
- No push, pull request, merge, or main-branch update was performed.

## Before and after

Before, Event V1 and `CommitmentV1` were chain-neutral, but each queued target
could generate a different subject reference and commitment. Publication requests
were already independent rows, while attempts, receipts, and send/reconcile logic
were shaped around Solana signatures and transactions. There was no common adapter
contract.

After, one immutable local commitment binding is stored per event and reused by
every target. Targets have independent chain, adapter, network, status, attempts,
and receipts. Attempts store an opaque payload and transaction identifier with
adapter metadata. Receipts expose normalized chain, transaction identifier, block
reference, timestamps, safe error code, retry metadata, and evidence status. The
existing Solana client is wrapped by `SolanaMemoAdapter`; Event V1 remains untouched.

The current CLI send/reconcile route remains Solana-specific by design because the
mission excludes a full Solana migration. The shared adapter protocol and outbox
are ready for later adapter integrations, while a generic execution dispatcher
and CLI routing remain Mini-MVP 2 work. The tests do not claim an EVM adapter or
real network behavior.

## Reuse and anti-duplication record

- **Reused:** Event V1/hash chain, `CommitmentV1`, public envelope, SQLite `Store`,
  outbox, publication lifecycle, and Solana Memo client.
- **Extended:** one-per-event canonical commitment binding; per-target chain and
  adapter identity; generic attempt/receipt fields; `RETRYABLE`; Solana adapter
  conformance; target selection for queue/status.
- **Created:** the small `ChainAdapter`, `PreparedPublication`, and `ChainReceipt`
  domain boundary, plus architecture, DoD, and handoff reports.
- **Avoided:** a second event/commitment/store/queue; chain-specific event fields;
  per-chain transaction columns; Base/Arbitrum implementations; speculative
  capability registries.

The repository search and architecture map established that no equivalent shared
adapter contract or per-event canonical binding existed before this change. The
existing event and commitment implementations were reused directly.

## Migration and failure handling

- Legacy Solana attempts and receipts are migrated transactionally while retaining
  their signature, signed transaction, expiry height, slot, and receipt history.
  The migration rejects orphan/mismatched journal relationships and mismatched
  normalized transaction IDs rather than dropping or miscorrelating evidence.
- Migration retries the chain backfill after interruption and restores SQLite
  foreign-key enforcement even when it cannot acquire the write lock.
- A target moves independently. `RETRYABLE` allows a new attempt; observations
  from older attempts cannot terminate or rewrite the active attempt. Submission
  and confirmation times are scoped to the attempt that produced them.
- Ambiguous send recovery remains the Solana CLI's existing exact-signature
  reconciliation path. A crash after a generic attempt is persisted but before
  submission has no generic recovery dispatcher yet; keep this in Mini-MVP 2.

## Red-team review

The independent review found and this branch corrected:

1. Ambiguous target/idempotency key construction for separator-containing names
   and long identifiers: use a stable digest of the chain and adapter pair.
2. Legacy journal rows that could be dropped or cross-linked during table rebuild:
   preflight ownership and verify row counts before dropping source tables.
3. Populated normalized receipt fields being overwritten during migration: preserve
   them, and reject a transaction ID that conflicts with its Solana signature.
4. Old-attempt observations affecting a newer retry and timestamps leaking across
   attempts: reject stale aggregate transitions and scope receipt lookups by attempt.
5. A failed SQLite migration lock leaving foreign keys disabled: always restore the
   connection setting in `finally`.

The final read-only red-team pass found no remaining P1/P2 findings. No EVM or
real-chain evidence was reviewed or claimed.

## Verification record

Focused migration suite:

```text
uv run --offline --extra dev --extra solana pytest -q \
  tests/livestock_tracking/test_publication_outbox.py \
  tests/livestock_tracking/test_solana_memo.py \
  tests/livestock_tracking/test_publication_cli.py \
  tests/livestock_tracking/test_event_contract.py \
  tests/livestock_tracking/test_commitment_privacy.py \
  tests/livestock_tracking/test_event_chain_concurrency.py
63 passed
```

Full regression and clean-checkout reproduction will be recorded here after the
final commits are tested.

Current source-worktree verification:

```text
uv run --offline --extra dev --extra solana pytest -q
763 passed, 7 skipped, 1 existing Starlette/httpx deprecation warning

uv run --offline python -m compileall -q src
passed

uv lock --check --offline
passed; no dependency or lockfile changes

git diff --check
passed
```

The repository exposes no configured lint/type-check target and no `ruff`,
`mypy`, or `pyright` executable was available in the checkout.

## Mini-MVP 2 handoff

1. Add a shared execution dispatcher that routes a request to a registered
   `ChainAdapter`, persists the prepared payload before submission, and records
   normalized receipts through the existing outbox.
2. Adapt the current Solana send/reconcile CLI to that dispatcher without changing
   its commitment encoding or existing recovery guarantees.
3. Add fake-adapter end-to-end dispatcher tests for submit, ambiguous outcome,
   confirmation, failed verification, retries, restart recovery, and per-target
   isolation before implementing any EVM adapter.
4. Define safe recovery for a crash between durable `PREPARED` and network submit;
   do not retry an ambiguous transaction unless adapter evidence proves it is safe.
5. Only after that shared route passes review, add Base and Arbitrum adapters using
   one EVM implementation/configuration path. Verify any real-chain claim from
   independent transaction evidence; until then retain `REAL_ON_CHAIN=UNVERIFIED`.
