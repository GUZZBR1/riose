# RIOSE Integrated Beta — Definition of Done

**Authority:** Mini-MVP 6 integration mission  
**Base:** `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`  
**Approved source heads:** Firmware `15f63a4bef31f4985ffc0c911785b1043e656eae`; simulation `d11d8838f41dbd36da2020365b914a86e2262b76`; publication `0c482054a7a0b37c9c2d59a3d97641a0c57837d7`; intelligence `cb912a42ed089d8a1bfbbdbe3d95e13e1c4e0f48`; persistence `e0efe781c7109fd8c0ea3044654eed9175f4954b`.

This is the pre-integration acceptance contract. Each criterion must be evidenced against the integrated tree; source-branch evidence alone does not prove the combined tree.

## Acceptance criteria

1. Preserve the requested base and approved source provenance; do not modify `main`, either remote, or historical preservation refs. Keep FREQUENCIA external.
2. Reconcile Event V1, identity, event time, simulation time, firmware units, and tag/animal identity. Event V1 remains authoritative; simulated values and unavailable values are explicitly classified.
3. Use one Core SQLite Store. Preserve `BEGIN IMMEDIATE` before event-head reads, WAL, `synchronous=FULL`, five-second busy timeout, foreign keys, prediction persistence, and publication outbox atomicity/recovery. Verify chain order/hash compatibility, rollback, restart, concurrency, duplicate requests, and tamper behavior.
4. Keep Movement optional/reusable and Behavior ML, BioSignature, Health, and Reproduction at their stated research/experimental classifications. Preserve null confidence for uncalibrated scores and the published held-out metrics.
5. Exercise an integrated software path from animal/tag observations through movement/network/localization, optional behavior, persistence/Event V1, commitment/publication state, API, and demo. Missing stages must remain unavailable; no synthetic truth may enter estimator inputs.
6. Run the relevant Python, contract, firmware host, embedded CTest, Robot, simulation, persistence, publication, intelligence, CLI/API, packaging, and clean-checkout checks available in this environment. Record unavailable toolchains/services without upgrading claims.
7. Run bounded fault injection for nominal/no movement, NO_PATH, packet loss/collision, gateway outage, insufficient inputs, rejected convergence/quality, invalid/outlier estimates, store concurrency, publication retries/unavailability, restart/recovery, local-chain tampering, malformed input, and missing optional intelligence.
8. Run a reproducible bounded simulation robustness campaign with seeds, attempts, convergence and quality acceptance, failures, conditional metrics, runtime, and provenance. Do not claim physical accuracy.
9. Inspect the demo for honest status labels covering identity, movement, simulation/network, position, behavior, history/events, commitment/publication, and chain verification.
10. Conduct an independent adversarial review of capability loss, truth/provenance, identities/times, SQLite atomicity, publication duplication/recovery, evidence freshness, and user-facing labels; fix and reverify recoverable findings.
11. Deliver an integrated Completion Gate with explicit status, SHAs, evidence by suite, unresolved limitations, and the required scientific classifications. No push, PR, promotion, or `main` update.

## Required classification invariants

`SIMULATED != VALIDATED`; `TESTED_SOFTWARE != FIELD_VALIDATED`; `FORWARDED != EFFECTIVE`; `CONVERGENCE != ACCURACY`; `CONVERGED != QUALITY_ACCEPTED`; `GROUND TRUTH != ESTIMATOR INPUT`; `PHY_RECEIVED != APPLICATION_DELIVERED`; `MOCKED != REAL_ON_CHAIN`. FREQUENCIA must remain `EXTERNAL`; Behavior ML must remain `RESEARCH`; real-chain and field validation are unverified/not performed absent direct evidence.

