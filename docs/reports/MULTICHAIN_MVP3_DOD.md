# Multichain Mini-MVP 3: compiled Definition of Done

Compiled from the Mini-MVP 3 mission before material implementation.
Approved base: `977be7b2c2aeb13b1bb378c0f9a3c753c8436701`.
This file preserves the required scope and will be updated with evidence.

## Baseline, anti-duplication, and checkpoints

| ID | Obligation | Evidence required | Status |
|---|---|---|---|
| B0 | Isolated branch/worktree from approved M2 HEAD; recovery ref; no upstream/main mutation | Git refs, merge-base, remotes, dirty state | COVERED locally |
| B1 | Reuse Event V1, canonical CommitmentV1 binding, target, SQLite Store/outbox, attempts, receipts, dispatcher, ChainAdapter, retry/recovery state machine | Source inventory and final diff | PASS |
| B2 | Search for existing EVM/contract/ABI/signing/runtime assets before adding any | Repository and local-tool inventory | COVERED: no EVM code, Solidity, ABI, library or local runtime in approved base |
| B3 | Map trust boundaries and evidence invalidated by EVM changes | Boundary map below, regression results | PASS |
| B4 | Preserve material checkpoints: base, DoD/inventory, contract+adapter, local execution, red team, clean checkout | Git commits and report updates | SOURCE COMMIT DONE; CLEAN CHECKOUT PENDING |

No BaseAdapter or ArbitrumAdapter is permitted. The same EVM adapter and
contract source must accept future network/deployment configuration for both.
Baseline focused publication/Solana/outbox tests: 62 passed at the approved
base. The existing generic dispatcher and SQLite publication journal are the
execution seam. Optional `solana` is the only chain library in `pyproject.toml`;
an EVM signing dependency and local EVM runtime are justified new capabilities.

## Trust boundaries and evidence impact

1. **Local Event V1 → canonical commitment:** existing verified event prefix and
   canonical envelope are authoritative locally. EVM code must consume the
   persisted digest as bytes32, never recompute a chain-specific digest.
2. **Configuration → RPC/contract:** chain ID, endpoint, contract address,
   confirmation policy, and optional explorer metadata are untrusted until
   validated against explicit configuration and RPC response. No implicit
   production chain default.
3. **Signer → signed wire:** private keys stay outside repository, database,
   logs, exceptions, and receipts. Signed raw transaction, hash, nonce, chain
   ID, destination, and calldata are validated before durable PREPARED and
   again after restart.
4. **RPC → state:** send acceptance, receipt appearance, confirmation policy,
   revert, replacement, nonce conflict, and reorganization carry different
   evidence. Missing/malformed RPC responses cannot become CONFIRMED or safe
   new-attempt RETRYABLE.
5. **Contract → public data:** only canonical commitment, publisher and block
   context may reach chain storage/logs. No Event V1 payload or animal data.
6. **Concurrent workers → nonce:** signer/network nonce allocation must be
   coordinated across targets and processes; the existing per-target claim
   alone is insufficient.

EVM additions can invalidate publication dispatcher/receipt/state evidence,
Solana CLI behavior, SQLite migration/atomicity, and Event V1 privacy claims.
Those descendants require regression. Prior unrelated RF/firmware/ML evidence
is not invalidated by proximity alone.

## Implementation gates

| ID | Obligation | Verification method | Status |
|---|---|---|---|
| D1 | One generic EVM network configuration with explicit chain/network/RPC/contract/finality/explorer identity | Config validation and wrong-network tests | PASS |
| D2 | Deterministic EVM serialization of the unchanged canonical commitment | Same-event Solana/EVM payload golden test | PASS |
| D3 | Minimal Solidity registry, explicit duplicate semantics, no private data or unnecessary admin/proxy/storage | Source audit and real local contract tests | PASS |
| D4 | Shared EVM ChainAdapter prepares/signs, validates persisted wire, submits exact bytes, observes/verifies normalized receipts | Adapter/fault tests and call-order evidence | PASS |
| D5 | Reuse existing dispatcher/outbox/CLI without domain or chain-specific duplication | Integration test and diff inspection | PASS |
| D6 | Recovery distinguishes prepared, accepted, absent receipt, reverted, replaced/nonce-conflict, and confirmed/finalized; no unsupported certainty | Restart and fault injection | PASS WITH FINALITY LIMIT |
| D7 | Same-signer concurrent targets cannot cause RIOSE nonce collision; crash/restart retains reservation evidence | Two-process and restart tests | PASS |
| D8 | Real local EVM deploy, publication, event, duplicate, revert, recovery, and multiple commitments | Local runtime transcripts and independent receipt/log inspection | PASS |
| D9 | Local measured deployment/publication/duplicate or revert gas | Receipts and report; no fiat estimate | PASS |
| D10 | Security review of privacy, replay, duplicate, signer, RPC/contract trust, gas/storage, admin/proxy | Independent review and disposition | PASS WITH DOCUMENTED LIMIT |
| D11 | Full Python/contract/local regression, package/build and dependency checks in final clean detached checkout | Commands and output at final HEAD | PENDING CLEAN CHECKOUT |
| D12 | Base and Arbitrum handoffs use only future config/deployment differences | Handoff artifacts, no live network claims | PASS |

