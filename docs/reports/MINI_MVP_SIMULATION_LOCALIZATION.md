# RIOSE Mini-MVP 2 — Simulation & Localization

## Verdict

**PASS_WITH_LIMITATIONS** — the isolated Mini-MVP executes a real synthetic Sionna RT → ns-3/LoRaWAN → received-gateway-timestamps → FREQUENCIA TDoA → request-bounds quality pipeline and writes evidence packages. TDoA/RF/network work remains research evidence. Analytic/Sionna pairing, broad dynamic/fault campaigns, and larger seed/scale sweeps remain open; none of these results is physical validation.

## Workspace and provenance

- Canonical checkpoint/base: `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`; approved tree: `bb9713f64467d498c4547bbe9bc1e32f5617dadf`.
- Work branch: `mini-mvp/simulation-localization`; implementation checkpoint: `5a6e09bcfe1de757e023f59459c9a6114bca292c`. The final response records the final report/evidence commit HEAD.
- Worktree: `/home/gusta/projetos/RIOSE/riose-mini-mvp-simulation-localization`.
- RIOSE was run from the canonical checkpoint, not a historical research branch. `fork` resolves to `https://github.com/GUZZBR1/riose.git`; its cached `fork/main` was the expected SHA. Fresh `git fetch --no-tags fork main` could not resolve `github.com`, so the current remote SHA is **not freshly verified**. `origin` is `https://github.com/santleme/riose.git` and is not the requested GUZZ remote.
- Recovery ref: `recovery/mini-mvp-simulation-localization-pre-reconcile` at the implementation checkpoint. It preserves the complete pre-reconciliation local work.
- FREQUENCIA: SHA `ba2bdabf003722aae8292580e048f7092d0356d6`, dirty before/after with the same user changes (`docs/phase_final_v1_visual_report.md` and untracked `results/riose_feature5/`). `--allow-dirty` was explicit. Generated FREQUENCIA outputs used a unique run ID, were moved into the RIOSE evidence package, and left the external checkout's Git state unchanged.
- Campaign source RIOSE SHA: `5a6e09bcfe1de757e023f59459c9a6114bca292c`. Reports and campaign evidence are local to this isolated branch; no push, PR, or main change was made.

### Workspace Reconciliation

| Field | Recorded value |
|---|---|
| REMOTE_NAME | `fork` |
| REMOTE_URL | `https://github.com/GUZZBR1/riose.git` |
| REMOTE_MAIN_SHA | Fresh value unavailable (DNS failure); cached `fork/main` = `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed` |
| EXPECTED_CHECKPOINT | `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed` |
| PRE_RECONCILIATION_HEAD | `5a6e09bcfe1de757e023f59459c9a6114bca292c` (the pre-reconciliation checkpoint commit; initial worktree HEAD was `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`) |
| ORIGINAL_BASE | `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed` |
| MERGE_BASE | `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed` |
| DIRTY_STATE_BEFORE | Branch was at canonical SHA with 15 untracked mission files; no user edits were present in this isolated worktree. |
| RECOVERY_REF | `recovery/mini-mvp-simulation-localization-pre-reconcile` |
| RECONCILIATION_CLASS | `A — CURRENT_BASE_CONFIRMED` (ancestry to the specified checkpoint is proven; latest remote freshness could not be verified) |
| RECONCILIATION_ACTION | Captured state, committed a reversible local recovery checkpoint, verified exact merge base, and attempted safe fetch. No rebase/reset was needed. |
| POST_RECONCILIATION_BASE | `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed` |
| POST_RECONCILIATION_HEAD | `5a6e09bcfe1de757e023f59459c9a6114bca292c` |
| CANONICAL_CAPABILITIES_REUSED | Simulation Contract V1, simulation adapter, temporal identity, existing evidence bridge, and the current product localization boundary. |
| LOCAL_CHANGES_SUPERSEDED | None. The historical runner was selectively adapted because no runner existed in canonical main. |
| CONFLICTS_RESOLVED | Historical branch code was not cherry-picked. The adapter was checked against canonical V1 schemas and tests. |
| TESTS_AFTER_RECONCILIATION | Full Python suite: 675 passed, 7 skipped. Clean checkout: 113 focused tests passed plus a real campaign. |

`WORKSPACE RECONCILIATION: PASS_WITH_ADAPTATION`. `SAFE_TO_CONTINUE_ORIGINAL_MISSION: YES`. Main modified: no. Push: no. PR: no.

## Capability map and boundary

