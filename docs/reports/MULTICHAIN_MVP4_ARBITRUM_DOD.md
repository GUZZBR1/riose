# Multichain Mini-MVP 4B: compiled Definition of Done

Status: local implementation and validation complete; public-chain execution is externally blocked.
Approved base: `60bbb7f29bc98cf5c69caf798276929c859c8d2f`.
Branch: `multichain/mvp4-arbitrum`.
The M3 mission is closed as `PASS_LOCAL_EVM_WITH_LIMITATION`; its
`CONFIRMED` to `VERIFIED` limitation remains in force.

## Mission and anti-duplication gate

Integrate the existing EVM Core with Arbitrum Sepolia and attempt public
testnet validation only after local validation and a safe preflight. Reuse
`EVMRegistryAdapter`, `EVMNetworkConfig`, Event V1 canonical commitment, generic
dispatcher, SQLite Store/outbox/attempts/receipts, and
`RioseCommitmentRegistry.sol`. Repository search found the shared EVM code and
the existing Arbitrum deployment handoff; there is no Arbitrum-specific adapter
or contract to reuse or duplicate. The registry has no Arbitrum-specific
opcodes, precompiles, bridge calls, or L2 block-number assumptions.

## Baseline, checkpoints, and trust boundaries

| ID | Obligation | Evidence required | Status |
|---|---|---|---|
| B0 | Isolated branch/worktree at approved M3 SHA; no upstream/main mutation | `git status`, branch, HEAD, remotes, worktree | PASS |
| B1 | Compile required outcomes and search for existing EVM/Arbitrum assets before implementation | This DoD and repository search | PASS |
| B2 | Preserve M3 closure and compare baseline behavior | Focused EVM/publication/Solana/event tests | PASS: focused EVM/nonce suite, 24 passed |
| B3 | Map trust boundaries and evidence affected by Arbitrum configuration | Boundary list below plus regression evidence | PASS |
| B4 | Checkpoint before local contract run, public RPC reads, deployment, and publication | Recorded preflight result for each boundary | PASS: no write transaction without signer/funding checks |
| B5 | Independent Arbitrum/EVM, integration-test, and red-team reviews | Audit reports and dispositions | PASS WITH DOCUMENTED LIMITATION |

Trust boundaries:

1. Event V1 and the stored canonical commitment remain authoritative. EVM
   calldata must contain that exact 32-byte commitment without a chain-specific
   rehash; only the commitment may reach public storage/logs.
2. The RPC endpoint, network name/chain ID/genesis, registry address/code hash,
   immutable publisher, gas/fee limits, and configured confirmation depth are
   untrusted until checked against RPC observations and explicit deployment
   configuration.
3. Private signer material stays outside the repository, database, logs,
   exceptions, and receipts. Only an owner-readable key file may be used after
   matching its address to the immutable publisher and confirming test funds.
4. A successful submission response, an L2 receipt, configured L2 block depth,
   and L1 batch finality are different evidence. Public RPC errors, missing
   receipts, reverts, replacement, or reorg must not become a successful claim.
5. Persisted signed wire and nonce reservations are replayed exactly after
   ambiguous submission; they must not be silently re-signed or assigned a new
   nonce. Arbitrum's nonce ordering behavior must be covered under concurrency.

## Arbitrum-specific scope

Only these differences enter this mission:

- Arbitrum Sepolia identity is checked as chain ID `421614` and against the
  configured genesis. Use a full read/write RPC endpoint, not the send-only
  sequencer endpoint.
- Arbitrum transaction gas estimation includes L1 data-posting cost, so gas and
  fee handling must use the network RPC and explicit configured caps; local
  Ganache gas values are not an Arbitrum estimate. `eth_estimateGas` changes as
  the parent-chain data price changes. Any externally reported gas values must
  come from the raw receipt's `gasUsed`, `effectiveGasPrice`, and (when present)
  `gasUsedForL1`; the normalized RIOSE receipt does not currently store these
  fields, and no fiat estimate is made.
- Configured confirmations count L2 blocks and do not prove Ethereum L1 batch
  finality. Preserve the existing `CONFIRMED`/`VERIFIED` limitation and label
  public-chain evidence accordingly.
- The current fee/tip policy is network-specific and can evolve; retain
  configurable EIP-1559 fields and do not encode historical assumptions.
- Arbitrum nonce acceptance is order-sensitive. Preserve unique durable nonce
  allocation and validate the lowest-outstanding-nonce submission/recovery path.

Do not introduce an `ArbitrumAdapter`, a second commitment format, changes to
Event V1, or unilateral edits to the shared dispatcher. Any unavoidable shared
change is recorded as `CROSS_BRANCH_FINDING` for review.

## Definition of Done