## Required tests

| Mission numbers | Direct proof required | Status |
|---|---|---|
| T1–T4 | Event V1 chain-agnostic; canonical digest unchanged; deterministic EVM bytes32; same digest in Solana and EVM transport | PASS |
| T5–T7 | Contract receives digest, deploys and publishes in real local EVM | PASS |
| T8–T11 | Normalized receipt, matching event/log, duplicate semantics, reverted transaction not CONFIRMED | PASS |
| T12–T14 | RPC failure yields no fabricated receipt; restart and evidence-bounded recovery | PASS |
| T15–T16 | Same-signer nonce concurrency and independent EVM targets | PASS |
| T17–T19 | Solana, SQLite, and Event chain regressions | PASS IN FULL SUITE |
| T20 | Full regression | 814 PASSED, 7 SKIPPED; FINAL CHECKOUT PENDING |

Fault injection must cover RPC unavailable, timeouts before/after send,
invalid contract, revert, absent receipt, restart, duplicate worker, nonce
collision, malformed commitment, and wrong network configuration.

## Claim limits

Local deployment may prove `EVM_CORE=TESTED_SOFTWARE` and
`CONTRACT=TESTED_LOCAL_EVM`. It cannot prove public Base or Arbitrum execution.
`SOLANA_REAL_ON_CHAIN`, `BASE_REAL_ON_CHAIN`, and
`ARBITRUM_REAL_ON_CHAIN` remain UNVERIFIED unless separately evidenced.

## Execution evidence and review disposition

- Local Ganache deployed the immutable-publisher registry and mined signed
  EIP-1559 transactions through the production adapter/dispatcher. A measured
  run used 165,517 gas for deployment, 45,788 for a registration, and 24,130
  for a duplicate revert. These are local measurements, not network fee quotes.
- The integration test inspects the deployed code hash, receipt status, block
  identity, exact event topics, persistent registry state, unauthorized caller
  revert, zero-commitment revert, duplicate revert, multiple commitments, a
  second independent contract with the same canonical commitment, and a real
  after-submit timeout recovered after closing/reopening SQLite.
- The test-only Node toolchain is locked in `contracts/package-lock.json` with
  Ganache 7.9.2 and solc 0.8.28. An offline Windows installation required
  `npm ci --force --ignore-scripts` because Ganache's bundled lock includes a
  Darwin-only `fsevents` entry; Node then used its JavaScript fallback on WSL.
  This is a local test-toolchain constraint, not an EVM runtime dependency.
- Focused EVM/dispatcher/CLI tests: 46 passed before the final additions;
  nonce tests include two separate OS processes. Full suite: 814 passed,
  7 skipped, 1 pre-existing Starlette deprecation warning before final
  checkout reproduction. `uv lock --check --offline`, `uv pip check`, Python
  byte-compilation, and `uv build --offline` passed.

Independent red team found five concrete issues. Contract front-running by an
unauthorized publisher was fixed with an immutable publisher argument and a
local revert test. Nonce collisions across two contracts on one chain were
fixed by reserving against chain ID plus pinned genesis, independently of the
publication target. Log and transaction block linkage was added to receipt
validation and fault-injected. Wrong-network conflation was reduced by pinning
the genesis block hash and including it in target/nonce identity. A proposed
generic dispatcher change for stale provisional confirmations broke approved
M2 recovery tests and was reverted. `VERIFIED` remains terminal after the
configured confirmation depth and a second RPC observation. A deeper later
reorganization and a dishonest single RPC remain externally unverifiable;
the CLI marks this evidence `ASSUMED`. New deployment handoffs require a
chosen finality policy and independent public evidence before public claims.

The permanent `mapping(bytes32 => bool)` is the minimum durable state used to
reject duplicates. Event logs alone would permit repeated successful writes
without a contract-side duplicate check. It grows by one slot per unique
commitment; the contract has no administrator, proxy, mutable publisher, animal
payload, or withdrawal path.
