# RIOSE Pre-SIM release report

Candidate 64846b0b6182cc0b248fe453dd875e0170c5a929 (tree 14bfa86aa1d1b38fc8c2c203742971ae32e6a04b) is a locally validated canonical candidate on release/pre-sim-canonical. It includes the SC-1 to SC-6 candidate d74ceacc08960002bc547d39cca42713280b600e reconciled to refreshed fork main b2ddf11098ecd87b954bf97af26f8ecb8862b58a, plus the accepted visual subset of PR #41. SIM V2 was not started.

## Verdict

PASS_PRE_SIM_RELEASE_WITH_FOLLOWUPS. The non-force fast-forward publication succeeded at SHA 0aaa42a173027c0c26a2563c10ee5b45d2562792. The five remote checks completed: four success and the heavy-validation request skipped. PR #41 was closed with audit comment 6065411992. Final self-audit found no P0/P1 in the candidate; PR tokenization P1/P2 findings remain excluded. Delegated final reviewer calls were unavailable because this account rejected their configured models. PR #41 verdict: PARTIALLY_INTEGRATE. The original PR was not merged directly. Its useful visual subset was integrated and it was closed with the technical disposition. Two local redundant refs were deleted only after proving their tips are in published main and no worktree depends on them; no worktrees were removed.

GitHub fetch and REST reads succeeded. PR #41 was open, not draft, and mergeable at its latest-head refresh, at head 79af412aff8a63e7b563d49f3e03f4d8c07c40ec. The PR has 33 commits and 116 changed files. Latest-head isolated tests: farm 22/22; API/integration 29; security subset 90; web3 build passed with 12 moderate advisories; PR E2E failed its 2.5-second stability wait, which was repaired in the candidate. The WSL gh token was invalid, but the configured Windows Git credential enabled the authorized non-force push and PR closure. Remote CI passed for the published SHA.

## Validation

Python: 953 passed / 8 expected skips. Security subset: 128 passed / 1 expected skip. Publication reliability: 65 passed. PR_FAST: 85 passed. Scientific: 315 passed / 1 expected skip. CTest: 39/39. Local EVM: 2 passed. Solidity compile: passed. Frontend tests: 22/22 passed on the final candidate through Windows Node, including typecheck/build; reconciled candidate E2E passed. Initial WSL rerun had a tsc execute-permission issue, resolved by using Windows Node. Post-commit API/integration tests: 25 passed. Integrated deterministic smoke passed with local/mock fixtures; public-chain evidence remains unverified.

Inherited contracts test-toolchain audit reports 9 advisories (1 critical, 7 high, 1 moderate) in local Ganache/solc dependencies. No dependency change was made; farm-demo audit found zero vulnerabilities.

## PR #41 decision

The diorama, responsive scene, accessible animal selection, local event readback, and preview-only identity card are accepted with reconciliation. The guided Solana identity flow, asset API/storage, public metadata, and wallet/signing path are rejected pending authentication, private-data separation, ambiguity-safe recovery, exact transaction verification, and canonical architecture integration. The virtual-fence deletion is rejected; functionality remains at /simulator.

## Publication and cleanup

Initial published main SHA is 0aaa42a173027c0c26a2563c10ee5b45d2562792. The documentation-only closeout was committed and fast-forwarded to main after test, PR, cleanup, and evidence results were recorded. The final verified main SHA is reported in the handoff packet. Existing local main at e57b235a was a fast-forward ancestor and was advanced to the published candidate SHA. No force push was used. Local main and remote main matched at publication. Cleanup removed two proven redundant local branches, preserved all worktrees, and retained recovery, archive, upstream, dirty, and unknown refs. All refs/worktrees are inventoried; no unique work was lost.

## Final independent audit closeout

The independent reviewer identified a stale SHA-256/byte-count record for `security/discovery.json` in `security/manifest.json` on the previously published tree. The entry now matches the artifact (SHA-256 `33060cf85ce03bfc9d333607a18d8dc0cde27284e368c0f77edd75b551414590`, 7,345 bytes). Affected PR_FAST, scientific, and security-focused regression gates passed after the correction. The initial WSL DNS lookup failed; fresh remote fetch and `git ls-remote` then succeeded using a one-command GitHub DNS resolution override to the address resolved by Windows. GUZZBR1/riose `main` remains `1f689a806bbf5921a2b7a4605fa28b989416ea43` and is an ancestor of this closeout branch. Publication of the evidence correction and CI for its final SHA remain pending.

## Claim limits

Software core, offline-first, and multichain software are validated locally. Solana/Base/Arbitrum public testnets are UNVERIFIED. RF/localization remain SIMULATED; behavior ML remains research-supported/not operational; hardware is not validated; field testing was not performed. See claim_registry.json.
