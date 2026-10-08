# RIOSE SC-6 — Final Software Closure Gate

**Reported status:** AUDIT_COMPLETE_WITH_FOLLOWUPS
**Recommended closure:** SOFTWARE_READY_WITH_FOLLOWUPS
**Factory verdict:** not assigned by executor
**Source/base SHA:** b2ddf11098ecd87b954bf97af26f8ecb8862b58a
**Branch:** software-closure/sc6-final-gate
**REMOTE_FRESHNESS:** UNVERIFIED

## Authority and discovery

Selected locally cached fork/main at b2ddf11. Cached upstream origin/main is c85c5f9; merge base 5b17771; graph counts are 84 fork-only and 1 upstream-only. Fetch and GitHub PR/API lookup failed because github.com did not resolve. No upstream/main mutation or public-chain write occurred. The original dirty checkout and other pre-existing dirty worktrees were preserved. SC-1/2/3/5 named branches point to the same cached fork/main SHA; their worktrees contain uncommitted evidence or are clean. No SC-4 named branch was found.

## Audit result

- **Architecture:** one canonical Event V1, Commitment V1, dispatcher/outbox lifecycle, SQLite persistence, and target adapters; no large structural issue found.
- **Event:** deterministic schema/hash and malformed-input tests pass. Event API lacks request idempotency; no external anchor proves tail completeness.
- **Commitment:** golden vectors and target fan-out tests pass. Target/network does not change the canonical digest.
- **Persistence/offline-first:** current-source tests and smoke validate local queue, restart, and mock reconciliation. This does not establish distributed durability.
- **Multichain:** all three software adapter paths pass local tests. Base and Arbitrum share EVM logic with target-specific configuration. No public receipt was found.
- **Security:** SEC-SOLANA-001 is open; PUBLIC_SIGNER_READINESS is NOT_READY. It blocks funded/public Solana signing, not the entire local software core.
- **Dependencies/reproducibility:** uv lock check and 68-package consistency pass. Tests used cached matching environments; clean-room install and live advisory lookup were unavailable. Level: CACHED_REPRODUCTION.
- **CI:** core workflow omitted EVM optional dependencies despite full-suite EVM imports. This branch adds the EVM extra; local suite passes, remote CI remains unverified.
- **Science:** RF/localization remain SIMULATED, Behavior ML remains research-only, and hardware/field claims remain unvalidated.

## Verification

Full Python: **884 passed, 7 skipped**, one Starlette/httpx deprecation warning. The seven skips are CAD/mechanical tests because CadQuery is absent. Focused Event/Commitment/Solana/EVM/outbox/dispatcher: **117 passed**. CMake build and CTest: **39/39 passed**. Compileall, uv lock check, uv pip check, and pre-package git diff check passed. Local Ganache/Solidity tests are not public-chain evidence.

Integrated local smoke: synthetic input → Event V1 → SQLite → common commitment → three offline mock targets → two restarts → reconciliation. Result: 12 simulated observations, 3 queued targets, shared commitment, zero pending and SQLite integrity check ok. No public write occurred. See integrated_smoke.json and rerunnable reproduce_flow.py.

## Gap classification

- **Internal follow-ups:** Solana key-loader hardening; Event API idempotency; external chain anchor; bounded retry backoff and additional crash-window tests.
- **External blockers:** remote freshness/PR/CI lookup and public testnet evidence.
- **Hardware required:** target board, HIL, calibrated bench and physical RF.
- **Field required:** controlled farm trial and field localization accuracy.
- **Future product:** operational behavior/health/reproduction requires labeled validated evidence.

## Recommendation

**Technical stage:** BETA_CANDIDATE. Versioned contracts, local persistence/outbox, three software adapter paths, and broad regression exist; public chain, operational hardware, field performance, and clean-room reproduction remain unverified. Production readiness is not supported.

**Digital Farm Simulation V2:** SIM_V2_READY_WITH_LIMITATIONS. Software interfaces and synthetic evidence are usable; physical channel, clock, antenna, and field accuracy remain outside the evidence.

**Recommended Factory review:** SOFTWARE_READY_WITH_FOLLOWUPS. External chain blockers need not prevent software closure, but public claims remain unverified and open signer/persistence follow-ups stay visible. Executor reports a recommendation only; Factory owns the final verdict.
