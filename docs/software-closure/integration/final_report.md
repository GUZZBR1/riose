# RIOSE Final Canonical Software Closure Integration

## Governed result

**PASS_CANONICAL_INTEGRATION_WITH_FOLLOWUPS** on the local integrated tree. All six Software Closure candidates are represented by reachable commit history and reconciled implementation/evidence. Local mandatory gates pass. Publication is **EXTERNAL_BLOCKED** because GitHub DNS resolution failed during the remote refresh attempt; remote freshness is **UNVERIFIED**. No remote was changed and no branch or worktree was deleted.

## Canonical tree and recovery

- Repository: `GUZZBR1/riose`
- Integration branch: `software-closure/final-canonical-integration`
- Base canonical SHA: `b2ddf11098ecd87b954bf97af26f8ecb8862b58a` (cached `fork/main` at integration time)
- Validated implementation SHA: `a1dbaca2db0aff42a2c18aba0300bea1cfc263c1`
- Validated implementation tree: `ea0fde9aaf32ee980da2cbae76e1d6c9260c77da`
- Local `main`: `e57b235a452c6e8d258d1708d5fd53ce56cecfb3`
- Cached `fork/main`: `b2ddf11098ecd87b954bf97af26f8ecb8862b58a`; cached `origin/main`: `c85c5f9bacf8065ceae95d45f173ad18418e5fda`
- Recovery ref: `recovery/pre-software-closure-integration-2026-10-08`
- The evidence-package commit will follow the validated implementation commit; its final SHA and tree SHA are returned in the Factory packet.

## Integration disposition

| Candidate | Disposition | Canonical result |
| --- | --- | --- |
| SC-1 `4bcf18ec6a2be9000d5a4e78c490dd9f330aceef` | INTEGRATED | Persisted bounded retry, backoff/jitter, crash recovery, ambiguous-attempt handling, duplicate suppression, reconciliation, and nonce coordination retained and exercised. |
| SC-2 `091efd561e8b575c2db3d08c645e88f02e56a8ad` | INTEGRATED | Stronger descriptor-based Solana signer validation selected; EVM and event/outbox hardening retained. |
| SC-3 `60a1222212e4e250948aea7ed788cf0a94f72b6f` | INTEGRATED | All 12 branch commits considered and included; reproducible environment and smoke path retained. |
| SC-4 `33b62c04ad97b51bec98afee41335b108e5ca17f` | INTEGRATED / RECONCILED | CI and scientific gates retained; workflow updated for complete history, locked setup, EVM dependencies, and the full configured Python test paths. |
| SC-5 `2b1d2ace05ffc2846533f9c1fb9d2b2ede7d34fa` | INTEGRATED / RECONCILED | EVM network guard and public-evidence structure retained; SC-2 signer implementation retained with SC-5 non-POSIX symlink precheck. Public-chain claims remain unverified. |
| SC-6 `425b71b9dcce59f993e4f79c30cf21aa4d71f82b` | INTEGRATED / HISTORICAL EVIDENCE | Closure matrix and useful evidence/claim clarifications retained; stale workflow was reconciled with SC-3/SC-4 and historical reports are not current-tree proof. |

All six candidate commits are ancestors of the integration branch. SC-3 contributes 12 unique commits from the shared base; SC-4 contributes two; the other candidates contribute one or two as recorded in the ledger. Historical SC-1/SC-2 source manifests describe CRLF byte streams; the canonical Git blobs use normalized LF. This provenance difference is documented and does not indicate omitted source behavior.

## Verification

All results below apply to implementation SHA `a1dbaca2db0aff42a2c18aba0300bea1cfc263c1` and tree `ea0fde9aaf32ee980da2cbae76e1d6c9260c77da`.

- PR_FAST: **PASS**, 85 passed; compileall and diff checks passed.
- SCIENTIFIC: **PASS**, 315 passed, one expected non-POSIX symlink-precheck test skipped on POSIX.
- MAIN full Python regression: **PASS**, 952 passed, eight governed skips, one Starlette/httpx deprecation warning. Seven skips are CadQuery export tests because CadQuery is unavailable locally; the dedicated CAD workflow installs it. One skip is a non-POSIX symlink precheck on POSIX.
- Security/publication focused suite: **PASS**, 169 passed and one expected platform-specific skip. SEC-SOLANA-001 is closed on this local integrated tree, with native Windows ACL and path-race limitations recorded in the security results.
- Local EVM: **PASS**, two tests; Ganache 7.9.2 and solc 0.8.37 are locked and available.
- Solidity compilation: **PASS**, solc 0.8.37.
- CTest: **PASS**, 39/39 from a fresh CMake build directory.
- Bootstrap and offline lock check: **PASS**. Doctor reports all required checks READY and optional simulation/hardware toolchains missing; overall status is `OPTIONAL_MISSING` for those optional tools.
- Package build: **PASS** offline with pinned build constraints. The initial online dependency resolution was blocked by DNS to pypi.org; cached offline build succeeded.
- Integrated local smoke: **PASS**, synthetic event through Event V1, SQLite persistence, Commitment V1, mock publication, restart, and receipt reconciliation. `real_on_chain=NOT_EXECUTED`.
- Three-target reproduction flow: **PASS**, local/mocked only.
- HEAVY remains **REQUEST_ONLY**; no heavy campaign was run.

Commands and structured evidence are in `test_results.json`, `reproducibility_results.json`, `scientific_gate_results.json`, and `security_results.json`.

## External state and preservation

`git fetch --all --prune` failed because `github.com` could not be resolved. Therefore cached remote refs are not asserted to be current. No push/publication was attempted, no public-chain transaction was attempted, and no upstream repository was modified. Branch cleanup was not executed: all six candidate branches, the recovery ref, tags, dirty worktrees, and unrelated work were preserved. The local integration worktree is the only worktree created for this mission; the original dirty checkout was left untouched.

## Claims and limitations

- Public Solana Devnet, Base Sepolia, and Arbitrum Sepolia: **UNVERIFIED**.
- RF and localization: **SIMULATED**; hardware: **NOT_VALIDATED**; field: **NOT_PERFORMED**.
- Native Windows ACL behavior, public CI state, external remote freshness, and ignored-file/reflog secret scanning were not verified.
- The red-team preservation check establishes candidate commit ancestry and inspected worktree state, not an exhaustive byte-level inventory of ignored files in every unavailable worktree.
- No required unique candidate commit was found outside the integration history; unique required work lost: **0**.

## Factory disposition

The local integration and evidence are ready for Factory review. Publishing and branch cleanup remain separate follow-ups blocked by unavailable remote freshness. Recommended simulation readiness: **READY_WITH_LIMITATIONS**.
