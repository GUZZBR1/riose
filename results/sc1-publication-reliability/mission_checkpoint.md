# SC-1 Mission Checkpoint

- Mission: harden existing RIOSE publication reliability, preserve Factory verdict authority, and return the required evidence packet.
- Current phase: implementation, red team, tests, and evidence are complete; final commit and repository snapshot are in progress.
- Source base: local fork tip `b2ddf11098ecd87b954bf97af26f8ecb8862b58a`, tree `2ee3930e5ae6b96cef6134840151c17f7c85f0e4`.
- Mission checkout: `/home/gusta/projetos/RIOSE/riose-sc1-publication-reliability`, branch `software-closure/sc1-publication-reliability`, created from `fork/main`.
- Existing primary checkout remains untouched, including its pre-existing dirty/untracked work.
- Remote freshness: `UNVERIFIED`; GitHub DNS failed during fetch and PR lookup. No push, merge, or upstream write occurred.

## Completed changes

- Extended the existing outbox with bounded persisted retries, exponential backoff/jitter, classification, due gating, duplicate suppression observability, and manual-intervention terminal states.
- Extended the existing dispatcher with transient/permanent classification, safer local failure handling after an attempt, forced reconciliation observation without early replay, and conflict escalation after `CONFIRMED`.
- Reused the common EVM nonce coordinator for all EVM sends, including Base, and added a Base adapter integration regression test (not executable until EVM extras are available).
- Added Solana persisted-block-height replay safety. Expired ambiguous attempts stop for manual review without a replacement transaction.
- Added retry, expiry, Base nonce, replay/backoff, verification conflict, and post-attempt local error tests.
- Added seven hard subprocess crash windows A-G. Stage F forcibly exits after durable `CONFIRMED` receipt persistence and before `VERIFIED`.
- Added `failure_matrix.json`, `test_results.json`, `retry_policy.json`, `crash_window_results.json`, `nonce_safety_results.json`, `commitment_consistency.json`, `red_team_report.md`, `environment.json`, `claims.json`, and `final_report.md`.

## Verification

- Focused publication suite: 91 passed.
- Full Python suite excluding `test_evm_local.py` and `test_evm_registry.py`: 623 passed; one unrelated Starlette deprecation warning.
- Unexcluded Python collection is blocked by missing optional `eth_account` in those two EVM modules. Package download was unavailable due network/DNS.
- Compileall, `uv lock --check --offline`, offline source/wheel build, and `git diff --check`: passed.
- Hardware C build and CTest: 39/39 passed.
- Solidity tests were not run because npm offline cache lacks Ganache 7.9.2.
- Independent red team found and the branch fixed four in-scope issues: early retry during forced reconciliation, infinite verification conflict polling, illegal terminal transition after a persisted attempt, and backoff/replay interaction.

## Remaining boundary

No public-chain transaction or funds were used. `REAL_ON_CHAIN=UNVERIFIED`. Solana keypair loader remains unchanged; observed `SEC-SOLANA-001` stays in SC-2 scope. Recommended Factory classification: `EXTERNAL_BLOCKED`, due to missing EVM and Solidity dependency lanes. Commit only mission changes with Lore trailers; do not push or merge.
