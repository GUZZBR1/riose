# RIOSE Beta Simulation Validation Report

## 1. Executive Summary

**Governed verdict: PARTIAL.** A bounded campaign completed 13/13 scheduled runs, but a post-hoc temporal audit found source epochs at 0/1/2 s, 86 TX from 129 requests, 43 non-transmitted final epochs, and 7 s between the first and second TX for each animal despite a declared 60 s interval. C.1 specifically excluded this 1 s source/FIFO attribution regime after finding event-association errors. H hashes establish the recorded outputs, not event/time identity. Therefore H does not pass the integrated Beta gate.

The RF/network campaign demonstrates execution inside declared software models. It does not establish that every estimate is usable: the control had 8/8 converged estimates but only 2/8 quality-accepted; the collision case had 0/12 gateway PHY receptions; and the ten-animal case had 56/60 transmitted packets received by at least one gateway, with 40/56 estimates accepted. PHY reception is not application delivery.

The current Tag closure evidence supports PASS_SIMULATED for STATIC/WALK/RUN and a golden-axis probe; antenna remains separately PARTIAL_SIMULATED. RF, corrected network, and D.1 localization gates pass within their declared simulated scopes; Movement's separate measured-data research pipeline passes with risk but its classifier is weak. These component results do not erase H's event-attribution failure or establish one Tag→RF→Movement→Blockchain run. Hardware, field, clinical, and reproductive validation are not claimed.

## 2. Scope

This report asks how coherently and robustly RIOSE behaves within the currently declared models and simulators. It integrates auditable software evidence and records gaps. It does not attempt to prove physical operation.

## 3. What This Report Does NOT Claim

- `SIMULATED` does not mean `VALIDATED`.
- Sionna convergence, a TDoA solution, or a passing software test does not mean accuracy or quality acceptance.
- Gateway PHY RX does not mean application/server delivery.
- Offline receipt/integrity checks do not mean `REAL_ON_CHAIN`.
- External measured data, if used later, would not by itself validate RIOSE hardware.
- No hardware, field, animal-health, estrus, pregnancy, or commercial-readiness claim is made.

## 4. Repository / Version

- Repository: `GUZZBR1/riose`.
- Isolated worktree branch: `research/riose-beta-final`, based on `fork/main` revision `72ad69551b54eb069bb1c5f863dfff4066786965`.
- Official RF/network campaign source: RIOSE `68a7a49a6f618a363cdd87ba9e4827a2dffa4a9a`, clean at execution.
- Dynamic Localization V2 campaign source: RIOSE `a844bd6039a5c10d22ee0cc0ed1b866db7a8c1b6`, clean at execution; V2 source SHA-256 `f30f72b2159b50747c321cb5a19532f13043b6d2a51f1a1c32e9315d097a16cc`.
- External simulator: `GUZZBR1/frequencia` revision `ba2bdabf003722aae8292580e048f7092d0356d6`, clean at execution. Doctor found Sionna RT 2.2.0, ns-3.48 and LoRaWAN adapter available.
- The repository changes remain on the isolated research branch. No A–G branch was edited, no push was performed, and no automatic merge to `main` occurred. GitHub PR discovery was unavailable because the API/DNS connection failed.

## 5. Simulation Architecture

The archived H RF path composes scenario/request validation → Sionna RT synthetic channel → ns-3/LoRaWAN outcomes → gateway PHY timestamps → FREQUENCIA TDoA → offline truth scoring. The composition exists, but H packet/event/time attribution is not verified: source epochs are one second apart, while C.1 found FIFO association invalid in that regime. The declared 60 s parameter acts as a seeded phase window, not demonstrated cadence. Ground Truth is score-only in estimator code, but per-packet scores remain subject to the unresolved event-association issue.

The dynamic localization campaign is a separate analytic 2D LOS model. It supplies synthetic anchor coordinates and timestamps to Localization V2; it does not call the RF or ns-3 pipeline. The movement/health/reproduction/blockchain modules are not implicitly serialized into either path. See [dependency-graph.md](docs/research/beta-final/dependency-graph.md).

## 6. Evidence Classification

