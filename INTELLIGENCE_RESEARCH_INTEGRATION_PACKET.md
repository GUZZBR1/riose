# RIOSE Intelligence & Research Integration Packet

**Status: PASS_WITH_LIMITATIONS**
**Scope:** Intelligence & Research mini-MVP only. This does not claim integration of all RIOSE repositories or domains.
**Audit date:** 2026-10-05 (America/Sao_Paulo)

## 1. Repository identity and frozen bases

| Item | Observed value |
|---|---|
| Upstream | `santleme/riose`, `origin` = `https://github.com/santleme/riose.git` |
| Upstream frozen base | `5b17771f0f86b0bb0cdb526485e8e2f50e78fdea` |
| GUZZ fork | `GUZZBR1/riose`, `fork` = `https://github.com/GUZZBR1/riose.git` |
| GUZZ frozen reference | `72ad69551b54eb069bb1c5f863dfff4066786965` |
| Work branch | `integration/intelligence-research-mvp` |
| Worktree | `/home/gusta/projetos/RIOSE/riose-intelligence-research-mvp` |
| FREQUENCIA | Separate repository `/home/gusta/projetos/frequencia`; observed HEAD `ba2bdabf003722aae8292580e048f7092d0356d6`; not invoked by this integration or its tests |

The task began in `/home/gusta/projetos/RIOSE/riose` on `codex/issue-10-antenna-convergence`, HEAD `9bc8e972c4e7418669ce94250c58ce91e49cb744`, ahead 3/behind 8 relative to its locally fetched `origin/main`, with pre-existing untracked preservation/audit files. That checkout was not edited. The isolated worktree was created at the frozen upstream SHA and was clean at creation. A safe fetch was attempted for both `origin/main` and `fork/main`; DNS resolution for `github.com` failed, so remote freshness is unverified. The local refs still resolve to the frozen SHAs above.

Phase A inputs found: `UPSTREAM_ARCHITECTURE_PACKET.md`, `GUZZ_CAPABILITY_REGISTRY.md`, `GUZZ_CAPABILITY_REGISTRY.json`, `GUZZ_PRESERVATION_MANIFEST.md`, and `INTEGRATION_COLLISION_MATRIX.md`. The registry's 35-capability tally is treated as an audit snapshot, not current truth. The preservation manifest is multi-megabyte and was not copied or rewritten.

## 2. Base architecture and integration boundary

The pinned upstream is Python-first and already has an offline XYZ signal engine at `src/riose/products/ear_tag/signal/engine.py`, local SQLite persistence, livestock tracking contracts, and a distinct truth type. This mini-MVP reuses those surfaces. It adds only (a) an optional, provenance-preserving movement dataset adapter, (b) shared evidence-class mapping, (c) a strict simulation request/result contract and opt-in result adapter, and (d) a typed behavior prediction/persistence seam. The BehaviorPredictionStore protocol describes the dependency Intelligence needs from Core; Intelligence does not own a second database or migration system.

Intended direction: Core/Embedded provide stable identities and movement input; Intelligence consumes timestamped XYZ traces and emits versioned feature/model outputs; Core persistence may store those outputs through the protocol. Product runtime does not depend on research runners, training datasets, localization campaigns, or FREQUENCIA.

## 3. Capability lineage and canonical selections

The lineages below are reconstructed from the local preserved refs/worktrees and phase A records. They are not a claim that every historical campaign was rerun.

