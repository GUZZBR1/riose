# Multichain Mini-MVP 1: compiled Definition of Done

Each criterion must be evidenced by a test, inspection or reproducible command.

| ID | Criterion | Required evidence |
|---|---|---|
| D1 | Reconcile exact canonical base and isolated branch; capture remotes, merge-base, worktrees, dirty state and recovery ref | Git report; canonical SHA equals requested base |
| D2 | Event V1 canonicalization/hash remains chain-independent | Existing golden contract test plus no chain dependency in Event V1 |
| D3 | A persisted event commitment is reused for all publication targets; repeat calculation from identical inputs is deterministic | Tests create multiple targets for one event and compare commitment bytes/digest |
| D4 | There is a small typed chain-adapter boundary for submit/receipt/verify/health behavior, with no commitment mutation | Protocol/value contract test; adapter receives the existing commitment envelope |
| D5 | Target publication states and receipts are separate from Event V1 and independently addressable by chain/network | Schema and tests inspect multiple target rows and receipt ownership |
| D6 | A target can remain queued/pending while the local Event V1 remains valid and readable offline | No adapter/network call required for local event or enqueue; tests cover queue state |
| D7 | A failed target does not invalidate the event or mutate another target's state | Independent failure-injection test across two destinations |
| D8 | Current Solana Memo behavior and persistence compatibility remain intact | Existing Solana and outbox tests pass; legacy SQLite shape opens/continues correctly |
| D9 | SQLite write atomicity and event-chain concurrency semantics remain intact | `BEGIN IMMEDIATE` fault and concurrent writer tests pass |
| D10 | Relevant full regression and clean-checkout reproduction pass | Commands and exact counts/outputs recorded |
| D11 | Independent red-team review checks chain leakage, target duplication/idempotency, partial failures, transaction semantics and offline-first | Review findings and dispositions included in final handoff |
| D12 | Mini-MVP 2 handoff names its bounded Solana migration work and unresolved operational evidence | Final handoff document/section; no claim of real on-chain verification |

## Evidence status

| ID | Result | Evidence |
|---|---|---|
| D1 | PASS WITH REMOTE FETCH LIMITATION | Local `HEAD` and `merge-base` match the canonical SHA; remotes, worktrees, dirty state, and recovery ref are recorded below. `git fetch fork main` could not resolve `github.com`; the GitHub connector confirmed the repository and base commit, but did not establish current remote branch freshness. |
| D2 | PASS | Existing Event V1 golden tests pass; `domain/identity.py` was not changed and has no chain dependency. |
| D3 | PASS | Multi-target outbox test asserts one persisted binding, the same commitment and envelope across targets, target key separation, and collision-safe idempotency. Existing commitment golden tests pass. |
| D4 | PASS | `ChainAdapter` protocol contract and Solana adapter conformance test pass without changing the commitment envelope. |
| D5 | PASS | Generic attempts and receipts persist chain, adapter, transaction ID, block reference, timestamps, safe error code, retry metadata, and evidence status. |
| D6 | PASS | Queue and offline event-chain tests pass without a network adapter. |
| D7 | PASS | Failure injection verifies one target can reject while the other remains queued and the local event chain remains valid. |
| D8 | PASS | Existing Solana CLI/client tests and legacy SQLite migration tests pass. The full Solana execution path remains unchanged. |
| D9 | PASS | Existing queue rollback and event-chain concurrency tests pass; migration lock contention verifies foreign-key enforcement is restored. |
| D10 | PENDING CLEAN CHECKOUT | Source worktree full regression: 763 passed, 7 skipped. Clean detached checkout reproduction is recorded in the final handoff after the commit is tested. |
| D11 | PASS | Independent final red-team review found no remaining P1/P2 findings after the fixes listed in the handoff. |
| D12 | PASS | `MULTICHAIN_MVP1_HANDOFF.md` lists the generic execution/recovery work and evidence gates for Mini-MVP 2. |

## Local verification

- Full suite: `uv run --offline --extra dev --extra solana pytest -q` — 763 passed,
  7 skipped, 1 existing Starlette/httpx deprecation warning.
- Focused migration suite — 63 passed.
- `uv run --offline python -m compileall -q src` — passed.
- `uv lock --check --offline` — passed; no dependency or lockfile change.
- `git diff --check` — passed.
- No configured or available lint/type-check executable was found in this
  checkout; the Makefile exposes only the pytest test target for Python checks.

Scope boundary: this is architecture preparation only. No Base/Arbitrum/EVM code,
Solidity, RF/firmware/Behavior ML work, live chain claims, push, PR or main update.

## Reconciliation evidence at start

- `HEAD` and `merge-base(HEAD, fork/main)` were both
  `b2de3a9a58f911e24dc9a8395717f520542282b3`.
- Worktree branch: `multichain/mvp1-core-migration`; initially clean.
- Remotes: `fork=https://github.com/GUZZBR1/riose.git`,
  `origin=https://github.com/santleme/riose.git`.
- Recovery ref `recovery/multichain-mvp1-pre-migration` points to the initial
  source worktree state (`9bc8e972c4e7418669ce94250c58ce91e49cb744`).
- `git fetch fork main` failed with `Could not resolve host: github.com`. The
  GitHub connector independently confirmed `GUZZBR1/riose`, default branch `main`,
  push authority, and the requested base commit SHA. Remote branch freshness was
  not fetched in this environment.
