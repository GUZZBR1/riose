# RIOSE Main + Multichain Reconciliation

## Decision and authority

- Fork authority: `GUZZBR1/riose` (`fork` remote).
- Freshly fetched `fork/main`: `a974a4e9f5008487d70f3ab8f71a78c9465158ac`.
- Approved Multichain candidate: `a45908b6eecb347fb5e2f6bf1e111f10885a4647`.
- Actual merge base: `b2de3a9a58f911e24dc9a8395717f520542282b3`.
- The supplied merge-base value `b2de3a9a58f911e24dc9f2d0060cf53c8ffe6901ed` is not a valid object in this repository; it is recorded as a transcription error.
- A local recovery ref, `recovery/main-pre-multichain-reconciliation-2026-10-07`, points to the fresh main SHA.
- Reconciliation branch: `multichain/main-reconciliation`, created from `fork/main`; candidate was merged locally with a two-parent merge. Neither remote was changed.

The initial ancestry was 4 main-only commits and 18 candidate-only commits from the actual merge base. The reconciliation merge preserves both histories. Main is the first parent and the approved candidate is the second parent.

## Main-only commit audit

| Commit | Purpose and changed behavior | Files / tests / Multichain relation | Disposition |
| --- | --- | --- | --- |
| `2beb7a5dd5681cbc7b5fc308f5e3a12301b85686` | Preserves reproducible pre-Web3 work; adds strict event/network/temporal identity and request sequencing, H.2 dynamic localization with calibrated uncertainty, and bounded simulated RF evidence. The workflow installs the Solana extra. | Inventory/provenance and baseline docs; simulation contract, farm RF/network and runner; TDOA v2 implementation/tests; Renode conversion path. Commit records 788 pytest passes, 7 skips, CTest 39/39, and focused checks. These capabilities are outside Multichain's publication paths and remain covered in the merged suite. | **PRESERVE** |
| `4aafeb955786d3582282b53b555f70182e5656de` | Records the verified publication of the pre-blockchain baseline; no runtime behavior change. | `PRE_BLOCKCHAIN_INTEGRATION_PROVENANCE.json`, `docs/PRE_BLOCKCHAIN_BASELINE.md`; commit records PR 37 and CI jobs 81/85. No overlap with Multichain implementation. | **PRESERVE** |
| `e32235b86d1e6f0042f6490b223bdf155bc2827f` | Captures simulated LIS2DW12 firmware trace lineage, adds sensor-range guarding and a tag-only digital-twin path that can skip unresolved antenna work. Evidence remains simulated. | Renode trace fixture/converter/tests, digital-twin runner/tests, and research evidence. Commit records 794 pytest passes, 7 skips, focused tag/RESD 55 passes, CTest 39/39. No Multichain publication-path overlap. | **PRESERVE** |
| `a974a4e9f5008487d70f3ab8f71a78c9465158ac` | Records publication and CI closure for the tag-trace baseline; no runtime behavior change. | Provenance and baseline docs; commit records PR 39 and CI run 89. | **PRESERVE** |

No main-only change was classified `RECONCILE`, `ALREADY_SUPERSEDED`, `CONFLICT`, or `INVALID`. None had an equivalent implementation in the Multichain candidate that justified dropping it.

## Change impact map

| Area | Main-only side | Multichain side | Reconciliation / evidence |
| --- | --- | --- | --- |
| Event V1 / canonical commitment | No changed paths. | Existing canonical event commitment and publication envelope. | Preserved unchanged; Event V1 and commitment/privacy tests pass. |
| Persistence / SQLite / event chain | Main adds no changed paths here. | Publication outbox, receipts, attempts, recovery and nonce coordination. | Preserved; event-chain concurrency, persistence, outbox, and nonce tests pass. |
| Publication / blockchain / Solana / EVM | Main adds no changed paths here. | Generic dispatcher, Solana Memo adapter, EVM registry adapters and contract tests. | Preserved; local three-chain fanout proves one commitment with separate targets and receipts. |
| CLI / API | Main adds no changed paths here. | Publication CLI integration. | Preserved; focused CLI and publication tests pass. |
| Simulation, localization, firmware evidence | Main's four commits contain these additions. | Candidate does not change these paths. | Preserved; main-specific tests and full suite pass. |
| Dependencies / lockfiles | No main-only package or lockfile path changes. | Candidate adds EVM Python dependencies and contract npm lock. | Preserved. Corrected the nested Darwin-only `fsevents` lock entry to `optional: true`; offline `npm ci --dry-run` then succeeds. |
| Documentation / claims | Main adds pre-blockchain provenance and simulated evidence. | Candidate adds Multichain handoff and test evidence. | Both histories and reports are retained. Blockchain and field claims remain bounded below. |