| Capability | Current location / status | Reuse decision |
|---|---|---|
| Simulation request/result, identity and time | Canonical `src/riose/simulation_contract/`; tested | REUSE |
| Conversion to RIOSE domain observations/estimates | Canonical `src/riose/simulation_adapter/`; tested | REUSE |
| External engine process/provenance boundary | Added `src/riose/simulation_lab/`; 58 focused tests and real campaign | ADAPT; optional developer capability |
| Sionna RF propagation | FREQUENCIA `rf/sionna_backend.py`, Sionna RT 2.2.0; runtime executed on CPU | EXTERNAL / RESEARCH |
| Analytic smoke | FREQUENCIA analytic free space plus flat-ground reflection; runtime executed | EXTERNAL; request fields declared unsupported/not effective |
| Network | FREQUENCIA ns-3 3.48 + LoRaWAN v0.3.7 adapter; runtime executed | EXTERNAL / RESEARCH |
| TDoA | FREQUENCIA estimator fed by modeled successful gateway receptions; runtime executed | RESEARCH; does not replace product RSSI localization |
| Evidence bridge and scientific registry | Canonical main evidence/provenance components plus run-local manifests/hashes | REUSE / EXTEND |

RIOSE/FREQUENCIA communication uses validated request files and a versioned `riose.simulation.request/v1` → `riose.simulation.result/v1` file boundary. Source identity mappings remain explicit for animal, device, transmitter/tag, gateway, and receiver/anchor. The runner validates the pinned external Git remote/SHA, records dirty state, request/result hashes, command, environment, requested/effective parameter binding, runtime, and `SIMULATED` classification. The request does not turn the lab into a RIOSE runtime dependency.

The analytic backend ran, but its fixed smoke does not consume the request-specific seed, geometry, or radio parameters; the manifest records effective values as null and `REQUEST_SPECIFIC_PARAMETERS_UNSUPPORTED`. The runner fails closed for unavailable selected backends and does not silently replace Sionna with analytic RF.

## RF, network and localization results

The real Sionna environment was Sionna RT 2.2.0, Mitsuba 3.9.1, Dr.Jit 1.5.0, NumPy 2.5.3, CPU (`CUDA_VISIBLE_DEVICES=-1`). The RF model used the FREQUENCIA FARM reference scene at 915 MHz, 125 kHz, 14 dBm, SF7, configured 1×1 isotropic vertical arrays and uncalibrated synthetic material proxies. No physical antenna gain/orientation, vegetation loss, field-calibrated soil, or measured antenna behavior is represented. The RF mesh includes synthetic shed/terrain; listed trees, canopy, fences, pasture, and other land-use inventory are not all ray-traced obstacles.

| Run | Runtime | RF / network / localization evidence |
|---|---:|---|
| Base end-to-end, seed 20261003 | 7.286 s | 1 tag × 3 snapshots × 4 gateways = 12 RF links: 9 LOS, 0 NLOS, 3 NO_PATH. ns-3: 2 transmitted packets, 6 gateway RX events, 2 unique packets received by ≥1 gateway, PDR 1.0. TDoA: 2 attempts, 1 converged, 0 quality accepted; conditional error 4349.932 m for the converged estimate. |
| LOS excluded, reflection enabled | 4.835 s | 12 RF links: 0 LOS, 6 NLOS, 6 NO_PATH. Network was disabled; PDR is null/not applicable. |
| Synchronized collision control | 5.049 s | 4 packets transmitted; 12 gateway-level INTERFERENCE outcomes; 0 packets delivered; PDR 0.0. Also 4 gateway-level NO_PATH and 8 NOT_TRANSMITTED outcomes, kept distinct. |
| One gateway unavailable | 6.924 s | Three configured gateways remained; 2/2 packets received by at least one gateway. TDoA had 0 eligible observations and 2 failed attempts; no missing timestamps were synthesized. |
| 20-tag one-epoch scale | 14.374 s | 80 RF links; 20 TX packets; 17 unique packets received by ≥1 gateway (PDR 0.85), 52 gateway RX events, 28 NO_PATH gateway events. TDoA: 13 eligible/converged/quality-accepted, 7 unavailable/failed; conditional RMSE 193.738 m. Bounds acceptance is not accuracy. |
| High detector threshold | 5.468 s | 2 packets, 6 gateway RX events, PDR 1.0; 0 eligible TDoA estimates and 2 failed attempts, without invented timestamps. |
| Analytic fixed smoke | 0.689 s | Backend `frequencia.analytic`; no request-derived observations; request-specific parameters not effective. |

The FREQUENCIA network adapter reports PHY receptions, not application or network-server delivery. The reported PDR is unique transmitted packets received at one or more gateways divided by transmitted packets. Application delivery is unavailable and is not claimed. A Sionna NO_PATH is a propagation outcome, not packet loss; NOT_TRANSMITTED is distinct from NOT_RECEIVED. A simulated 1 ps timestamp resolution is not hardware accuracy.

## Quality, false confidence, faults and temporal identity

