# Multichain Mini-MVP 2: compiled Definition of Done

Compiled before implementation from the Mini-MVP 2 mission and the approved
Mini-MVP 1 commit `fedc1bb8b3645d78d5747745d1b8f6ad21af5fd2`.
`UNVERIFIED` means the new phase still needs evidence; it is not a failure claim.

## Reconciliation and anti-duplication gate

| ID | Obligation | Verification method | Initial status |
|---|---|---|---|
| R0 | Work in an isolated branch based on the approved Mini-MVP 1 HEAD; preserve main and recovery refs | Git refs, merge-base, worktrees, dirty state, remotes, commit log | COVERED locally; remote fetch unavailable |
| R1 | Reuse Event V1, commitment binding, outbox, normalized attempts/receipts, ChainAdapter, and Solana client | Architecture map and code search before implementation; diff after implementation | COVERED as inventory; final diff pending |
| R2 | Do not implement Base, Arbitrum, EVMAdapter, Solidity, RF, firmware, Behavior ML, or field validation | Diff and final scope audit | UNVERIFIED |

`fork` is `https://github.com/GUZZBR1/riose.git`; `origin` is
`https://github.com/santleme/riose.git`. The new branch is
`multichain/mvp2-solana-reconciliation`, created clean from the approved HEAD.
The recovery ref `recovery/multichain-mvp2-pre-reconciliation` points to that
HEAD. `git fetch fork main` was attempted and failed because this environment
could not resolve `github.com`; this is an external reconciliation limitation,
not evidence of a newer or older remote branch.

Existing orchestration is `publication_cli._send_or_reconcile`, which calls
`SolanaMemoClient` directly. No generic dispatcher or publication HTTP route
exists. The approved `ChainAdapter`, `SolanaMemoAdapter`, and generic outbox
attempt/receipt methods are the interfaces to extend. This rules out another
event model, commitment generator, store, or Solana RPC client.

## Implementation obligations

| ID | Obligation | Required evidence | Initial status |
|---|---|---|---|
| D1 | One dispatcher selects an adapter by the target chain, network, and adapter identity, failing closed on mismatches | Dispatcher test with matching and mismatched targets | UNVERIFIED |
| D2 | The dispatcher passes the unchanged canonical public envelope to the adapter and persists the prepared attempt before any submit call | Event/commitment golden tests and call-order fault injection | UNVERIFIED |
| D3 | Solana send/reconcile runs through `SolanaMemoAdapter` and the generic dispatcher while reusing `SolanaMemoClient` | CLI integration test and call-path inspection | UNVERIFIED |
| D4 | States and normalized receipts distinguish QUEUED, PREPARED, RPC_ACCEPTED, UNKNOWN, RETRYABLE, CONFIRMED, VERIFIED, and REJECTED without claiming more evidence than observed | Transition table audit, receipt tests, CLI status test | UNVERIFIED |
| D5 | A persisted PREPARED Solana attempt is recoverable after restart using the same validated signed bytes/signature; absent RPC evidence remains explicit ambiguity | Crash/restart test, signed payload and envelope validation, RPC fault injection | UNVERIFIED |
| D6 | Duplicate dispatch, already confirmed/verified targets, safe retry, and two workers cannot create duplicate new attempts or corrupt publication state | Concurrent worker and idempotency tests, SQLite transaction inspection | UNVERIFIED |
| D7 | Adapter unavailability and a failed target do not invalidate Event V1 or block another target | Offline and partial failure tests | UNVERIFIED |
| D8 | Existing CLI entrypoints remain useful, and a normal `publication process` route uses the dispatcher | CLI tests and command help/manual invocation | UNVERIFIED |
| D9 | Full relevant regression and clean checkout at the final commit pass | Recorded commands, counts, commit SHA, clean status | UNVERIFIED |
| D10 | An independent red team challenges leakage, retries, recovery ambiguity, receipt truth, concurrency, and offline behavior | Findings, dispositions, and rerun evidence | UNVERIFIED |
| D11 | Attempt a controlled real Solana Devnet publication only if credential, funds, and RPC prerequisites are safely available; classify the result honestly | Prerequisite inspection and, if run, independently checked transaction evidence | UNVERIFIED |
| D12 | Produce a precise EVM Core handoff without implementing EVM | Final handoff artifact and scope audit | UNVERIFIED |

## Required software tests

Each numbered item in the mission must have direct evidence. Tests may share a
fixture or command, but a passing suite alone is insufficient without the named
behavior being covered.

| Mission test | Required observation | Initial status |
|---|---|---|
| T1 | Event V1 has no blockchain dependency | Existing Event V1 golden test plus source inspection | UNVERIFIED |
| T2 | The same persisted Event V1 binding yields the same commitment | Multi-target deterministic commitment test | UNVERIFIED |
| T3 | A Solana target does not change that commitment | Envelope before/after dispatch compared | UNVERIFIED |
| T4 | Dispatcher selects Solana by target identity | Matching and wrong-adapter tests | UNVERIFIED |
| T5 | Attempt is durable before submission | Fault immediately before network submit, reopen Store | UNVERIFIED |
| T6 | Receipt is normalized and correlated to target/attempt | Chain/network/transaction/status/time/block fields inspected | UNVERIFIED |
| T7 | CONFIRMED/VERIFIED does not republish | Duplicate process invocation and adapter call counts | UNVERIFIED |
| T8 | RETRYABLE may resume only by a safe new attempt | State and attempt count tests | UNVERIFIED |
| T9 | Terminal failure cannot become success | Transition and dispatcher tests | UNVERIFIED |
| T10 | Restart preserves publication state | Reopen SQLite and reconcile persisted attempt | UNVERIFIED |
| T11 | PREPARED recovery is safe or explicitly UNKNOWN | Crash, absent receipt, same-wire recovery tests | UNVERIFIED |
| T12 | Duplicate dispatch is controlled | Same-target repeated dispatch test | UNVERIFIED |
| T13 | Concurrent workers preserve state | Separate Store connections against one SQLite file | UNVERIFIED |
| T14 | Solana failure leaves Event V1 valid | Local chain verification after injected failure | UNVERIFIED |
| T15 | Other targets remain independent | Two-target failure test | UNVERIFIED |
| T16 | SQLite/event chain semantics persist | Existing atomicity/concurrency tests and new transaction checks | UNVERIFIED |
| T17 | Full regression passes | Repository-wide test command | UNVERIFIED |

