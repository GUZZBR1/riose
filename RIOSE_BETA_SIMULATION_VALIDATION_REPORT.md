# RIOSE Beta Simulation Validation Report

## 1. Executive Summary

**Verdict: PARTIAL.** A bounded, reproducible simulated campaign completed 13/13 scheduled runs across four scenarios, using RIOSE revision `68a7a49a6f618a363cdd87ba9e4827a2dffa4a9a` and clean FREQUENCIA revision `ba2bdabf003722aae8292580e048f7092d0356d6`. The campaign covers a one-animal control, ten-animal nominal traffic, two-animal collision stress, and localization unavailability; a separate Localization V2 experiment adds 28 cases × 10 seeds × 24 epochs (6,720 attempts).

The RF/network campaign demonstrates execution inside declared software models. It does not establish that every estimate is usable: the control had 8/8 converged estimates but only 2/8 quality-accepted; the collision case had 0/12 gateway PHY receptions; and the ten-animal case had 56/60 transmitted packets received by at least one gateway, with 40/56 estimates accepted. PHY reception is not application delivery.

The independent tag evidence remains PARTIAL because the RESD-to-LIS2DW12 raw STATIC/WALK values were both zero. Movement, behavior, BioSignature, health, reproduction, persistence, and blockchain are not bound into the RF campaign. Hardware, field, clinical, and reproductive validation are not claimed.

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

The archived RF path is scenario/request validation → Sionna RT synthetic channel → ns-3/LoRaWAN packet outcomes → gateway PHY timestamps → FREQUENCIA TDoA results → offline truth scoring. Ground Truth is score-only and is joined after estimator output.

The dynamic localization campaign is a separate analytic 2D LOS model. It supplies synthetic anchor coordinates and timestamps to Localization V2; it does not call the RF or ns-3 pipeline. The movement/health/reproduction/blockchain modules are not implicitly serialized into either path. See [dependency-graph.md](docs/research/beta-final/dependency-graph.md).

## 6. Evidence Classification

Evidence uses `SIMULATED`, `EXTERNAL_MEASURED_DATA`, `REAL_ON_CHAIN`, `EXPERIMENTAL`, `ENGINEERING_ESTIMATE`, and `NOT_EVALUATED`. The 13-run and 6,720-attempt campaigns are `SIMULATED`. Synthetic trajectory truth is not a measured dataset. The tag closure energy value is an `ENGINEERING_ESTIMATE` from assumed current inputs. No Beta run is `REAL_ON_CHAIN`.

## 7. Beta Scenario Contract

The versioned contract is [scenario-contract.schema.json](docs/research/beta-final/scenario-contract.schema.json), with [campaign-spec.json](docs/research/beta-final/campaign-spec.json) and four concrete scenarios. It binds animal/tag/device identities, coordinate frame, trajectory time/position, RF/network settings, faults, localization, blockchain mode and expected evidence classes. Request V1 validation rejects duplicate source identity mappings.

Each campaign run binds seed and scenario hash to a clean RIOSE SHA and a clean pinned FREQUENCIA SHA. Request hashes, runtime manifests, requested/effective parameter bindings and archived output hashes are present in [campaign-manifest.json](docs/research/beta-final/campaign-manifest.json). The manifest hash and all referenced packaged artifacts were checked.

## 8. Tag Simulation

The Tag Simulation Closure report records successful C/Zephyr/Renode paths, profile loading, firmware reads and 12 deterministic FSM runs. Its sensor gate remains PARTIAL: observed raw LIS2DW12 values for `STATIC` and `WALK` were both `0`, so distinct RESD sample propagation was not proven. Its antenna/openEMS results are partial or blocked on numerical convergence. The source worktree was dirty at audit; no hardware reading was available.

## 9. RF Propagation

The official campaign produced Sionna RT path/channel records and per-gateway outcomes for four synthetic scenes. The run manifests expose requested/effective solver parameters and whether values came from the request or an upstream default. The separate RF realism report contains 24 seeded software scenarios and explicitly labels its findings SIMULATED.

This is a bounded model characterization. Scene materials/geometry and antenna behavior are not calibrated against a farm; it does not establish vegetation, orientation, multipath, or NLOS performance in deployment.

## 10. Network Scale

The official ten-animal nominal scenario used a 60 s traffic interval and three seeds. Across its three runs, 90 requests yielded 60 transmissions and 56 packets with at least one gateway PHY RX (93.3% of transmitted packets). The two-animal, 0.01 s collision stress produced 12 transmissions and 0 gateway PHY RX; all 12 localization attempts were `NO_PACKET`.