Evidence uses `SIMULATED`, `EXTERNAL_MEASURED_DATA`, `REAL_ON_CHAIN`, `EXPERIMENTAL`, `ENGINEERING_ESTIMATE`, and `NOT_EVALUATED`. The 13-run and 6,720-attempt campaigns are `SIMULATED`. Synthetic trajectory truth is not a measured dataset. The tag closure energy value is an `ENGINEERING_ESTIMATE` from assumed current inputs. No Beta run is `REAL_ON_CHAIN`.

## 7. Beta Scenario Contract

The versioned contract is [scenario-contract.schema.json](docs/research/beta-final/scenario-contract.schema.json), with [campaign-spec.json](docs/research/beta-final/campaign-spec.json) and four concrete scenarios. It binds animal/tag/device identities, coordinate frame, trajectory time/position, RF/network settings, faults, localization, blockchain mode and expected evidence classes. Request V1 validation rejects duplicate source identity mappings.

Each campaign run binds seed and scenario hash to a clean RIOSE SHA and a clean pinned FREQUENCIA SHA. Request hashes, runtime manifests, requested/effective parameter bindings and archived output hashes are present in [campaign-manifest.json](docs/research/beta-final/campaign-manifest.json). The manifest hash and all referenced packaged artifacts were checked.

## 8. Tag Simulation

The Tag Simulation Closure report records dataset-to-RESD-to-Renode-to-Zephyr-to-UART traces for distinct STATIC/WALK/RUN profiles and a golden-axis probe. The scoped sensor gate is PASS_SIMULATED. H's earlier zero-value finding came from an older MVP2 smoke report and is stale relative to the current closure artifacts. Antenna/openEMS is separate and remains PARTIAL_SIMULATED. The source worktree is dirty at base SHA `72ad69551b54eb069bb1c5f863dfff4066786965`; trace evidence is cited by artifact hashes, not attributed to that base commit.

## 9. RF Propagation

The H campaign produced Sionna RT records and gateway outcomes for four scenes, but its per-event attribution is not verified under the 1 s source/FIFO regime. Independent RF gap-closure evidence distinguishes 3 LOS received, 4 reflected geometric NLOS received, and 8 NO_PATH; hashes and geometry were verified. RF's bounded simulated gate is PASS_SIMULATED; site calibration remains FUTURE_PHASE. Vegetation and isotropic orientation are declared scope limits, not failures of this path-class gate.

This is a bounded model characterization. Scene materials/geometry and antenna behavior are not calibrated against a farm; it does not establish vegetation, orientation, multipath, or NLOS performance in deployment.

## 10. Network Scale

The ten-animal scenario declared `traffic_interval_s=60`, but archived source epochs are 0/1/2 s, which does not demonstrate 60-second cadence. Its 90 requests yielded 60 FIFO-attributed TX and 56 PHY receptions (93.3% of attributed TX), but C.1 excluded analogous 1 s source/FIFO rows after event-association mismatches. Treat these as raw simulator output, not validated per-animal delivery or localization evidence. C's separate corrected envelope supports PASS_SIMULATED_WITH_LIMITS only for its conditioned schedules.

The localization-unavailability scene records 6 attributed TX and 6 PHY receptions, with all 6 estimates `LT3_TIMESTAMPS`; unresolved event/time mapping prevents confident linkage to requested animal epochs. No application/server delivery was measured. Ten animals is not a capacity limit or guarantee.

## 11. Dynamic Localization

Localization V2 Final was reused directly; no new solver was created. The separate dynamic campaign covers movement/turn/stop, bad geometry, anchor loss, timing corruption/drift/jitter/quantization, packet loss and combined cases. It scheduled 28 × 10 × 24 = 6,720 epochs and retained input, numerical, accepted, error, false-confidence and recovery denominators.

Fail-closed examples include `CLOCK_UNCALIBRATED`, `CLOCK_UNQUALIFIED`, and loss of accepted estimates under two-anchor loss. D.1 closes its declared synthetic fault characterization as PASS_SIMULATED; 50/50 wrong-calibration and 3/3 poor-geometry+jitter false accepts are known high-risk failure modes, not new contradictions. The analytic harness assumes 2D LOS propagation and synthetic clock calibration; its nominal errors are not field accuracy.

## 12. Movement Intelligence

The separate Movement E2E worktree contains a measured-data research pipeline through Signal Engine, Behavior ML and SQLite persistence: 29,908 windows, six test animals, 6,524 persisted test records, SQLite reopen, train-only class selection and temporal-overlap audit. Pipeline status is PASS_WITH_RISK / RESEARCH_BASELINE. Its worktree is dirty and lacks an immutable run-source commit. H does not bind its RF events into that Movement path, so no continuous RF→Movement result is claimed.

