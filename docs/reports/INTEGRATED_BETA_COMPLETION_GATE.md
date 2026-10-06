# RIOSE Integrated Beta Completion Gate

**Review status: READY FOR FACTORY FINAL REVIEW WITH OPEN UI / RECOVERY LIMITS**  
**Integration status: SIMULATED PASS; FIELD VALIDATION NOT PERFORMED**  
**Branch:** `integration/integrated-beta-final`  
**Base:** `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`  
**Integrated code revision:** `4c9410d16a48eb46f205d92ddcd09405dea0750c`  
**Simulation source revision:** `ac9f97ba173b204bfa01ecf0de16116023e33d58`

An independent read-only red-team review found and prompted fixes for recovery from `CONFIRMED` after interruption, evidence-status promotion in publication summaries, and the demo API anchor fixture. Those corrections have focused regression tests. The red-team also identified the unresolved prepared-transaction resubmission boundary listed below.

## Completion gate

| Gate | Status | Evidence / boundary |
|---|---|---|
| Mini-MVP 1–5 consolidation | PASS | Five source heads merged on the isolated branch; their merge bases are the requested base. Source branches and other worktrees were preserved. |
| Python regression suite | PASS | 753 passed, 7 skipped. One existing Starlette/httpx deprecation warning. Repeated from detached clean checkout `58fa5fd20f17b8c4c0f6e40409a34a41809d716b`. |
| Native firmware / hardware host suite | PASS | Fresh Debug CMake build and CTest: 39/39 passed from the detached clean checkout. This is host-side evidence, not physical firmware validation. |
| Package build | PASS | Offline source distribution and wheel built as `cattle_rf-0.1.0` from the detached clean checkout. |
| Lock / whitespace checks | PASS | `uv lock --check --offline`; `git diff --check`. The detached checkout had no tracked or untracked changes before package outputs (ignored `dist/`). |
| Sionna RT + ns-3 smoke campaign | SIMULATED PASS | Run `c93252ed65524582abec8f384b8d9ed3`; Sionna RT 2.2.0 and ns-3 3.48 / LoRaWAN v0.3.7. 12 links, 2 transmissions, 6 gateway PHY receptions, 2 TDoA attempts, 1 converged estimate, 0 quality-accepted estimates. Conditional RMSE 4349.93 m applies only to the converged estimate. Application/server delivery is not modeled. |
| Monte Carlo | SIMULATED PASS, SMALL SAMPLE | Three seeds: 20261011, 20261012, 20261013. Each produced 12 RF observations and 2 location rows. Across these 6 rows: 3 quality accepted, 3 rejected or not evaluated; one solver failure. This is a reproducibility smoke sample, not statistical validation. |
| Fault injection | PASS FOR EXECUTED CASES | Live collision campaign: 4 TX, 12 collision/interference events, 0 gateway receptions. Gateway outage and localization-failure runs are retained; both correctly produce no eligible localization estimate. Additional malformed-input, no-path, identity, threshold and persistence fault behavior is covered by the passing automated suite. |
| API / persistence / event / publication / demo E2E | PASS, LOCAL SIMULATION | Local TestClient smoke returned simulated health and dashboard HTML, exposed 4 anchors and saved 12 telemetry records to the canonical Store, retained no ground truth and no rejected positions, recorded a `SIMULATION_RUN_RECORDED` event, verified its hash chain, queued a local commitment/outbox item, verified local binding, and reopened the DB and anchors successfully. Report: `results/integrated-beta/e2e/report.json`. A regression checks that registered animals without accepted positions remain listed; browser rendering remains unverified. |
| Behavior inference | UNAVAILABLE IN THIS RUN | No prediction was synthesized from RF/localization. Integrated research model remains uncalibrated and is not approved for operational use. |
| Real blockchain publication | UNVERIFIED | Outbox state is `QUEUED`; local commitment binding verifies. No RPC publication or on-chain receipt was attempted. |
| Physical / field validation | NOT PERFORMED | Zephyr, Robot Framework and Renode tools were unavailable in the execution environment; no physical tag, gateway, animal, or farm test was performed. |
| FREQUENCIA authority / vendoring | PASS | Used as an external checkout pinned at `ba2bdabf003722aae8292580e048f7092d0356d6`; no FREQUENCIA source was vendored. Its pre-existing dirty files were left untouched. |
| Upstream / branch safety | PASS | No push, PR, upstream write, main-branch change, or deletion/rewriting of preserved refs. Work was performed in a separate worktree rooted at the requested base. |

## Run evidence

All campaign requests, manifests, results, engine/network outputs, and summaries are retained under `results/integrated-beta/`. The smoke campaign records received power separately from RSSI; canonical RSSI remains null when absent. Simulation timestamps and propagation delays retain simulated semantics. The localization estimator did not receive ground truth. Failed or rejected location solutions remain evidence artifacts and are not presented as accepted animal positions.

The three Monte Carlo cases had differing solver/quality outcomes; do not summarize them as identical successful localizations. The sample is intentionally too small to support operational accuracy claims.

## Remaining limits before field or operational approval

- Run physical firmware, radio, timestamp, clock-drift, and gateway tests on identified hardware; establish calibration and measurement uncertainty.
- Validate the source dataset rights, labels, time basis, and population coverage before considering behavior-model calibration or deployment.
- Exercise authenticated application delivery, real device identity provisioning, and farm-scale recovery under deployment conditions.
- Publish to a controlled test network only after key custody, destination authorization, duplicate/retry policy and receipt verification are operationally approved.
- Publication reconciliation now resumes `CONFIRMED` requests after a crash before `VERIFIED`. Resubmission of a persisted `PREPARED` signed transaction after an unobserved signature / RPC ambiguity is not implemented or validated; do not interpret that recovery gap as resolved.
- Review the new `SIMULATION_RUN_RECORDED` event type as a stable public API contract before external clients depend on it.
- Run the dashboard in a browser against this exact E2E database and verify the animal renders as unlocated, without a fabricated map marker.

## Final dispositions

- `INTEGRATED_BETA`: `PASS_SIMULATED_WITH_LIMITATIONS`
- `FACTORY_FINAL_REVIEW`: `READY_WITH_OPEN_ITEMS`
- `FIELD_VALIDATION`: `NOT_PERFORMED`
- `REAL_ON_CHAIN`: `UNVERIFIED`
- `BEHAVIOR_MODEL`: `UNAVAILABLE_FOR_OPERATIONAL_USE`
- `UPSTREAM_CHANGED`: `NO`
- `PRESERVED_REFS_REWRITTEN_OR_DELETED`: `NO`