| Capability | Canonical implementation / lineage | Decision and reason |
|---|---|---|
| Movement feature extraction | Upstream signal engine at frozen base; GUZZ issue 22 `866d985` adds explicit trace/window validation and metadata | Keep deterministic feature transformation product-capable; no biological label claim. Contract is `SignalSample`/`SignalTrace`, not another sensor driver. |
| Movement/RF context | GUZZ issue 28 implementation `2e2ef41`, with current red-team notes at `044b90b` | Keep experimental; exact identity, alignment, conflict rejection and abstention do not turn RF into behavior or zone truth. |
| Dataset provenance | GUZZ issue 21 `816049f`; dataset adapter later hardened by issue 26 `.gitattributes` commit `ac68443` | Reuse the strict adapter/catalog and synthetic fixture; the publisher's full ActBeCalf file was not downloaded here. |
| Behavior ML | GUZZ issue 23 `6fdc34a`; animal-disjoint 60/20/20 split, feature version `movement-window-v1`; issue 24 `55b10ac` adds persistence contract | Keep model in research. 144-window dataset and 1.0 held-out metrics are synthetic fixture results, not animal validation. |
| Behavior persistence | GUZZ issue 24 `55b10ac`, with explicit observation provenance and idempotent animal scope | Reuse the contract shape only. Core-owned SQLite/API integration is not copied into this isolated MVP because it would create a competing persistence migration surface. |
| BioSignature | GUZZ issue 25 `fe4b841` | Keep experimental; within-animal change signal, not biological identity or health. |
| Health anomaly | GUZZ issue 27 `b79ee4e` | Keep experimental/investigation-only; detector output is not risk diagnosis or veterinary diagnosis. |
| Reproduction | GUZZ issue 26 lineage; current isolated worktree `riose-issue26-live` at `ac684435` includes the boundary clarification, with core implementation introduced at `7a7e058` | Keep research only. Activity proxies and hypotheses do not identify pregnancy, estrus, or fertility outcomes. |
| Localization V2 | GUZZ `research/localization-v2-final` `641c4fa`; dynamic faults `632d423` reuse the exact V2 solver blob `12edcdd9f8e656683dd571993b1bb86a9334ecc1` | Keep solver/campaign research. V1 remains comparison control. Hardening is a sibling snapshot; final is the canonical instrumented solver. |
| Simulation Lab | GUZZ separate worktree `riose-simulation-lab-guzzbr1`, `research/simulation-lab` at `bcc49af` extends older `2c9c477` | Reuse only the request/result v1 contract and opt-in adapter. Keep backend runner, FARM and campaigns as research tooling. |
| RF campaigns | `cecda8d` campaign extended by `44216b3` gap closure | Keep research; bounded simulated specular NLOS is not field calibration. |
| Network campaigns | `a3e8f1b` scale study extended by `4152f8a` contention closure | Keep research; corrected finite model scenarios do not support universal capacity claims. Invalid FIFO runs remain excluded. |
| Event/evidence infrastructure | Event Contract → Evidence Bridge (`04e0070`) → Beta evidence/package pipeline (`bfc6e86` lineage) | Shared evidence mapper is reusable. Publication/blockchain capabilities are explicitly out of scope. |
| Simulation evidence package pipeline | Beta `research/riose-beta-final` (`bfc6e86`) | Keep as research tooling: it hashes manifests/inputs and enforces path/secret gates, but packaging does not validate scientific claims. |
| Temporal identity | Beta H.1 FIFO → H.2 explicit request/packet/sequence identity; RIOSE implementation lineage `2e5d5d9`, later checked by `9ae9ee1` and `a3c5f50` | H.1 attribution is superseded and must not be restored. Preserve H.2 mapping in research integration contracts. |

No branch was selected merely because it was newest. The localization final and dynamic campaign share a solver blob; RF and network closures extend their earlier campaigns; simulation lab in the separate GUZZ checkout is distinct from the older upstream lab snapshot.

## 4. Movement pipeline and contract

The current upstream signal engine is the input boundary: `SignalTrace` carries ordered `SignalSample` records, declared sample rate, optional source reference and full scale. Each sample carries monotonic timestamp, XYZ, animal/session identity, sensor position, unit and evidence status. The engine rejects missing sample rate, inconsistent clocks, excessive gaps, mixed units, invalid values and saturation; it does not infer the rate or fabricate missing axes. Its `FeatureWindow` includes a fixed feature-name order and provenance metadata.

