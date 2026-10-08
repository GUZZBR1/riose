# RIOSE SC-4 — CI & Scientific Integrity Gates

Status: PASS_CI_WITH_LIMITATIONS. Local gates are implemented and validated; no remote CI result is claimed.

The evidence package is built on the verified `fork/main` baseline `b2ddf11098ecd87b954bf97af26f8ecb8862b58a`, in the isolated branch `software-closure/sc4-ci-scientific-gates`. The historical claim registry is preserved unchanged. See `local_ci_results.json`, `evidence_records.json`, and `manifest.json` for reproducible local evidence and integrity hashes.

## Gate results

- PR_FAST: 83 passed in 2.06 s.
- SCIENTIFIC: 275 passed in 22.02 s.
- Full Python regression: 664 passed in 71.08 s; zero skips; one Starlette deprecation warning.
- CAD export: 7 passed, 34 deselected in 7.31 s.
- Host C: build succeeded; CTest 39/39 passed. This is host-only evidence.
- Solidity registry compilation and ABI/bytecode checks passed.
- Offline Python wheel build passed.
- Heavy interface smoke emitted a provenance-bound `REQUEST_ONLY`/`UNVERIFIED` request. It did not execute a campaign.

## Limits and disposition

The clean `npm ci` install could not complete because DNS access to the npm registry was unavailable. The local Ganache test passed using an existing dependency tree verified against the target lockfile versions and integrities. GitHub Actions, branch protection, hardware, field, and public-chain execution were not verified. `SEC_SOLANA_001` remains OPEN. No Digital Farm V2 or SIM-1 through SIM-8 execution is claimed. See `limitations.json` for the complete boundary.
