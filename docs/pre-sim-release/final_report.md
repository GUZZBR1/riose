# RIOSE Pre-SIM release report

Candidate 64846b0b6182cc0b248fe453dd875e0170c5a929 (tree 14bfa86aa1d1b38fc8c2c203742971ae32e6a04b) is a locally validated canonical candidate on release/pre-sim-canonical. It includes the SC-1 to SC-6 candidate d74ceacc08960002bc547d39cca42713280b600e reconciled to refreshed fork main b2ddf11098ecd87b954bf97af26f8ecb8862b58a, plus the accepted visual subset of PR #41. SIM V2 was not started.

## Verdict

LOCAL_RELEASE_READY_PUBLICATION_BLOCKED pending valid GitHub write credentials; final read-only review found no P0/P1 in the candidate, while PR tokenization P1/P2 findings remain excluded. PR #41 verdict: PARTIALLY_INTEGRATE. No direct merge, push, PR close, branch deletion, or worktree deletion has occurred.

GitHub fetch and REST reads succeeded. PR #41 is open, not draft, and mergeable at refresh, at head c8f4c62cf603dac04623f6f54dbb250784d5752f. Configured gh authentication is invalid, so write operations are blocked. Candidate remote CI is UNVERIFIED because it is not published.

## Validation

Python: 953 passed / 8 expected skips. Security subset: 128 passed / 1 expected skip. Publication reliability: 65 passed. PR_FAST: 85 passed. Scientific: 315 passed / 1 expected skip. CTest: 39/39. Local EVM: 2 passed. Solidity compile: passed. Frontend tests: 22 passed on the prior reconciled candidate; build and E2E passed. Final npm test rerun could not execute tsc because local node_modules/.bin/tsc lacked execute permission. Post-commit API/integration tests: 25 passed. Integrated deterministic smoke passed with local/mock fixtures; public-chain evidence remains unverified.

Inherited contracts test-toolchain audit reports 9 advisories (1 critical, 7 high, 1 moderate) in local Ganache/solc dependencies. No dependency change was made; farm-demo audit found zero vulnerabilities.

## PR #41 decision

The diorama, responsive scene, accessible animal selection, local event readback, and preview-only identity card are accepted with reconciliation. The guided Solana identity flow, asset API/storage, public metadata, and wallet/signing path are rejected pending authentication, private-data separation, ambiguity-safe recovery, exact transaction verification, and canonical architecture integration. The virtual-fence deletion is rejected; functionality remains at /simulator.

## Publication and cleanup

Current remote main is b2ddf11098ecd87b954bf97af26f8ecb8862b58a. Existing local main is e57b235a452c6e8d258d1708d5fd53ce56cecfb and was not moved because it is not an ancestor of this candidate. No force push or remote mutation was made. Cleanup was not executed because canonical publication is not confirmed. All refs and worktrees are inventoried; no unique work was lost.

## Claim limits

Software core, offline-first, and multichain software are validated locally. Solana/Base/Arbitrum public testnets are UNVERIFIED. RF/localization remain SIMULATED; behavior ML remains research-supported/not operational; hardware is not validated; field testing was not performed. See claim_registry.json.