The localization-unavailability scene had 6 transmissions, 6 gateway PHY receptions, but all 6 estimates were `LT3_TIMESTAMPS`. This points to the estimator input/anchor denominator, not a radio outage. No application/server delivery was measured. Ten animals is the largest nominal population tested here, not a capacity limit or capacity guarantee.

## 11. Dynamic Localization

Localization V2 Final was reused directly; no new solver was created. The separate dynamic campaign covers movement/turn/stop, bad geometry, anchor loss, timing corruption/drift/jitter/quantization, packet loss and combined cases. It scheduled 28 × 10 × 24 = 6,720 epochs and retained input, numerical, accepted, error, false-confidence and recovery denominators.

Fail-closed examples include `CLOCK_UNCALIBRATED`, `CLOCK_UNQUALIFIED`, and loss of accepted estimates under two-anchor loss. The `clock_drift_wrong_calibration` case produced 50 bad accepted estimates out of 50 accepted; this is a material unresolved false-confidence result. The analytic harness assumes 2D LOS propagation and synthetic clock calibration, so its tiny nominal errors are not field accuracy.

## 12. Movement Intelligence

Movement context and signal/behavior components exist in the source tree, but the campaign did not bind RF events into the movement pipeline. A separate movement E2E worktree pointer could not be resolved in this audit. No integrated movement result is claimed; the gate is EXPERIMENTAL.

## 13. Behavior ML

The behavior pipeline has software modules and synthetic fixtures/tests. This campaign did not evaluate externally measured, held-out animal/farm labels. Classification quality and transfer to a farm are NOT_EVALUATED; any behavior label claim remains EXPERIMENTAL.

## 14. Persistence

SQLite persistence, dataset writing, outbox and receipt components are covered by repository tests. They were not connected to the RF campaign and no database failure/recovery or scale workload was run. The gate is PARTIAL.

## 15. BioSignature

BioSignature remains an offline experimental module. No biological Ground Truth or independent biological validation was used. It supports no diagnosis, estrus, or pregnancy claim.

## 16. Health Anomaly

Synthetic safe behavior such as returning `INVESTIGATE` is useful fail-closed behavior, not a diagnosis. No clinical labels, calibration, or disease performance was evaluated. Health status is PARTIAL/EXPERIMENTAL.

## 17. Reproduction Research

Synthetic research fixtures do not establish estrus timing, pregnancy, fertility, or reproductive outcomes. No paired reproductive dataset was evaluated. `INSUFFICIENT_EVIDENCE` is an acceptable safe state; the domain remains EXPERIMENTAL.

## 18. Blockchain

The available demonstration uses a fake/offline adapter and local commitment/outbox/receipt/integrity checks. The Beta campaign did not publish to a live chain, so no campaign evidence is `REAL_ON_CHAIN`. Even future on-chain integrity would not establish physical truth.

## 19. Hackathon Demo

The offline demo components and tests exist, but the RF campaign did not feed its events into a combined demo run. The demo is PARTIAL and SIMULATED; it is not a live-chain or hardware demonstration.

## 20. Systemic Fault Injection

Dynamic localization exercised anchor loss, insufficient anchors, bad geometry, packet loss, missing/corrupt/stale/duplicate timestamps, clock offset/drift, stale/missing/wrong calibration, jitter and quantization. RF/network collision stress reached zero gateway PHY RX. Database failure, blockchain RPC failure and physical sensor-stream failure were not injected into the combined campaign.

## 21. Cascading Failures

One observed cascade was high-cadence collision → no gateway PHY RX → 12 localization `NO_PACKET` attempts. Another path preserved gateway PHY reception but produced `LT3_TIMESTAMPS` and no numerical localization. The synthetic dynamic harness also links anchor/timestamp loss to estimator availability. Database and chain failure cascades were not run end-to-end; no broader cascade claim is made.

## 22. Monte Carlo Campaign

The RF/network contract predeclared seeds `11`, `29`, and `47` for four scenarios. A second baseline run repeated seed `11` for replay comparison, giving 13 scheduled runs. The dynamic localization campaign used seeds `100`–`109` across 28 cases, 240 epochs per case/seed. All scheduled outcomes and per-domain denominators are retained.

## 23. Resource / Edge Estimates

