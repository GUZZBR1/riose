# RIOSE Multichain Mini-MVP 4A: Base Sepolia

## Mission and baseline

Compiled from the Mini-MVP 4A request and the M3 Base handoff before implementation.
Approved base: `60bbb7f29bc98cf5c69caf798276929c859c8d2f`.
Baseline branch: `multichain/mvp3-evm-core`, clean at mission start.
Execution branch: `multichain/mvp4-base`, isolated worktree created at the approved base.
M3 status: `PASS_LOCAL_EVM_WITH_LIMITATION`; `MISSION = CLOSED`.
M3 Base handoff: configuration/deployment only; no Base transaction or public-chain validation.

## Anti-duplication gate and baseline inventory

| Capability | Existing asset | Decision |
|---|---|---|
| EVM chain configuration | `EVMNetworkConfig` | Reuse; it already accepts explicit chain ID, genesis, RPC, deployed address/code hash, publisher, confirmations, fee policy, and optional explorer URL. |
| EVM publishing | `EVMRegistryAdapter` | Reuse; no Base-specific adapter. |
| Commitment contract | `RioseCommitmentRegistry.sol` | Reuse unchanged; immutable publisher, canonical bytes32 commitment only. |
| Dispatch, persistence, recovery | Generic dispatcher, SQLite Store/outbox, attempts, receipts, EVM nonce coordinator | Reuse; do not change shared dispatch semantics for finality. |
| Base network identity | New deployment configuration only if independently verified | Extend through existing config, not a parallel abstraction. |

Search result: M3 provides a dedicated Base handoff, shared adapter/config, contract, dispatcher, persistence/recovery code, local EVM integration tests, and optional EVM dependencies. No existing Base deployment config or evidence of a public Base transaction was found. No implementation edits have been made at this checkpoint.

## External checkpoint

Base Sepolia identity read at mission time:
- Official Base documentation specifies chain ID 84532 and the public RPC `https://sepolia.base.org`.
- Chain ID `0x14a34` was read from the official RPC and two independent RPC endpoints.
- Genesis hash `0x0dcc9e089e30b90ddfc55be9a37dd15bc551aeee999d2e2b51414c54eaf934e4` matched on two independent endpoints.
- The official RPC returned the latest block but could not serve block 0 (pruned history). The independent endpoints returned the same block-0 hash.
- No signer key-file path is configured in the available shell environments. Do not deploy or sign until a protected key file, matching publisher address, and sufficient Base Sepolia ETH are available and checked. No transaction has been attempted.

Verified Base network fields for a future deployment config are `chain=base-sepolia`, `chain_id=84532`, `expected_genesis_hash=0x0dcc9e089e30b90ddfc55be9a37dd15bc551aeee999d2e2b51414c54eaf934e4`, and `rpc_url=https://sepolia.base.org`. Contract address, deployed runtime code hash, publisher, fee bounds, and a live confirmation depth are deployment-specific and remain unset. No partial JSON deployment config is committed because those required values cannot be verified before deployment.

## Trust boundaries

1. Canonical commitment and persisted event are authoritative. The EVM call must encode the existing 32-byte SHA-256 commitment unchanged; no animal/event payload may reach the chain.
2. Network/deployment JSON and RPC are untrusted. Verify chain ID, genesis hash, contract runtime code hash, configured publisher, and contract address before preparing/submitting/reading receipts.
3. The signer file is secret. It must remain outside Git, logs, evidence, and persistence; only a matching configured publisher may sign.
4. RPC acceptance, transaction submission, receipt existence, success/revert, configured confirmation depth, and independently verified finality are distinct claims.
5. Attempts, nonce reservations, receipts, and dispatch state must remain durable across process restart. Recovery may only rebroadcast the exact signed wire under the established EVM rules.
6. Base-specific configuration must not leak into the generic dispatcher or alter EVM Core/Solana behavior. Preserve the known `CONFIRMED -> VERIFIED` finality limitation.

## Compiled Definition of Done

Statuses start as `UNVERIFIED`; evidence will be added below. Obligations are transcribed from the mission without adding thresholds.