The TDoA solver receives transmission identities/times, successful gateway receptions, and gateway geometry. Ground truth is absent from estimator and quality-gate inputs; the separate scoring step uses it only after estimation. Raw converged positions are retained. The gate compares them with request-declared operational bounds and reports `CONVERGED` separately from `ACCEPTED`/`REJECTED`/`NOT_EVALUATED`; bounds do not come from ground truth.

False-confidence checks include unit tests for a converged zero-residual point outside bounds and a recorded Monte Carlo case where both attempts converged but conditional RMSE was 1319.494 m and both estimates were rejected. Across four recorded seeds, run-level conditional RMSE ranged from 74.918 m to 5776.887 m; 6/8 attempts converged and 2/8 were accepted. This small screening sample shows sensitivity, not expected field accuracy.

Executed fault cases cover synchronized collisions, one gateway outage, a detector threshold that prevents timestamp eligibility, and missing/NO_PATH observations. Tests cover invalid/extreme clock settings, event/link identity mismatch, two-gateway TDoA failure, out-of-bounds estimates, and malformed evidence. A full clock drift/offset/jitter sweep, missing/corrupt/stale/duplicate timestamp recovery, multi-gateway outage/recovery, and moving stop/turn/bad-zone sequence were not executed. Calibration models for identity/ideal/fitted/stale/wrong/no calibration are not implemented by this Mini-MVP; therefore fitted calibration is not claimed.

Temporal records are tied to the request's tag/transmitter mappings and to actual packet event, gateway and TX/RX times. Timestamp rows are accepted only for matching PHY RX events, and only those rows are offered to TDoA. The clean and repeated runs had identical network-result, timestamp, localization and scoring file hashes. Sionna RF output also matched after excluding only the generated ExperimentSpec hash and measured per-snapshot execution times; those fields are run-specific. GPU determinism is not claimed.

## Evidence, tests and red-team review

Each campaign workspace under `results/mini-mvp-simulation-localization/runs/` contains the request, V1 result, run manifest, adapter output, copied FREQUENCIA raw/summary/metrics/environment/geometry/plot artifacts, and network/timestamp/localization/scoring output when the network ran. Manifests identify RIOSE/FREQUENCIA SHAs, seed, CPU device, backend, scenario, parameter bindings, runtimes and hashes. `run-index.json`, `reproducibility.json`, and `clean-checkout-reproduction.json` summarize evidence.

- `compileall`: passed.
- Full RIOSE Python regression: **675 passed, 7 skipped**, one existing Starlette/httpx deprecation warning (baseline: 617 passed, 7 skipped; increase: 58 lab tests).
- Contract and adapter tests: **55 passed**.
- Simulation lab tests: **58 passed**.
- Clean detached checkout at implementation checkpoint: **113 passed** across contract/adapter/lab tests; an Sionna + ns-3 campaign also completed with the same semantic result.
- `git diff --check`: passed.

Red-team checks: FREQUENCIA remains external; no silent backend fallback; analytic is not labeled Sionna; requested/effective differences are recorded; ground truth remains post-estimation; convergence is not accuracy; out-of-bounds estimates are rejected without clamping; PDR is explicitly PHY-level; NO_PATH and NOT_TRANSMITTED remain separate; timestamps are derived from RX records; simulated calibration/materials are not physical claims; all Monte Carlo seeds are retained; run provenance and output hashes are present; historical evidence was not rewritten; main was not modified; no physical validation is claimed. Fresh GitHub remote state remains unverified because DNS lookup failed.

## Promotion and remaining limits

- Canonical contracts, adapter, and temporal identity: reusable, optional product boundary.
- Simulation runner: optional developer tooling; requires external FREQUENCIA and explicit local setup.
- FREQUENCIA: EXTERNAL.
- Sionna RF and ns-3 campaigns, collision results and TDoA: RESEARCH / SIMULATION.
- Antenna/terrain/material choices: EXPERIMENTAL, uncalibrated.
- No field/hardware validation.

In-scope gaps: no valid analytic/Sionna paired comparison; no 50/100-tag sweep; only a three-seed Monte Carlo extension plus baseline; only a short linear route rather than a broad dynamic movement matrix; no clock corruption/recovery or multi-gateway recovery campaign; no vegetation/antenna orientation model; fresh GUZZ remote main SHA unavailable. These do not alter the `SIMULATED` classification.

## Machine-readable artifacts

- Test matrix: `docs/reports/MINI_MVP_SIMULATION_LOCALIZATION_TEST_MATRIX.json`
- Claim registry: `docs/reports/MINI_MVP_SIMULATION_LOCALIZATION_CLAIMS.json`
- Campaign index: `results/mini-mvp-simulation-localization/run-index.json`
- Reproducibility check: `results/mini-mvp-simulation-localization/reproducibility.json`
- Clean-checkout record: `results/mini-mvp-simulation-localization/clean-checkout-reproduction.json`