Path comparison of `merge-base..fork/main` and `merge-base..candidate` found **0 shared changed paths** (56 main paths, 36 candidate paths). Git therefore reported no textual conflict. This does not prove semantic correctness; the focused and full regression runs below cover the cross-cutting behavior.

## Main behavior preservation checklist

- [x] Pre-blockchain inventory, provenance, baseline and publication records remain in the tree.
- [x] Workflow retains the `uv sync --extra solana` dependency setup.
- [x] Temporal identity, request sequencing, strict event/network/schedule validation and seeded phase-window behavior remain in the simulation path; `test_farm_network.py` and dynamic-localization tests pass.
- [x] TDOA v2 clock calibration, uncertainty and untrusted-calibration behavior remain in place; TDOA v2 and dynamic-localization tests pass.
- [x] LIS2DW12 range guard, trace lineage, golden-axis fixture and dataset-to-RESD conversion remain present; the full test suite includes the Renode converter tests.
- [x] Tag digital-twin `--skip-antenna` route remains present; digital-twin tests pass.
- [x] FREQUENCIA remains external; physical, field, and Renode hardware claims are not upgraded by this Git integration.

## Multichain invariants and E2E

The local E2E test `test_three_chain_local_evm_fanout_uses_one_event_and_independent_receipts` exercises Event V1 → one canonical commitment → three publication targets. Base Sepolia and Arbitrum Sepolia chain IDs run on separate local Ganache instances; Solana is a mock adapter. The assertions verify the shared commitment, three independent transaction identifiers, independent confirmed/verified receipts, local binding, privacy of the tag identifier, and successful EVM receipt logs. The dispatcher/outbox/Solana/nonce suites cover pending/retry/recovery and isolation behavior.

This is **local software evidence only**. It is not public-chain validation.

## Verification evidence

Linux/WSL was used for code and test verification.

| Check | Result |
| --- | --- |
| Main-specific + Multichain-focused pytest selection | **252 passed**, 1 warning. Includes all four main-specific Python test files and Event V1, persistence, publication, Solana, EVM registry, nonce, and local-EVM tests. |
| Full Python suite on reconciled worktree | **884 passed, 7 skipped**, 1 existing Starlette/httpx deprecation warning. |
| Three-chain local EVM test file | **2 passed**. |
| `compileall -q src tests` | Passed. |
| `pip check` | No broken requirements. |
| Solidity registry compilation with locked `solc` | Passed; ABI and bytecode produced. |
| Python wheel and sdist | Passed using Hatchling provisioned in a temporary directory. |
| Contract lock metadata | Root dependencies match `package.json`; resolved lock entries include integrity metadata. `npm ci --dry-run --offline` passed after the optional-platform metadata correction. |
| `git diff --check` | Passed before the audit artifact was added. |

Environment note: a full `npm ci` could not download packages because WSL DNS returned `EAI_AGAIN` for `registry.npmjs.org`. The first install attempt also exposed that the lock entry for Ganache's optional macOS-only `fsevents` package lacked its optional marker. The marker is now recorded and npm's offline dry-run accepts the lock. E2E used the existing Linux-native Ganache and solc modules from the approved candidate checkout; Ganache warned that its optional µWS native binary did not match Node 22 and fell back to its JavaScript implementation. The local EVM tests passed under that fallback.

## Red-team review

Adversarial checks looked for omitted main history, same-path conflicts, commitment mutation, chain-specific state leaking into Event V1, shared target/receipt state, offline-first regressions, retries/recovery defects, nonce reuse, weak local-EVM assertions, and overstated validation claims. No recoverable behavior finding remained after review and test execution. The merge retains main as first parent and the exact approved candidate as second parent; main-specific tests and the full suite pass.

The Codex native independent-review launch failed twice because the available model was rejected by the platform. The leader therefore performed the repository-required sequential red-team pass and records that limitation here; no independent subagent verdict is claimed.

## Governed claims and decision

```text
MULTICHAIN_SOFTWARE = COMPLETE
SOLANA_REAL_ON_CHAIN = UNVERIFIED
BASE_REAL_ON_CHAIN = UNVERIFIED
ARBITRUM_REAL_ON_CHAIN = UNVERIFIED
FIELD_VALIDATION = NOT_PERFORMED
FREQUENCIA = EXTERNAL
```

The reconciliation is local-only. No push, PR, main update, or upstream update was performed. The candidate is a descendant of the fresh fork main and is eligible for a future fast-forward promotion only after the final detached-checkout verification is recorded in the delivery report.
