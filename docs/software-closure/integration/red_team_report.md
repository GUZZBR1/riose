# Independent Red-Team Report

## Scope and verdict

Read-only review of the integrated implementation, branch ancestry, security selection, gate wiring, claims, and evidence provenance. The review found no remaining P0, P1, or P2 internal defect after the collection-skip issue below was repaired. **PASS_WITH_LIMITATIONS** for the local integration.

The reviewer did not execute tests independently. Ignored files and reflogs were not scanned, public CI was unavailable, and some worktrees could not be inspected because they were unavailable or marked prunable. The six candidate histories were checked for reachability; this does not prove byte-level preservation of every untracked or ignored file in every worktree.

## Findings and disposition

1. **Pytest collection skips could evade skip governance.** The first review found the governance hook handled test runtime reports but not collection reports. The integration now records both through a shared skip handler and includes a regression test. PR_FAST, SCIENTIFIC, and MAIN were rerun after the repair and passed.
2. **SEC-SOLANA-001 selection.** SC-2 is stronger than SC-5 for the POSIX signer path: nonblocking/no-follow descriptor open where supported, strict UTF-8 and exactly 64 integer bytes, bounded oversized-input rejection, regular-file validation, POSIX ownership/mode checks, and sanitized parse failures. The SC-5 non-POSIX `islink` precheck was retained. No duplicate signer implementation was introduced.
3. **CI/reproducibility reconciliation.** The final workflow fetches full history for historical commit validators, installs the EVM dependencies, uses locked tool setup, and covers the configured Python test paths including `hardware`. The full local MAIN, PR_FAST, SCIENTIFIC, and CTest gates passed.
4. **SC-6 evidence is baseline-bound.** Historical closure reports and hashes are not represented as current-tree validation; the final package has its own source/tree-bound results.
5. **Historical line-ending hashes.** SC-1 source/test evidence hashes refer to CRLF bytes while canonical Git blobs use LF; source content agrees after newline normalization. SC-2's `security/discovery.json` differs only by final LF/CRLF normalization. The final integration manifest hashes canonical files directly.
6. **Claims and boundaries.** No public transaction, physical hardware, field result, or accuracy claim was promoted. Mock and simulation boundaries remain explicit; HEAVY remains REQUEST_ONLY.
7. **Git safety.** The integration is based on the locally cached fork base and has a recovery ref. Remote fetch failed on DNS, so nothing was pushed and no candidate, recovery, or unrelated branch/worktree was deleted.
8. **Dependency advisory scope.** Offline `npm ci` completed successfully, but its zero-vulnerability install message is not a fresh online advisory review. The inherited SC-2 advisory evidence remains separately scoped.

## Residual limitations

- Native Windows ACL behavior is untested. `O_NOFOLLOW` is conditional on platform support; non-POSIX path precheck is not atomic against concurrent replacement, and ancestor-directory symlinks are not blocked.
- External GitHub state is stale/unverified after DNS failure.
- The review did not scan ignored files or reflogs, and did not independently inventory unique uncommitted data in every unavailable/prunable worktree.
- The secret-scan evidence is inherited local evidence, not a fresh whole-repository or history scan.

## Evidence reference

Implementation reviewed: `a1dbaca2db0aff42a2c18aba0300bea1cfc263c1` (`ea0fde9aaf32ee980da2cbae76e1d6c9260c77da`). Full current-tree results and limitations are recorded in the adjacent integration package.