## 13. Behavior ML

Behavior ML has an externally measured research baseline, but model quality is weak: accuracy 0.5336 vs majority baseline 0.5279, balanced accuracy 0.1991, macro-F1 0.1885. Animal-disjoint holdout and train-only class eligibility were audited. This supports EXTERNAL_MEASURED_DATA / EXPERIMENTAL_MODEL_RESULT research only, not reliable classification or RIOSE farm transfer.

## 14. Persistence

The Movement research run persisted 6,524 held-out test records and a read-only reopen returned them across six test animals. Records retain EXPERIMENTAL/NECK/SOURCE_RELATIVE semantics, unknown timezone and null confidence. This is evidence for that research persistence flow. H RF output is not wired to the store; no RF-to-database failure/recovery cascade is claimed.

## 15. BioSignature

BioSignature was invoked in the Movement research path and returned an insufficient-history/data outcome. No biological Ground Truth or independent biological validation was used. It supports no diagnosis, estrus, or pregnancy claim; status remains EXPERIMENTAL.

## 16. Health Anomaly

The health research layer was invoked only for safe investigation/insufficient-data outcomes. This is fail-closed software evidence, not diagnosis. No clinical labels, calibration or disease performance was evaluated; status remains PARTIAL/EXPERIMENTAL.

## 17. Reproduction Research

No reproductive outcome, estrus, fertility or pregnancy event dataset was evaluated in Movement E2E. `INSUFFICIENT_EVIDENCE` remains a safe outcome; the domain remains EXPERIMENTAL.

## 18. Blockchain

The available offline path covers event → commitment → SQLite outbox → signer → fake adapter → simulated receipt/read-back → integrity/tamper verifier. REAL_ON_CHAIN is NOT_ACHIEVED / EXTERNAL_BLOCKED: devnet funding failed and no publication transaction, signature, slot or chain receipt exists. Future on-chain integrity would not establish physical truth.

## 19. Hackathon Demo

The offline demo and tamper/integrity tests are available. The RF campaign did not feed its events into the demo, and no live transaction occurred. The demo is a separate SIMULATED path, not a combined hardware or chain demonstration.

## 20. Systemic Fault Injection

Separate campaigns exercised Tag missing-RESD fail-closed behavior; RF NO_PATH and reflected NLOS; controlled network contention; and localization anchor loss, timing corruption, stale/duplicate timestamps, wrong calibration, jitter and quantization. These were not one universal cross-domain fault run. The H event/FIFO association failure itself is a material integration finding. Database outage, live RPC failure and physical sensor-stream failure were not cascaded from H RF events.

## 21. Cascading Failures

The H outputs contain cases labeled as collision → no PHY RX → `NO_PACKET` and PHY RX → `LT3_TIMESTAMPS`, but the source-event/time association is unresolved under the FIFO regime; these are not accepted as validated per-animal cascades. D.1 independently characterizes synthetic anchor loss/recovery. Database and chain cascades were not run end-to-end.

## 22. Monte Carlo Campaign

The RF/network contract predeclared seeds `11`, `29`, and `47` for four scenarios. A second baseline run repeated seed `11` for replay comparison, giving 13 scheduled runs. The dynamic localization campaign used seeds `100`–`109` across 28 cases, 240 epochs per case/seed. All scheduled outcomes and per-domain denominators are retained.

## 23. Resource / Edge Estimates

For a nominal 12-byte payload every 60 seconds, raw payload volume is 1,440 × 12 = 17,280 bytes (17.28 kB decimal) per animal per day, before protocol metadata, retries or storage indexes. The simulator emitted 56.576 ms airtime for the declared SF7/125 kHz/12-byte configuration; extrapolating that model value gives about 81.5 s transmitter airtime per animal-day. Both are bounded `ENGINEERING_ESTIMATE` calculations from a SIMULATED setup, not measured device use or battery life.

The tag report's 0.878847 µAh integrated-window value uses assumed currents and is an `ENGINEERING_ESTIMATE`; no configured battery capacity or physical current trace supports a battery-life claim. Model memory, edge compute and storage capacity were NOT_EVALUATED.