For a nominal 12-byte payload every 60 seconds, raw payload volume is 1,440 × 12 = 17,280 bytes (17.28 kB decimal) per animal per day, before protocol metadata, retries or storage indexes. The simulator emitted 56.576 ms airtime for the declared SF7/125 kHz/12-byte configuration; extrapolating that model value gives about 81.5 s transmitter airtime per animal-day. Both are bounded `ENGINEERING_ESTIMATE` calculations from a SIMULATED setup, not measured device use or battery life.

The tag report's 0.878847 µAh integrated-window value uses assumed currents and is an `ENGINEERING_ESTIMATE`; no configured battery capacity or physical current trace supports a battery-life claim. Model memory, edge compute and storage capacity were NOT_EVALUATED.

## 24. Reproducibility

The official campaign's two baseline seed-11 runs used identical request SHA and the same normalized result digest. Raw result hashes differ because runtime provenance contains volatile fields; both raw hashes remain in the manifest. The dynamic seed-100 replay used identical RIOSE revision and exact source hashes; all 672 records matched after excluding only `runtime_ms`, which is expected to vary. Details and digests are in [reproducibility.json](docs/research/dynamic-localization/reproducibility.json).

An attempt-history file discloses the earlier diagnostic executions: one pre-fix repeat gate lacked usable output digests, and one ten-animal request set was rejected before simulation for duplicate source identity mappings. Neither is treated as official final evidence; the final campaign is the clean 13/13 manifest.

## 25. Regression Tests

Focused Beta, Simulation Lab/evidence and Localization V2/dynamic tests passed during implementation. A final full-suite run, including collection counts, skips, compileall and `git diff --check`, is recorded below after final report generation. Any skip/warning is reported rather than described as a full pass without qualification.

## 26. Red Team

Independent review found and corrected a false replay PASS caused by a missing output digest; a regression test now requires a nonempty normalized digest. It also rejected treating convergence as successful localization: control quality acceptance was only 2/8, collision was 0/12 `NO_PACKET`, and the localization-unavailability scenario was 6/6 `LT3_TIMESTAMPS`. The wrong-calibration case's 50/50 bad accepted estimates remains open. The campaign preserves TX/RX/delivery distinctions, score-only truth and per-scenario denominators.

## 27. Claim Matrix

The required claim table is [claim-matrix.md](docs/research/beta-final/claim-matrix.md). In particular, hardware/field validation, pregnancy detection, clinical diagnosis, and general network capacity are not allowed claims from this evidence.

## 28. Known Limitations

- Tag dataset values did not propagate distinctly to the simulated LIS2DW12 output.
- Sionna scene realism is synthetic and not site-calibrated.
- Application delivery is not measured; no scale sweep exceeds ten animals.
- The V2 dynamic harness is analytic 2D LOS and exposes false confidence under wrong calibration.
- Movement/behavior/persistence/health/reproduction/blockchain are not integrated with the Beta RF run.
- Clinical, reproductive, hardware and field Ground Truth are absent.
- Current remote PR state could not be retrieved due GitHub API/DNS connectivity.

## 29. Beta Completion Matrix

See [completion-matrix.json](docs/research/beta-final/completion-matrix.json) for domain status, implementation/source, evidence, limitation, next stage and readiness. Evidence/provenance and bounded replay pass within scope; several domain gates remain PARTIAL or EXPERIMENTAL.

## 30. What Remains for Hardware Stage

1. Demonstrate distinct RESD sensor samples at the LIS2DW12 boundary and rerun Tag closure from a clean revision.
2. Calibrate RF scenes against measured sites, then validate with actual RIOSE tags/gateways and timestamp clocks.
3. Sweep animal population, cadence, gateway loss and application/server delivery while retaining every denominator.
4. Test Localization V2 with measured clock error, NLOS and physical reference positions; address wrong-calibration false confidence.
5. Bind accepted event identities/timestamps into movement, persistence and offline blockchain flows before any field or on-chain claim.
6. Collect appropriate labeled behavior, health and reproductive datasets with independent evaluation design.

## 31. Final Verdict

**PARTIAL — RIOSE's declared simulated RF/network/localization paths are reproducibly characterized for the archived scenarios, while tag propagation, broader capacity, integrated movement/intelligence, physical validation and several domain gates remain open.** This is not a prototype, hardware, field, clinical, reproductive, or commercial validation.

The official campaign has four scenario definitions and 13 runs scheduled, 13 completed, 0 failed; its separate dynamic campaign has 28 cases and 6,720 attempts. The explicit open gates are TAG, expanded RF calibration, network capacity/application delivery, wrong-calibration false confidence, movement E2E, and the integration/validation limits for behavior, persistence, BioSignature, health, reproduction, blockchain and demo.
