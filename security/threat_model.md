# RIOSE SC-2 Threat Model

## Scope and assumptions

This assessment covers the current local-first livestock tracking implementation, its SQLite/Event V1/Commitment V1/outbox flow, signer loaders, Solana and EVM adapters, local EVM contract tests, and locked dependency/tooling snapshots. The device side is simulated; no public transaction, real funds, or production deployment was used. Trust boundaries describe implementation evidence, not desired future architecture.

## Flow

Simulated tag/device -> API/CLI ingestion -> backend/domain validation -> SQLite -> Event V1 -> Commitment V1 -> publication outbox -> local signer -> RPC provider -> EVM registry or Solana Memo transaction

## Threat actors

- A malformed or malicious API/CLI caller, especially if an operator binds the API to a reachable interface.
- A local user able to modify database, configuration, or signer path contents.
- A malicious or compromised RPC provider returning malformed or mismatched responses.
- A compromised dependency/toolchain during local builds or tests.

## Security objectives

Keep signer material out of logs, exceptions, persistence and evidence; bind publication to the intended event/commitment and target chain; reject ambiguous persisted/RPC JSON; avoid unsafe file following/blocking; and preserve local record integrity against accidental or detectable tampering. Event hashes are unkeyed and do not authenticate a database owner.

## Boundaries

See trust_boundaries.json for each boundary's trusted/untrusted side, data crossing, assumptions, abuse cases, mitigations, and residual risk. Key boundaries are API-to-backend, backend-to-SQLite, outbox-to-signer file, adapter-to-RPC, and EVM adapter-to-contract.

## Findings and residuals

The prior Solana keypair loader issue was reproduced on the baseline and is now closed by strict descriptor-based loading plus adversarial tests. Red-team review found and led to fixes for duplicate JSON keys crossing the outbox boundary, EVM signer trailing/special-file acceptance and fee caps, and Solana RPC signature/duplicate-key validation. The current external API remains unauthenticated, SQLite is plaintext and locally writable by the process owner, npm/PyPI advisories remain in development/test/compiler tooling, and native Windows ACL/RPC-provider behavior was not exercised. These are recorded in findings.json and residual_risk_register.json.