| ID | Requirement | Verification evidence required | Status |
|---|---|---|---|
| DOD-01 | Start from the approved base on isolated `multichain/mvp4-base`; preserve M3 baseline and avoid upstream/main mutations | Git branch, base SHA, clean checkout and final status | COVERED |
| DOD-02 | Reuse EVMAdapter/config, canonical commitment, generic dispatcher, Store/outbox, attempts, receipts, contract source | Source inventory and final diff | COVERED |
| DOD-03 | Only add Base differences actually needed: network/chain ID/RPC/confirmation/deployment config/verified explorer metadata | Verified Base identity and focused shared-config test; deployment fields are external | PARTIAL |
| DOD-04 | Do not hardcode secrets, commit/log private keys, alter canonical commitment, or publish animal data | Diff review, privacy assertions in EVM regression, and contract/payload audit | COVERED |
| DOD-05 | Attempt Base Sepolia validation only when RPC, safe signer, test ETH, chain ID, and credential safety are established | Read-only RPC evidence and gated deployment decision | PARTIAL — no signer configured |
| DOD-06 | If prerequisites allow, deploy unchanged registry; publish nonsensitive test commitment; capture real tx/receipt/block/log/address; reconcile and compare canonical digest; independently verify explorer/endpoint | Public RPC and independent verification evidence | NOT RUN — DOD-05 preconditions absent |
| DOD-07 | If external infrastructure prevents real deployment, classify `EXTERNAL_BLOCKER`; otherwise on-chain claim stays `UNVERIFIED` | Error evidence and explicit report disposition | EXTERNAL_BLOCKER — signer, publisher, and funded balance unavailable |
| DOD-08 | Exercise timeout before/after submit, missing receipt, restart, duplicate dispatch, nonce concurrency, and reverted transaction under Base config | Shared EVM adapter fault tests plus Base identity/chain binding test | COVERED; Base adds no separate recovery path |
| DOD-09 | Preserve M3 finality limitation; do not change dispatcher to claim `CONFIRMED -> VERIFIED` | Diff review and claim audit | COVERED |
| DOD-10 | Run focused Base tests, EVM Core, contract/Solidity, Solana, persistence, full Python, clean detached checkout, build/package/dependency checks | Exact commands/results at candidate code HEAD `1fc1193861ee50d16fc9c4a4308b6be1c21bb25b` | COVERED |
| DOD-11 | Independent red-team review attempts all mission-listed attacks; fix recoverable findings | Independent review and disposition evidence | COVERED — no bypass; finality, single-RPC, and shared-SQLite nonce scope documented |
| DOD-12 | Compare final candidate with M3 and report all cross-branch findings and remaining gaps | Baseline comparison and final report | COVERED — no shared-code changes or new cross-branch finding |

## Checkpoints

- **C0 — baseline and DoD:** completed before implementation.
- **C1 — implementation/configuration:** complete; verified Base Sepolia identity and a focused test through the shared config/adapter; no deployment config can be completed without deployment-bound values.
- **C2 — local and regression validation:** complete; focused Base/EVM test 10 passed, local EVM/contract integration 1 passed, livestock tracking (excluding the separately run local EVM integration) 249 passed, full suite 815 passed / 7 skipped, `uv lock --check --offline`, `uv pip check`, offline sdist/wheel build, and contract dependency resolution passed.
- **C3 — red-team and clean-checkout verification:** complete; independent read-only red team found no actionable bypass; detached checkout at `1fc1193861ee50d16fc9c4a4308b6be1c21bb25b` passed the full suite and was clean after test dependencies were removed.
- **C4 — final M3 comparison and report:** complete; the candidate adds only this DoD/evidence report and Base Sepolia identity test. EVM Core, dispatcher, persistence, contract, and Solana production code remain unchanged from M3.

## Evidence ledger

| Evidence | Source | Freshness | Uncertainty | Coverage |
|---|---|---|---|---|
| Base Sepolia chain ID | Base official RPC response and official Base docs | CURRENT | OBSERVED | DOD-03, DOD-05 |
| Base Sepolia genesis hash | Two independent RPC responses; official RPC prunes block 0 | CURRENT | OBSERVED | DOD-03, DOD-05 |
| M3 software/handoff | Approved base source and M3 report | CURRENT at baseline SHA | VERIFIED | DOD-01, DOD-02, DOD-09 |
| Signer and funded balance | No configured key file path/address; not checkable without a safe signer | CURRENT | UNKNOWN | DOD-05 through DOD-07 |
| Focused Base identity/config test | `tests/livestock_tracking/test_evm_registry.py` | CURRENT at candidate code HEAD | VERIFIED | DOD-03, DOD-08 |
| EVM Core, Solana, persistence, contract and full suite | Detached checkout at candidate code HEAD; `815 passed, 7 skipped` | CURRENT | VERIFIED | DOD-08, DOD-10 |
| Package and dependencies | `uv lock --check --offline`, `uv pip check`, `uv build --offline`, locked npm tree | CURRENT | VERIFIED | DOD-10 |

