# RIOSE SC-1 Publication Reliability Hardening

## Outcome

Implementation and local verification are complete on the isolated fork branch `software-closure/sc1-publication-reliability`, based on local `fork/main` at `b2ddf11098ecd87b954bf97af26f8ecb8862b58a`. Remote freshness remains unverified because GitHub DNS was unavailable.

The existing Event V1, Commitment V1, SQLite Store/outbox, one publication dispatcher, ChainAdapter boundary, Solana Memo adapter, EVM registry adapter, and shared EVM nonce coordinator were reused. The work adds bounded retry scheduling, persistent retry classifications, manual-intervention outcomes, due-time gating, Base submission ordering through the common EVM coordinator, safe Solana expiry handling, CLI retry/attempt observability, and hard crash-window tests.

The conservative processing claim is at-least-once worker processing with duplicate request suppression and exact signed-payload reuse for ambiguous attempts. Exactly-once execution and universal effectively-once anchoring are not claimed. `UNKNOWN`, `RPC_ACCEPTED`, `CONFIRMED`, and `VERIFIED` retain distinct meanings. EVM receipts in existing adapters remain `ASSUMED`; Solana receipts remain `ASSUMED`; crash fixtures are `SIMULATED`.

## Verification

- Focused publication/reliability suite: 91 passed.
- Full Python suite excluding only the two EVM adapter/local-EVM modules blocked by missing `eth_account`: 623 passed, one unrelated Starlette deprecation warning.
- Unexcluded full Python collection: blocked by `ModuleNotFoundError: eth_account` in those two EVM modules.
- Compileall, dependency lock consistency, package build, `git diff --check`: passed.
- Hardware C build and CTest: 39/39 passed.
- Solidity compile/local-EVM checks: not run; npm offline cache lacks Ganache 7.9.2.
- Base adapter ordering integration test is added but not run because the EVM module cannot collect. Coordinator-level Base 84532 and Arbitrum 421614 ordering tests passed.

## Limits and next gate

No live Base, Arbitrum, or Solana transaction was sent. No public-chain evidence was queried. Re-run EVM and Solidity checks when package indexes are reachable. `SEC-SOLANA-001` was observed and left in SC-2 scope: `load_keypair` still lacks explicit no-follow and restrictive file-permission enforcement. No merge or push was performed.

Recommended classification for Factory: `EXTERNAL_BLOCKED`. The implemented local reliability paths are reviewable, but required EVM adapter and Solidity lanes could not be verified in this environment. This is a recommendation only; Factory owns the verdict.
