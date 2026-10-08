# RIOSE SC-2 Security & Dependency Closure

## Reported result

PASS_SECURITY_WITH_RESIDUAL_RISK. SEC-SOLANA-001 was reproduced against the baseline, corrected, and verified with synthetic adversarial fixtures. Independent red-team probes also led to fixes for Event/outbox duplicate-key parsing, EVM signer file handling and priority fee validation, and Solana RPC receipt binding.

## Verification

- Full Python regression: 916 passed, 7 skipped, 1 deprecation warning. All skips are CadQuery-dependent mechanical tests; CadQuery is absent in this environment and the repository identifies a dedicated CAD CI job.
- Focused security/publication/EVM tests: 155 passed.
- Hardware CTest: 39/39 passed.
- Local EVM/Solidity tests are included in the focused suite and passed (2 integration cases). They compile with locked solc 0.8.37 and execute on local Ganache only.
- compileall, uv lock --check (Windows-host uv), uv build (sdist and wheel), and git diff --check passed. The npm package defines no test script.

## Findings

Five in-scope findings were fixed and tested: SEC-SOLANA-001 keypair loading; Event/outbox duplicate JSON keys; EVM signer file validation and redaction; configured EVM priority-fee enforcement; and Solana RPC duplicate-key/signature binding. (The signer concerns are split by chain in the findings matrix.) Remaining risks include API authentication if network exposed, plaintext/local SQLite integrity limits, tooling dependency advisories, platform validation, unavailable specialized scanners, and unverified remote freshness.

The current npm audit CLI snapshot reports 38 advisories in the local EVM/compiler dependency tree (1 low, 8 moderate, 24 high, 5 critical). The separate npm lock/advisory query includes 73 matches, 57 extraneous Ganache shrinkwrap records, 15 test dependency records and one compiler dependency record. These were not demonstrated as exploitable through production application entrypoints; no forced upgrade was attempted. Python OSV scan found one moderate pytest test-only finding. See the dependency reports and residual register.

## Limitations

No public RPC, blockchain transaction, real funds, or mainnet use occurred. GitHub remotes could not be refreshed from WSL due DNS, so REMOTE_FRESHNESS=UNVERIFIED. gitleaks, Slither, Forge, standalone solc and CadQuery were unavailable. The fallback secret scan is not equivalent to gitleaks and did not include ignored files or Git history. Native Windows ACL semantics were not tested.

The evidence supports a controlled testnet attempt only. It is not a production security certification and does not claim that the system is free of vulnerabilities.
