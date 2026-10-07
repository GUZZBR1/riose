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
| DOD-10 | Run focused Base tests, EVM Core, contract/Solidity, Solana, persistence, full Python, clean detached checkout, build/package/dependency checks | Exact commands/results at final HEAD | UNVERIFIED |
| DOD-11 | Independent red-team review attempts all mission-listed attacks; fix recoverable findings | Independent review and disposition evidence | COVERED — no bypass; finality, single-RPC, and shared-SQLite nonce scope documented |
| DOD-12 | Compare final candidate with M3 and report all cross-branch findings and remaining gaps | Baseline comparison and final report | UNVERIFIED |

## Checkpoints

- **C0 — baseline and DoD:** completed before implementation.
- **C1 — implementation/configuration:** complete; verified Base Sepolia identity and a focused test through the shared config/adapter; no deployment config can be completed without deployment-bound values.
- **C2 — local and regression validation:** pending.
- **C3 — red-team and clean-checkout verification:** pending.
- **C4 — final M3 comparison and report:** pending.

## Evidence ledger

| Evidence | Source | Freshness | Uncertainty | Coverage |
|---|---|---|---|---|
| Base Sepolia chain ID | Base official RPC response and official Base docs | CURRENT | OBSERVED | DOD-03, DOD-05 |
| Base Sepolia genesis hash | Two independent RPC responses; official RPC prunes block 0 | CURRENT | OBSERVED | DOD-03, DOD-05 |
| M3 software/handoff | Approved base source and M3 report | CURRENT at baseline SHA | VERIFIED | DOD-01, DOD-02, DOD-09 |
| Signer and funded balance | No configured key file path/address; not checkable without a safe signer | CURRENT | UNKNOWN | DOD-05 through DOD-07 |

## Independent red-team disposition

The independent read-only review found no new actionable bypass in the requested chain/RPC identity, commitment, contract trust, secret handling, receipt correlation, retry/recovery, duplicate dispatch, privacy, or Core separation checks. It confirmed the existing adapter validates chain ID, genesis, and runtime code hash; binds signed transactions to the configured publisher/contract/commitment; and validates persisted wire before replay. The existing SQLite nonce coordinator protects workers sharing the same Store. Distinct databases using the same signer do not coordinate reservations and remain an operational boundary. Confirmation depth is still `ASSUMED`, not irreversible finality; terminal `VERIFIED` does not detect a later deep reorganization. No shared dispatcher change was recommended or made.

## Recovery task: simulation runner timeout during full suite

- Operation: first full Python suite on the candidate.
- Failure: `tests/simulation_lab/test_runner.py::test_process_failure_output_timeout_and_malformed_response_are_structured` expected `output exceeded`; the child process instead hit the test's 0.2-second timeout while writing 3 MB.
- Diagnosis: timing-sensitive test/environment behavior; unrelated code was unchanged. The entire parameterized test passed in isolation (5 passed), so no source or expectation was altered.
- Resolution check: final full suite in the clean detached checkout is required before completion.