## 24. Reproducibility

The official campaign's two baseline seed-11 runs used identical request SHA and the same normalized result digest. Raw result hashes differ because runtime provenance contains volatile fields; both remain in the manifest. The dynamic seed-100 replay used identical RIOSE revision and exact source hashes; all 672 records matched after excluding `runtime_ms`. These checks establish deterministic reproduction of the recorded output, not correctness of H's packet-to-source-event mapping. Details and digests are in [reproducibility.json](docs/research/dynamic-localization/reproducibility.json).

An attempt-history file discloses the earlier diagnostic executions: one pre-fix repeat gate lacked usable output digests, and one ten-animal request set was rejected before simulation for duplicate source identity mappings. Neither is treated as official final evidence; the final campaign is the clean 13/13 manifest.

## 25. Regression Tests

Full repository regression: `PYTHONPATH=src /home/gusta/projetos/RIOSE/riose/.venv/bin/pytest -ra` — 893 collected, 886 passed, 7 skipped, 0 failed, 0 deselected in 67.97 s. Seven CadQuery mechanical tests skipped; one existing Starlette/httpx deprecation warning. `python3 -m compileall -q src tests research/dynamic-localization-faults/experiment.py` and `git diff --check` passed. Environment note: system Python initially lacked dependencies and PyPI DNS failed, but an existing project venv was available; a first venv run without subprocess `PYTHONPATH` was corrected by rerunning with `PYTHONPATH=src`. Final classification: ENVIRONMENT_RECOVERED, no full-suite regression failure.

## 26. Red Team

Independent review found and corrected a false replay PASS caused by a missing output digest. H.1 review restored stale-downrated A–D and E component gates, and confirmed H's pooled PDR ratios are arithmetically correct. The governor then identified that all H scenarios use 0/1/2 s source epochs with FIFO TX attribution, a regime C.1 excluded after finding event-association mismatch. This keeps H PARTIAL: run hashes and completion counts cannot prove source-event integrity. D's 50/50 wrong-calibration and 3/3 poor-geometry+jitter false accepts remain known risks.

## 27. Claim Matrix

The required claim table is [claim-matrix.md](docs/research/beta-final/claim-matrix.md). It distinguishes the allowed bounded A–G component claims from H's unresolved per-event integration claims. Hardware/field validation, pregnancy detection, clinical diagnosis, general capacity, application delivery and REAL_ON_CHAIN are not allowed claims from this evidence.

## 28. Known Limitations

- The current Tag trace-closure output is uncommitted in a dirty worktree; cite artifact hashes and scoped PASS_SIMULATED, not the base source SHA as containing those changes.
- Sionna scene realism is synthetic and not site-calibrated.
- H tested ten animals; C separately tested a conditional PHY envelope up to 100 tags. Application delivery is not measured, and neither campaign establishes general field capacity.
- The V2 dynamic harness is analytic 2D LOS and exposes known false confidence under wrong calibration.
- The H RF integration does not establish event identity/time under the 1 s source/FIFO schedule; C.1 excluded this regime. See the per-run [temporal identity audit](docs/research/beta-final/temporal-identity-audit.json).
- H RF events are not connected to Movement or Blockchain; E's separate research pipeline is dirty/uncommitted and lacks immutable run-source provenance.
- Clinical, reproductive, hardware and field Ground Truth are absent.
- Current remote PR state could not be retrieved due GitHub API/DNS connectivity.

## 29. Beta Completion Matrix

See [completion-matrix.json](docs/research/beta-final/completion-matrix.json) for domain status, implementation/source, evidence, limitation, next stage and readiness. The canonical status ledger is [evidence-reconciliation.md](docs/research/beta-final/evidence-reconciliation.md). H remains PARTIAL because event/time identity is not established for its integrated campaign.

## 30. What Remains for Hardware Stage

1. Reproduce the scoped Tag trace closure from a clean source revision, then measure distinct physical RESD samples at the LIS2DW12 boundary during hardware validation.
2. Calibrate RF scenes against measured sites, then validate with actual RIOSE tags/gateways and timestamp clocks.
3. Sweep animal population, cadence, gateway loss and application/server delivery while retaining every denominator.
4. Test Localization V2 with measured clock error, NLOS and physical reference positions; address wrong-calibration false confidence.
5. Bind accepted event identities/timestamps into movement, persistence and offline blockchain flows before any field or on-chain claim.
6. Collect appropriate labeled behavior, health and reproductive datasets with independent evaluation design.