## Independent red-team disposition

The independent read-only review found no new actionable bypass in the requested chain/RPC identity, commitment, contract trust, secret handling, receipt correlation, retry/recovery, duplicate dispatch, privacy, or Core separation checks. It confirmed the existing adapter validates chain ID, genesis, and runtime code hash; binds signed transactions to the configured publisher/contract/commitment; and validates persisted wire before replay. The existing SQLite nonce coordinator protects workers sharing the same Store. Distinct databases using the same signer do not coordinate reservations and remain an operational boundary. Confirmation depth is still `ASSUMED`, not irreversible finality; terminal `VERIFIED` does not detect a later deep reorganization. No shared dispatcher change was recommended or made.

## Recovery task: simulation runner timeout during full suite

- Operation: first full Python suite on the candidate.
- Failure: `tests/simulation_lab/test_runner.py::test_process_failure_output_timeout_and_malformed_response_are_structured` expected `output exceeded`; the child process instead hit the test's 0.2-second timeout while writing 3 MB.
- Diagnosis: timing-sensitive test/environment behavior; unrelated code was unchanged. The entire parameterized test passed in isolation (5 passed), so no source or expectation was altered.
- Resolution: isolated parameterized rerun passed (5 passed), and the full suite then passed in the clean detached checkout (815 passed, 7 skipped). No source or test expectation was changed.

## Final report

reported_status: `PASS_LOCAL_EVM_WITH_LIMITATION`
governed_candidate_status: `EXTERNAL_BLOCKER` for real Base Sepolia validation; local software candidate passes the in-scope checks.

base_sha: `60bbb7f29bc98cf5c69caf798276929c859c8d2f`
final_head_at_evidence_run: `1fc1193861ee50d16fc9c4a4308b6be1c21bb25b`
branch: `multichain/mvp4-base`
commits_created: 2 local commits (candidate checkpoint and evidence report update); no push/PR/merge.

base_network_config: verified network identity recorded above; no deployable JSON because address/code hash/publisher/fees/confirmation depth are deployment-bound.
chain_id: `84532`
evm_adapter_reused: YES
contract_source_reused: YES, unchanged
base_specific_code_created: NO; shared config/adapter is sufficient. Added a focused Base identity test.

base_sepolia_attempted: NO; no signer file path is configured, so publisher and funded test balance cannot safely be established.
contract_deployment: NOT ATTEMPTED
contract_address: NONE
publication_transaction: NONE
receipt: NONE
block: NONE
event_log: NONE
commitment_match: local canonical bytes32 path covered; no real on-chain match
independent_verification: no transaction to verify

focused_tests: Base config/adapter identity and wrong-chain/genesis/code checks: 10 passed; local registry deployment/dispatch/revert/recovery: 1 passed
evm_regression: PASSED
solana_regression: PASSED in full suite
full_tests: 815 passed, 7 skipped, 1 pre-existing Starlette/httpx deprecation warning
clean_checkout: PASSED at `1fc1193861ee50d16fc9c4a4308b6be1c21bb25b`; `git status --porcelain` empty after cleanup
build_and_dependencies: uv lock check passed; 67 installed Python packages compatible; source distribution and wheel built offline; npm tree Ganache 7.9.2 / solc 0.8.37 resolved. npm reported 38 advisories in the existing local test-toolchain dependency tree (1 low, 8 moderate, 24 high, 5 critical); lockfile was not changed.
red_team: no actionable bypass found; known finality limit and same-Store nonce coordination boundary retained

cross_branch_findings: none requiring shared-code changes
BASE_REAL_ON_CHAIN: UNVERIFIED
external_blockers: protected signer/key file, matching publisher address, and sufficient Base Sepolia ETH are unavailable to verify
remaining_in_scope_gaps: real deployment, publication, receipt/event reconciliation, independent explorer verification; cannot proceed without DOD-05 prerequisites
dependency_risk: existing Ganache/solc test toolchain install reported 38 npm audit advisories; test-only tooling, not part of the Python runtime dependency set; no dependency update was attempted.

push: NO
pr: NO
main_modified: NO

FACTORY_REVIEW_READY: YES for local software candidate with external Base deployment explicitly unverified
