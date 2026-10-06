# MINI-MVP 3 — Blockchain & Publication

## Status

Implementation and software validation complete with external-chain limitations. Product boundary: publication is an opt-in product module; local Event Contract V1 remains authoritative for event identity and provenance. Blockchain publication is useful only when an external party needs a timestamped public digest; it does not validate animal facts, signer identity, ownership, or field truth. Outbox, adapters, receipts, verification, and recovery are optional; offline local use remains functional without network configuration.

## Workspace Reconciliation

- REMOTE_NAME: `fork` (URL identifies `GUZZBR1/riose`; `origin` is `santleme/riose`)
- REMOTE_URL: `https://github.com/GUZZBR1/riose.git`
- REMOTE_MAIN_SHA: `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed` (cached ref `fork/main`; live fetch unavailable)
- EXPECTED_CHECKPOINT: `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`
- PRE_RECONCILIATION_HEAD: `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`
- ORIGINAL_BASE: `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`
- MERGE_BASE: `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`
- DIRTY_STATE_BEFORE: clean in `mini-mvp/blockchain-publication`
- RECOVERY_REF: N/A for this clean worktree; adjacent dirty historical demo preserved at `/home/gusta/.codex/recovery/mini-mvp3-reconcile-20261006-blockchain-hackathon-dirty` (branch `research/blockchain-hackathon-demo`, pre-reconciliation HEAD `3bdb712dbfbe10d9130a9d49831b7476c79534dc`)
- RECONCILIATION_CLASS: A — CURRENT_BASE_CONFIRMED (local refs and ancestry match; live remote freshness unverified)
- RECONCILIATION_ACTION: kept isolated worktree on approved base; no checkout/reset/rebase or changes to main/preservation refs. Safe fetch failed with DNS resolution error for `github.com`.
- POST_RECONCILIATION_BASE: `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`
- POST_RECONCILIATION_HEAD: `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`
- CANONICAL_CAPABILITIES_REUSED: Event Contract V1, SHA-256 event chain, SQLite Store and its transaction/lock boundary, evidence provenance semantics.
- LOCAL_CHANGES_SUPERSEDED: no changes on this Mini-MVP branch at checkpoint. Existing historical hackathon work is preserved separately and not integrated.
- CONFLICTS_RESOLVED: none
- TESTS_AFTER_RECONCILIATION: baseline at approved base: `uv run pytest -q` — 617 passed, 7 skipped.

## Design and implementation plan

1. Freeze Event V1 bytes and digest semantics; add a versioned Commitment V1 using an opaque random subject reference persisted once and a minimal public envelope. Preserve the historical golden vector.
2. Add publication persistence to the existing Store only. Insert event binding and outbox intent in one SQLite transaction; never introduce a second event identity or persistence model.
3. Make idempotency durable. Persist exact request envelope and attempt identity before network I/O; ambiguous sends reconcile by the same signature and are never blindly resubmitted. Append correlated receipts.
4. Keep publication disabled by default. Provide a narrow CLI for local request inspection and opt-in send/reconcile; no default API route or network behavior. Require explicit network configuration and a verified Solana cluster genesis identity.
5. Implement a Solana memo adapter behind an optional dependency, use versioned message signing bytes correctly, bound RPC responses/timeouts, and separate RPC acceptance from confirmed transaction verification. Never place animal IDs, event data, subject refs, source hashes, or secrets on chain.
6. Test offline state transitions, crash recovery, duplicates, tampering, privacy, mocked adapters, CLI behavior, and real RPC only when the environment allows.

## Product classification

| Capability | Classification | Decision and reason |
|---|---|---|
| Event identity and local hash chain | CORE_PRODUCT | Reuse current Event V1 contract unchanged; this remains the canonical local record. |
| Commitment V1 and minimized envelope | OPTIONAL_PRODUCT_MODULE | Preserve exact historical format/golden vector; publication is opt-in. |
| Outbox, idempotency, durable attempts, receipts, recovery | OPTIONAL_PRODUCT_MODULE | Necessary for safe publication lifecycle; persisted additively in current Store. |
| Solana memo integration | OPTIONAL_PRODUCT_MODULE | Useful external timestamp/availability path; requires explicit configuration and confirmation. |
| Fake chain and hackathon narrative | HACKATHON_DEMO | Demo/test only; cannot imply real on-chain evidence. |
| Historical in-memory publisher, volatile retry registry | SUPERSEDED | Inadequate durability and recovery for product operations. |
| Multi-process SQLite reliability redesign | RESEARCH / out of scope | Separate Mini-MVP 5 concern; current Store lock does not establish multi-process safety. |

## Validation evidence

- Focused publication suite: 22 passed.
- Full Python suite on the implementation: 639 passed, 7 skipped, 1 existing Starlette/httpx deprecation warning (47.90 seconds).
- `uv lock --check --offline`, Python `compileall`, JSON report parsing, and `git diff --check` succeeded.
- Clean detached worktree reproduction at the implementation commit: `uv sync --offline --extra dev --extra solana` succeeded and the focused suite passed 22 tests.
- Dependency lock check and offline sync with `dev` and `solana` extras succeeded.
- Genesis identity read from Solana devnet succeeded; the funding faucet returned errors, no airdrop signature was received, and no publication transaction was submitted.
- A real on-chain transaction was not submitted. `REAL_ON_CHAIN=UNVERIFIED`; software behavior is `TESTED_SOFTWARE`, test doubles are `MOCKED`.
- Remote fetch was blocked by DNS resolution; cached `fork/main` ancestry matches the expected checkpoint, so live remote freshness remains unverified.

## Limits and next validation

This validates single-process behavior against the current SQLite Store boundary, not multi-process concurrency or production key custody. Solana RPC confirmation is evidence from the configured RPC, not independent proof. A funded, explicitly authorized devnet run is still required to claim `REAL_ON_CHAIN`.

## Red-team disposition

The implementation and tests address secret inclusion/logging, duplicate requests and sends, acceptance versus confirmation, fake evidence labels, unsupported networks, deterministic canonicalization, historical hash preservation, atomic outbox persistence, ambiguous crash recovery, receipt correlation and immutability, reuse of the existing identity architecture, public-data minimization, offline operation, main isolation, and historical-evidence preservation. Insufficient-funds behavior was not exercised against a funded live transaction; the external faucet did not fund the temporary signer. Signer parsing, endpoint validation, RPC malformed/error responses, and mock evidence were exercised in software tests. No live transaction was sent.