The movement dataset adapter accepts its expected ActBeCalf CSV schema only when its header is exact. Because the publisher's full CSV was not downloaded, this expected header is validated against the synthetic fixture but has not been confirmed against published file bytes. The adapter preserves original labels, raw units/timezone as unknown where the source is silent, per-row animal/segment identity and file hash. `segId` is not treated as a session. The 3-row checked-in fixture is explicitly synthetic. No LIS2DW12 driver or sensor implementation was added.

## 5. Dataset inventory

| Dataset | Source/license/checksum | Animals, labels, split | Evidence and use |
|---|---|---|---|
| ActBeCalf | [Zenodo record](https://zenodo.org/records/13259482), DOI `10.5281/zenodo.13259482`; local catalog says CC BY 4.0, but the current record's rendered Rights section does not expose a license. Treat reuse/redistribution as needing API/license recheck. Publisher file `AcTBeCalf.csv`, 177,608,717 bytes, MD5 `59bd00564af64d92489485fa5a8a3960`; full source file absent, so SHA-256 not computed. | 30 calves, 27.4 h, 25 Hz, neck sensor, 23 source classes. Unit/timezone undocumented; adapter keeps canonical label `UNKNOWN`. Record lists a subject split helper, but no split artifact was downloaded/verified; use calf-disjoint evaluation. | `PUBLIC_MEASURED_DATA`, external neck sensor; not RIOSE measured data and not ear-tag validation. Adapter tests use synthetic fixture only. |
| Precision Beef | [Zenodo record](https://zenodo.org/records/4064802) and [published README](https://zenodo.org/records/4064802/files/Readme.md?download=1), DOI `10.5281/zenodo.4064802`; local catalog says CC BY 4.0, but the rendered record does not expose a license, so recheck rights before reuse/redistribution. Per-file MD5s are cataloged; bytes not downloaded. | 18 cattle / three trials; 10 Hz, collar in mg. The README's test fold is animal-disjoint (IDs 04, 10, 11). Labels come from a separate halter device; drinking is merged into Eating. | `PUBLIC_MEASURED_DATA`; collar and machine-predicted labels are not ear-tag measurements or manually observed ground truth. Keep research; preserve the published animal split if evaluated. |
| Japanese Black Beef v2 | [Zenodo record](https://zenodo.org/records/5849025), DOI `10.5281/zenodo.5849025`; description explicitly says CC BY-NC-ND 4.0, while the local phase-A catalog also recorded conflicting CC BY 4.0 API metadata. File MD5 `1ba658c6091461730c57e2b378218a39`; not downloaded. | 6 cattle, 197 labeled minutes, neck sensor, 25 Hz. Six per-cow files; no train/test split prescribed by the record. | `PUBLIC_MEASURED_DATA`; acquisition and redistribution remain disabled until conflicting license metadata is resolved. `MOV` means moving, not necessarily walking. |
| ActBeCalf adapter fixture | `datasets/movement_biosignature/fixtures/actbecalf_synthetic_fixture.csv`; SHA-256 `11698c1c9936643a00950f94ff1d4c0a9023a404dd058eb8b939210d40ea5e7`. Golden JSONL and manifest are LF-pinned through `.gitattributes`. | 3 synthetic rows, one animal, NECK, 25 Hz; label retained but canonical mapping unknown. | `SYNTHETIC_DATA`, software/contract test only. Never use for model performance or measured-data claims. |
| Behavior ML fixture | GUZZ artifact provenance SHA-256 `9528443806da10f666c44ee35798a46174b19a9092268fbbed778970f17723ba`. | 144 generated windows; 12 synthetic animals; deterministic animal-disjoint 96/24/24 split with 8/2/2 animals. | `SYNTHETIC_DATA`; model/software exercise only. |

No split-by-window is accepted where windows from the same animal could leak across folds. For the behavior fixture, all sessions/windows for each synthetic animal remain in one fold. Precision Beef's published animal-level test fold is 04/10/11; keep it intact. The Japanese v2 record groups files by cow but does not define an evaluation split. External datasets were not downloaded in this integration, so their local SHA-256 checks are `NOT_TESTED`, not passed.

## 6. Behavior ML and persistence boundary

The behavior pipeline's recorded candidate model is logistic regression with standard scaling, features `accel_mean_g`, `accel_std_g`, `accel_rms_g`, feature version `movement-window-v1`, and animal-disjoint deterministic split. Artifact scores are maximum model scores, explicitly not calibrated probabilities. The current 144-window synthetic artifact reports accuracy, balanced accuracy and macro-F1 of 1.0 on 24 synthetic holdout windows; the majority baseline is accuracy 0.333 and macro-F1 0.167. This does not measure generalization to cattle or a tag sensor. Earlier briefing values (~0.53 / ~0.20 / ~0.19) were not found in the current artifact/registry; they are not substituted for current evidence.

The new `BehaviorPrediction` contract carries animal/tag identity, window bounds and creation time, class, optional score, model version and SHA-256, feature version, evidence status, source reference, input SHA-256 and prediction ID. `confidence` means score, not calibrated probability. `BehaviorPredictionStore` is a protocol seam for Core-owned persistence; it is idempotent by prediction ID and requires conflicting retries to fail instead of overwrite. Ground truth and manual labels are separate records and are not model input. No SQLite tables, API routes, or parallel database were added here.

## 7. BioSignature, Health and Reproduction

- **BioSignature:** experimental individual baseline deviation/similarity signal. It is not verified identity, a health state, or a diagnosis. Synthetic scenario tests only establish arithmetic and schema behavior.
- **Health anomaly:** experimental deviation detector intended to trigger investigation. It does not estimate veterinary risk or diagnose disease. Use “anomaly signal” and require qualified follow-up.
- **Reproduction:** research-only activity proxy/hypothesis stream. Current evidence does not validate pregnancy, estrus, fertility, or reproductive outcomes. Preserve retrospective exploration without a clinical/product claim.

## 8. Localization V2 and false confidence

V2 TDoA uses reference-clock calibration with simulated beacon/timestamp inputs; it has no validated physical clock synchronization/detector or field propagation model. The dynamic fault campaign reports 28 cases × 10 seeds × 24 epochs = 6,720 synthetic attempts. Known false-confidence negatives are retained: wrong calibration yielded 50/240 estimates that passed a quality gate while all had error >10 m; poor geometry plus jitter yielded 3/240 such estimates, also all >10 m. These are `KNOWN_FAILURE_MODE` evidence, not rows to omit.

Interpretation is explicit: `CONVERGED != QUALITY_ACCEPTED != ACCURATE`. Convergence and quality gates are separate evidence; neither establishes ground-truth accuracy. Ground truth is evaluator-only and must not reach estimator inputs. Numerical convergence in unrelated RF/antenna tools is not physical accuracy either.

## 9. Simulation Lab, contract and temporal identity

Reusable contract and adapter were copied from canonical GUZZ Simulation Lab `bcc49af`; the backend runner and campaign machinery remain research-only. Request/result v1 carries campaign/scenario/seed/backend, time/frame/unit contracts, explicit entity mappings, outcomes and provenance hashes where available. The separate `RequestTimeline` extension adds request/run/packet/sequence IDs plus created/superseded/scheduled/transmitted/received timestamps; these identities are not replaced by FIFO ordering. Statuses distinguish path availability, transmission, reception, solver and quality outcomes; null/unavailable values remain null. `NO_PATH`, `NOT_TRANSMITTED`, and `NOT_RECEIVED` are not interchangeable. Power is not mapped to receiver RSSI by default, and propagation delay is not hardware ToF.

Temporal joins use explicit source request/packet/sequence identity and retain requested, scheduled and actual timestamps. H.1 FIFO attribution (86/129 aggregate mapping in the audit record) is historical and superseded for per-request truth. Beta H.2's retained four-request campaign records 4 TX and 0 untransmitted; that execution is historically reported, not rerun now. FREQUENCIA remains an external simulator dependency. RIOSE imports no Sionna/ns-3 runtime dependency and no FREQUENCIA history.

## 10. RF realism and network capacity campaigns

RF evidence includes an 8-point distance sweep (5–1000 m), 9 TX/RX height combinations (TX 1.0/1.5/2.5 m; RX 4/8/12 m), six synthetic farm layouts, a 30-position Monte Carlo sweep, flat/synthetic-relief controls, direct-only/ground-reflection controls, and a bounded wall/reflector search. The follow-up reproduced 4 geometric received NLOS links and 8 `NO_PATH` rows, with no simulation failures; null power for `NO_PATH` remains null. This is a bounded Sionna simulated geometry, not field RF realism. The model uses isotropic antennas and uncalibrated environment/material assumptions; orientation is not meaningfully testable with its 1×1 isotropic arrays (`MODEL_LIMITATION`). Vegetation has no ray-traced foliage/material model (`NOT_TESTED`). Analytic propagation ignores obstacle geometry; model disagreement is not error against ground truth.

Network lineage is `2c9c477` → `a3e8f1b` → `4152f8a`. Nine initial one-second executions are invalid: 315 FIFO source/event identity mismatches. Corrected schedule audit records 2,100 TX starts without >1 ns timing mismatch. **PHY PDR denominator is packets with TX start**; numerator is unique packet IDs received by at least one gateway. Schedule completion (`TX starts / requested packets`) is reported separately so a good conditional PDR cannot hide untransmitted requests. Gateway outcomes are per-gateway and are not packet-level losses. Corrected finite scenarios include 20 colocated tags/60 s at 600/600 receptions and synchronized 10-tag bursts at 0/300; a previous 17→18-tag apparent drop was caused by `NO_PATH`, not contention. Other modeled limits include effective 100% sub-band duty cycle and no application delivery; no farm-scale capacity generalization is justified.

## 11. Promotion matrix

The complete capability list, decisions, dependencies, scientific classifications, test status and target locations are in [`INTELLIGENCE_RESEARCH_PROMOTION_MATRIX.json`](INTELLIGENCE_RESEARCH_PROMOTION_MATRIX.json). High-level decisions: stable contracts and provenance adapters are `PRODUCT_OPTIONAL`; ML, BioSignature, Health, Reproduction, Localization V2, Simulation Lab runners, and RF/Network campaigns remain research or experimental; superseded FIFO results are historical only.

## 12. Tests and reproducibility

Verification run results (current source refs/worktrees; separate suites, not one monolithic run):

| Scope | Result | Worktree/commit scope |
|---|---:|---|
| Integrated adapter, evidence bridge, simulation contract/adapter, temporal identity contract, behavior contract, and movement signal engine | 134 passed | Isolated integration branch at frozen upstream base plus this branch's changes |
| Behavior ML pipeline/artifact | 23 passed | `riose-issue23`, `6fdc34a`; `PYTHONPATH=src` for subprocess imports |
| BioSignature | 14 passed | `riose-issue25`, `fe4b841` |
| Health anomaly | 21 passed | `riose-issue27`, `b79ee4e` |
| Reproduction research | 12 passed | `riose-issue26-live`, `ac684435` |
| Localization V2 and robustness | 21 passed | `riose-localization-v2-final`, `641c4fa` |
| Dynamic localization fault controls | 12 passed | `riose-dynamic-localization-faults`, `632d423` |
| RF realism closure | 4 passed | `riose-rf-realism-gap-closure`, `44216b3` |
| Network contention closure | 12 passed | `riose-network-contention-capacity-closure`, `4152f8a` |
| Beta H.2 RF identity/timestamp validation | 15 passed | `riose-beta-final`, H.2 simulation lab source |
| GUZZ Simulation Lab network identity validation | 29 passed | `riose-simulation-lab-guzzbr1`, `bcc49af` |
| Movement/RF context abstention and provenance | 18 passed | GUZZ issue 28 worktree |
| Simulation evidence package pipeline | 30 passed | Beta `riose-beta-final` |

Together, 345 test cases passed across these focused suites. These runs prove code/contracts at their named local refs; they do not establish biological, hardware, field-RF, or clinical validity. The ActBeCalf published binary was not downloaded, and the campaign runners were not invoked end-to-end. Branch-local campaign result files remain historically reported unless a listed suite explicitly reran a bounded code check; no heavy campaign was regenerated.

The dataset fixture's SHA-256 and golden outputs are verified in this checkout. The behavior test suite retrained the current synthetic fixture pipeline and checked its deterministic artifact behavior; the pinned artifact records fixture hash, seed 23, animal split, model/feature versions, package versions, and output parameters. Full external FREQUENCIA campaigns are not claimed as reproduced. Tests in the isolated branch do not modify historical result artifacts. The frozen `pyproject.toml` defines no lint/type-check command, and neither `ruff` nor `mypy` is installed in the available environment; `compileall` passed for every newly added Python package.

## 13. Scientific red-team

**Result: PASS with limitations.** Reviewed the requested failure classes against the packet, catalog, model artifact, campaign closure records, source paths, and new integration diff:

1. Animal-disjoint behavior split retained; no window-level random split promoted.
2. Estimator inputs do not accept ground truth; evaluator truth remains separate.
3. Synthetic fixtures are explicitly labeled; synthetic metrics stay synthetic.
4. Public measured datasets remain external measurements, not RIOSE field data.
5. Behavior ML remains research despite the 1.0 synthetic holdout score.
6. Health anomaly is not diagnosis.
7. Reproduction signals remain hypotheses/activity proxies.
8. Localization convergence/quality are not called accuracy.
9. False-confidence negative controls are documented and preserved.
10. Invalid network runs are excluded and called invalid.
11. Network denominators/outcomes are reported per scenario; mismatched FIFO attempts are not counted as valid receptions.
12. Missing RF/position/ToF values remain unavailable rather than fabricated.
13. FREQUENCIA stays separate and external.
14. Historical evidence files/refs were not edited by this work.
15. Research runners/campaigns are not imported by product runtime.
16. Existing upstream signal and evidence contracts are reused; no second sensor driver/database was added.
17. Canonical versions follow explicit lineage/same-blob evidence rather than branch recency.

## 14. Diff, preservation and exact integration

The worktree began at upstream SHA `5b17771f0f86b0bb0cdb526485e8e2f50e78fdea`; all selected GUZZ code is a selective copy with lineage cited above. The scoped integration was committed locally as `222deb228e9b2cfde7ac3fbe1e64f489fce47d32` (31 files, 3,942 insertions). The commit's complete path list and diff are available through `git show --stat` and `git show 222deb2`. `upstream/main` remains `5b17771f0f86b0bb0cdb526485e8e2f50e78fdea`, `GUZZ/main` remains `72ad69551b54eb069bb1c5f863dfff4066786965`, and local `main` remains `e57b235a452c6e8d258d1708d5fd53ce56cecfb`. Preservation refs and existing research branches/worktrees were not checked out for mutation, reset, deleted, or rewritten. Evidence results and FREQUENCIA history were not rewritten. The pre-existing dirty FREQUENCIA worktree was inspected but left untouched. No push, PR or merge was performed.

## 15. Known limitations and Gate β recommendation

- Upstream/fork remote freshness could not be checked because DNS to GitHub failed; pinned local objects were available and used.
- ActBeCalf source data are cataloged but not downloaded; only its 3-row synthetic adapter fixture was tested.
- No real animal-held-out behavior evaluation, field hardware validation, biological validation, or veterinary validation exists in this packet.
- Research campaign executions were not rerun in this worktree. Their results remain historical evidence with source commits and status labels.
- The BehaviorPredictionStore protocol is not implemented by this upstream base's SQLite store; Core must adopt it with an additive migration and API decision before predictions are persisted in product runtime.
- FREQUENCIA's current checkout was dirty before inspection; this task did not use it and did not make its state part of RIOSE.

Gate β recommendation: accept the scoped Intelligence/Research boundary and contract package as `PASS_WITH_LIMITATIONS`; do not promote research models/campaigns as validated product claims. Gate β should separately require a Core-owned additive persistence implementation, external dataset checksum verification, reproducible animal-held-out evaluation on measured public data, and explicit review of any proposed biological/clinical use.
