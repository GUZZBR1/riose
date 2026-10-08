# SC-6 Red Team Report

Source SHA: b2ddf11098ecd87b954bf97af26f8ecb8862b58a. Read-only review, current regressions, and integrated smoke were used. No public-chain write was attempted.

## Findings

1. SEC-SOLANA-001 remains OPEN. The loader at src/riose/products/livestock_tracking/adapters/solana_memo.py:287-299 follows caller paths, does not check file mode or type, and parses only a 4096-byte prefix without strict EOF validation. Prior SC-2 and MVP6 evidence records symlink, permissive-mode, and trailing-content probes against this exact source SHA. The current source is unchanged. PUBLIC_SIGNER_READINESS is NOT_READY. This blocks funded Solana signing, not local Event, commitment, or persistence software closure.
2. Remote freshness is unverified. Fetch and GitHub API failed on DNS. Local green checks cannot represent remote CI.
3. Public-chain proof is absent. Ganache and mock adapter evidence are local only. Solana, Base, and Arbitrum public status remains UNVERIFIED.
4. Persistence limits remain. There is no external event-head anchor or Event API idempotency key; retry scheduling and all crash windows are not proven.
5. Scientific and physical limits remain explicit. RF and localization are simulated; convergence is not accuracy; PHY reception is not application delivery; no HIL or field validation exists; behavior ML is research-only.

## Counterevidence

Full Python: 884 passed and 7 skipped. Focused tests: 117 passed. CTest: 39/39. Integrated synthetic smoke survived two restarts, reconciled three mock targets with one shared commitment, and left zero pending requests with SQLite integrity result ok. The CI core job's missing EVM extra was repaired locally; remote job status remains unverified.

Conclusion: recommend SOFTWARE_READY_WITH_FOLLOWUPS for Factory review. No absolute completion, public deployment, production, hardware, or field claim is supported.
