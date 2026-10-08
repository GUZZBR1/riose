# SC-5 — REAL_ON_CHAIN public testnet validation

## Governed result

`reported_status: EXTERNAL_BLOCKED_LOCAL_GATE`

`governed_status: EXTERNAL_BLOCKED_LOCAL_GATE`

The local pipeline, mainnet firewall, signer hardening, privacy review, persistence checks, and regression gates passed. All three public RPC endpoints failed DNS resolution during the current preflight. No signer was configured, and no verified Base Sepolia or Arbitrum Sepolia deployment configuration was found. No transaction was signed or submitted. Each target is independently classified `EXTERNAL_BLOCKED`; every public-testnet claim remains `UNVERIFIED`.

## Discovery and local gates

- Work ran on isolated branch `software-closure/sc5-real-on-chain`, based on the last local `fork/main` snapshot `b2ddf11098ecd87b954bf97af26f8ecb8862b58a`.
- `git fetch origin` failed with `Could not resolve host: github.com`; `REMOTE_FRESHNESS=UNVERIFIED`.
- The existing Event V1, Commitment V1, Solana Memo adapter, shared EVM registry adapter, dispatcher, SQLite outbox/receipt journal, EVM nonce coordinator, and registry contract were reused.
- The baseline Solana signer loader finding was reproduced by source audit and closed with symlink, regular-file, ownership, permission, bounded-read, and malformed-content checks. EVM prepare and submit now fail closed except supported Sepolia chains and loopback local EVM.
- A synthetic event used the existing Event V1 `SIMULATION_RUN_RECORDED` type; its payload marks `TESTNET_VALIDATION_EVENT` and `synthetic=true`. The repository rejects new event types, so no alternate Event V1 type was introduced.
- `SQLitePublicationOutbox.enqueue_event` created one canonical Commitment V1 and reused it for the three local target requests. The public payload review passed: Solana carries only the allowlisted envelope; EVM calldata carries the `register(bytes32)` selector and digest.
- Reopening the temporary SQLite database preserved all three local bindings. Re-enqueueing the Solana target reused its existing request. There are zero persisted attempts and zero receipts.

## Target verdicts

| Target | Verdict | Preflight | Submission | Independent verification |
|---|---|---|---|---|
| Solana Devnet | `EXTERNAL_BLOCKED` | DNS failure; signer unavailable | Not attempted | Not attempted |
| Base Sepolia | `EXTERNAL_BLOCKED` | DNS failure; signer unavailable; deployment missing | Not attempted | Not attempted |
| Arbitrum Sepolia | `EXTERNAL_BLOCKED` | DNS failure; signer unavailable; deployment missing | Not attempted | Not attempted |

No balance was checked because no signer or RPC was available. No explorer reference or transaction identifier exists. The local target queue equality is `PASS_LOCAL_ONLY`; public cross-chain commitment equality is `NOT_FULLY_TESTED`.

## Verification

- Focused Event, commitment, privacy, Solana, EVM, dispatcher, outbox, nonce, and local EVM tests: 132 passed.
- Full Python regression: 888 passed, 7 skipped, 1 existing Starlette/httpx deprecation warning.
- `compileall`, Python lock check, `pip check`, Solidity registry compilation, and `git diff --check`: passed.
- CTest hardware suite: 39 passed.
- `contracts/package-lock.json` is absent at the selected base. The installed dependency tree reports Ganache 7.9.2 and solc 0.8.37; no lock file was generated.

## Claims and limitations

No claims were promoted. `SOLANA_REAL_ON_CHAIN`, `BASE_REAL_ON_CHAIN`, `ARBITRUM_REAL_ON_CHAIN`, and `PUBLIC_TESTNET_VALIDATED` remain `UNVERIFIED`. This result does not claim mainnet, production, field, or hardware validation.

Remaining external requirements are reachable DNS/RPC, explicitly available secure testnet signers, and verified Base/Arbitrum testnet deployments. Native Windows ACL behavior was not tested; the signer security regressions ran on Ubuntu WSL. A chain transaction restart/reconciliation cannot be exercised without a public attempt.

The enclosing commit SHA and final tree are provided in the accompanying `CODEX_TO_FACTORY_PACKET`; embedding the exact SHA of the commit that contains this report would be self-referential.

## Evidence index

See `discovery.json`, `preflight.json`, `network_identity.json`, `signer_security.json`, `canonical_event.json`, `canonical_commitment.json`, `privacy_review.json`, the per-target directories, `restart_reconciliation.json`, `target_comparison.json`, `red_team_report.md`, `test_results.json`, `environment.json`, `limitations.json`, `claims.json`, and `manifest.json`.