## 31. Final Verdict

**PARTIAL — A–G have scoped simulated/research evidence, but H's integrated scenario campaign has an unresolved source-event/cadence attribution failure.** The software path composes RF→network→localization, but the full 13-run campaign cannot establish per-event identity because it uses 1 s source epochs in the FIFO regime C.1 excluded; the declared 60 s interval is not demonstrated as an inter-transmission cadence. This is not hardware, field, clinical, reproductive, or commercial validation.

The official campaign has four scenario definitions and 13 runs scheduled, 13 completed, 0 failed; its separate dynamic campaign has 28 cases and 6,720 attempts. Completion is not proof of source-event attribution. The open H gate is correct event identity/time binding and faithful requested cadence, or independent evidence that every event mapping is valid. A–G governed statuses and limitations are listed in the ledger.

## 32. FINAL EVIDENCE RECONCILIATION

This governed addendum supersedes earlier H status assignments where they relied on stale evidence or missed an available worktree. It preserves the earlier assessments as history; no A–G worktree was modified.

- **Reclassified component gates:** TAG PARTIAL reverted to PASS_SIMULATED because H cited an older smoke report from before the firmware trace closure. RF PARTIAL reverted to PASS_SIMULATED for modeled LOS/NLOS/NO_PATH gap closure. NETWORK is PASS_SIMULATED_WITH_LIMITS for its separate corrected conditioned PHY envelope; this does not validate H's traffic identity mapping. LOCALIZATION is PASS_SIMULATED with HIGH-RISK_KNOWN_FAILURE_MODE; 50/50 wrong-calibration and 3/3 poor-geometry+jitter false accepts are already known adversarial outcomes. MOVEMENT is pipeline PASS_WITH_RISK / RESEARCH_BASELINE, while model quality remains WEAK_EXPERIMENTAL_MODEL_RESULT.
- **Antenna and chain separation:** antenna remains PARTIAL_SIMULATED. Offline Blockchain is available; REAL_ON_CHAIN is NOT_ACHIEVED / EXTERNAL_BLOCKED because no publication transaction, signature, slot or real receipt exists.
- **New H integration failure:** every H run uses source epochs 0/1/2 seconds. Across 129 requests, 86 were attributed TX and 43 final epochs were NOT_TRANSMITTED. These are raw adapter metrics, not validated event-attributed delivery. Each animal's second TX is 7 seconds after the first despite `traffic_interval_s=60`. C.1 documents that this parameter acts as a seeded phase window and that FIFO TX-start association is invalid for analogous 1 s source schedules. C.1 excluded those schedules after direct source-event mismatches. H does not independently bind actual TX starts to source identity/time. Therefore its PDR figures are arithmetic summaries of SIMULATED adapter records, not validated per-animal delivery or localization results. This integration validity issue keeps H PARTIAL.
- **PDR and hashes:** current H pooled PDRs are arithmetically correct at 100%, 0%, 100%, and 93.3% (8/8, 0/12, 6/6, 56/60). A previous audit's values 4.0/2.8 are stale against current HEAD and do not describe this renderer. Campaign hashes prove recorded content and reproducibility, not semantic event mapping.
- **Regression/environment:** system Python initially lacked dependencies; the existing project venv plus `PYTHONPATH=src` ran the complete suite: 893 collected, 886 passed, 7 skipped, 0 failed. This is ENVIRONMENT_RECOVERED, not a regression failure.
- **Allowed claims:** bounded SIMULATED Tag trace, RF path classes, corrected C PHY envelope, D fault characterization, H raw output records with attribution caveat, separate EXTERNAL_MEASURED_DATA Movement pipeline with weak model, offline simulated commitment/receipt, and ENGINEERING_ESTIMATE energy/airtime.
- **Prohibited claims:** hardware/field validation, app/server delivery, general capacity, H per-event/per-animal integration correctness, reliable behavior classification, diagnosis, estrus/pregnancy, or REAL_ON_CHAIN.
- **Governed verdict:** PARTIAL for H. The all-subsystem end-to-end claim is not supported. Component statuses stand independently under the evidence and provenance limits in [evidence-reconciliation.md](docs/research/beta-final/evidence-reconciliation.md).