## Fault injection matrix

Explicitly exercise: adapter unavailable; RPC timeout; failure before prepare;
failure after PREPARED; failure during submit; submit error; receipt unavailable;
process restart; duplicate worker; malformed adapter response. Record which
condition remains UNKNOWN, RETRYABLE, or terminal and why. No test fixture is
real on-chain evidence.

## Evidence and claim gates

- `QUEUED`, `PREPARED`, `RPC_ACCEPTED`, `CONFIRMED`, and `VERIFIED` are distinct.
  A single RPC endpoint remains `ASSUMED` evidence until independent verification.
- An absent `getTransaction` result cannot prove the prepared transaction was
  never submitted. The dispatcher must not create a new signed transaction from
  that absence alone. The Solana docs describe the distinction between RPC
  acceptance and confirmation, signature status history, and blockhash expiry:
  [sendTransaction](https://solana.com/docs/rpc/http/sendtransaction),
  [getSignatureStatuses](https://solana.com/docs/rpc/http/getsignaturestatuses),
  [confirmation and expiration](https://solana.com/developers/cookbook/transactions/confirmation).
- `REAL_ON_CHAIN=VERIFIED_SOLANA_DEVNET` requires an actual controlled transaction
  and independent evidence. Otherwise retain `REAL_ON_CHAIN=UNVERIFIED`, report
  any external blocker, and do not invent a signature, slot, or explorer URL.
- No push, PR, merge to main, history rewrite, or removal of preservation refs.

## Completion audit

The initial-status columns above preserve the pre-implementation baseline.
This audit records the evidence collected after implementation.

| Obligations | Result | Evidence |
|---|---|---|
| R0 | PASS locally; remote reconciliation limited | Branch/worktree from `fedc1bb8b3645d78d5747745d1b8f6ad21af5fd2`; recovery ref retained; `fork main` fetch failed DNS |
| R1-R2 | PASS | Existing Event V1, commitment, outbox, client, and adapter were extended; diff contains no EVM/Base/Arbitrum, RF, firmware, or field code |
| D1-D4 | PASS | Generic dispatcher routes exact chain/network/adapter; CLI send/process/reconcile uses it; normalized target-specific receipts and state tests |
| D5-D6 | PASS within signed-wire semantics | Persisted PREPARED wire is validated before replay; absent RPC evidence stays uncertain; claims, renewal, and fenced writes prevent duplicate local attempts; repeated Solana wire has the same signature |
| D7-D8 | PASS | Independent-target and Event V1 failure tests; CLI process entrypoint test |
| D9 | PASS in working tree; clean checkout pending | Full regression: 797 passed, 7 skipped, one upstream Starlette deprecation warning; Python compileall and git diff check passed |
| D10 | PASS after fixes | Independent red team found CONFIRMED downgrade, stale claim race, and misleading Solana rejection. All were fixed and covered by regressions |
| D11 | EXTERNAL_BLOCKER | No Solana keypair at the standard WSL path and Devnet DNS unavailable; no transaction submitted; `REAL_ON_CHAIN=UNVERIFIED` |
| D12 | PASS | `MULTICHAIN_MVP2_EVM_HANDOFF.md` defines the future adapter's signed-wire, network, nonce, receipt, and recovery requirements |

| Required tests | Result | Direct evidence |
|---|---|---|
| T1-T3 | PASS | Existing Event V1/commitment tests plus dispatcher unchanged-envelope and same-event target tests |
| T4-T6 | PASS | Dispatcher routing, persist-before-submit, and normalized receipt assertions |
| T7-T9 | PASS | Confirmed/verified no-republish, safe RETRYABLE, terminal REJECTED tests |
| T10-T13 | PASS | Reopened SQLite PREPARED recovery, duplicate dispatch, separate-Store worker contention, stale-claim recovery |
| T14-T16 | PASS | Failed target leaves Event V1 valid and sibling target independent; existing SQLite/event-chain regression |
| T17 | PASS in working tree | Full regression 797 passed, 7 skipped |

Fault injection covered adapter missing, prepare failure, persisted PREPARED
crash/restart, submit timeout and mismatched return, receipt RPC timeout or
absence, malformed prepared wire and receipt, duplicate worker, and claim
expiry. A repeated submit can occur after the first worker loses its claim
while its RPC is in flight; the adapter contract requires exact-wire replay
idempotency. Solana's validated signed wire satisfies this by preserving the
same signature. No exactly-once network claim is made.

Static checks: `compileall` and `git diff --check` passed. The repository
does not declare a linter or type checker, and `ruff` is not installed; no
new dependency was added.