| ID | Obligation | Verification | Status |
|---|---|---|---|
| D1 | Reuse the generic EVM adapter/configuration/registry and pin Arbitrum Sepolia identity | Config tests; wrong chain/genesis tests | PASS |
| D2 | Submit the unchanged canonical commitment through existing dispatcher/outbox | Full Python regression suite including cross-chain golden and local EVM integration tests | PASS |
| D3 | Account for Arbitrum RPC, gas estimation/caps, receipts, L2 confirmations, explorer evidence, and fee reporting without L2 domain leakage | Adapter tests and operator documentation | PASS WITH NO PUBLIC RECEIPT YET |
| D4 | Preserve retry safety and recovery for unavailable RPC, before/after-submit timeout, missing receipt, restart, duplicate, revert, wrong network/contract, and nonce concurrency | Focused fault tests plus full Python suite | PASS |
| D5 | Preserve publisher/code/genesis/signed-wire checks, privacy, and secret handling | Red-team review and tests | PASS WITH DOCUMENTED LIMITATION |
| D6 | Local EVM and Solidity regressions pass | EVM core and Ganache tests; Solidity compile | PASS |
| D7 | Solana, persistence/event-chain, and full Python regressions pass | Full Python suite | PASS: 822 passed, 7 skipped |
| D8 | Build, lock/dependency checks, and final clean detached checkout pass | Lock/dependency/build checks and full suite pass in a clean detached checkout | PASS |
| D9 | Attempt real Arbitrum Sepolia validation only after safe preflight; report public evidence only if independently verifiable | RPC identity, signer/funds, tx, receipt, address, block, event, matching commitment | EXTERNAL_BLOCKER: no secure signer key file or key environment configured |

## Claim policy

`LOCAL_EVM != ARBITRUM_SEPOLIA`.
`SUBMITTED != CONFIRMED`.
`CONFIRMED != VERIFIED`.
`ARBITRUM_REAL_ON_CHAIN = VERIFIED_ARBITRUM_SEPOLIA` only with a real public
transaction and independently verifiable matching receipt/event/commitment.
Otherwise, report `ARBITRUM_REAL_ON_CHAIN = UNVERIFIED` and the concrete
external blocker. No evidence may be inferred from local tests or fabricated.

## Independent audit dispositions

- The existing Solidity registry is reusable as written: normal direct L2
  `msg.sender` semantics apply and it does not read L2 `block.number` or use
  Arbitrum-specific precompiles/bridges. The same digest across networks allows
  correlation; it is not unlinkable anonymity.
- Sepolia configuration now pins chain ID `421614`, rejects the public
  send-only sequencer endpoint, and checks the immutable registry publisher in
  addition to chain, genesis, and deployed code hash.
- Arbitrum preparation estimates the exact registry call over RPC and applies
  a 10% gas allowance up to the configured maximum. Local EVM gas measurements
  are not reused as a Sepolia estimate.
- Arbitrum sends now hold a SQLite write reservation while checking the
  current nonce and submitting. A higher reserved nonce waits until the lower
  send advances the chain nonce. Persisted signed bytes are still replayed
  exactly on recovery.
- The M3 soft-confirmation limitation remains accepted: `VERIFIED` is a
  configured-depth L2 observation plus a second read from the configured RPC,
  with evidence labeled `ASSUMED`. It does not prove parent-chain batch
  finality, resist a later reorg, or provide independent-RPC corroboration.
- The existing nonce reservation has no operator recovery path for a
  permanently underfunded/underpriced attempt or a nonce consumed outside this
  database. The adapter does not create a replacement automatically; such a
  publication can remain `UNKNOWN` and needs a reviewed operator recovery.

## Execution evidence

- M3 focused baseline attempted from this exact base: **113 passed, 1 failed**.
  The only failure was the real Ganache integration test failing to start because
  Node dependencies were absent. Offline npm provisioning was attempted; npm
  first rejected Darwin-only `fsevents`, and `--force` then reported the locked
  Ganache tarball absent from the local npm cache. Re-run after provisioning or
  classify the environment limitation with evidence.
- The first `uv run` attempt could not resolve PyPI (`Temporary failure in name
  resolution`). Python test execution through the existing M3 virtualenv worked
  for the 113 passing tests.
- Focused EVM and nonce regression after implementation: **24 passed**. Full
  Python regression: **822 passed, 7 skipped**, including local Ganache
  deployment/publication/revert/restart, EVM Core, nonce ordering, Solana,
  persistence/outbox, and event-chain tests. One pre-existing
  Starlette/httpx deprecation warning was reported.
- Read-only public RPC preflight succeeded at
  `https://sepolia-rollup.arbitrum.io/rpc`: chain ID `0x66eee` (`421614`),
  genesis `0x77194da4010e549a7028a9c3c51c3e277823be6ac7d138d0bb8a70197b5c004c`,
  and a current block response. No signer/funding check was possible because
  there is no EVM key environment variable or known external key file. No
  deployment or transaction was attempted.
- A clean detached checkout at `0bd664b809f32132b883237e12972dd18f37a04c`
  passed the full suite: **822 passed, 7 skipped**. Its first run lacked the
  ignored Node dependencies and failed only the local Ganache startup; after
  locked dependencies were provisioned, the rerun passed, including Ganache.
- Solidity compile, `uv lock --check --offline`, `uv pip check`, Python
  `compileall`, `uv build --offline`, and `git diff --check` passed. These
  checks will be repeated at the final documentation commit.
- `ARBITRUM_REAL_ON_CHAIN = UNVERIFIED` until a secure funded test signer is
  available and a public deployment/publication is independently inspected.
