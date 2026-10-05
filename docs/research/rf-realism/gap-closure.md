# RF Realism Gap Closure

## Baseline

- Original campaign: `research/rf-realism-campaign`, reported as `PARTIAL`.
- Original campaign execution SHA in the final run summary: `f231ffc783f7881d63675faa782efbbb605eb778`.
- The original `campaign-spec.json` separately records `2c9c477321505ba7983acf63d1f07c634cf7002a`; both recorded values are retained with their artifact context, without rewriting the historical campaign evidence.
- Campaign B report HEAD: `cecda8d9145b169299d4fc077e800de9d8c4811c`.
- Follow-up branch: `research/rf-realism-gap-closure`.
- Follow-up code SHA used for the experiment: `95a81bc7b7ad8a45f008307fa301fb24506de04a`.
- The runner recorded `riose_dirty=true` because the first evidence manifest was untracked in the checkout at experiment time; the exact campaign script and inputs are SHA-256 bound below.
- Minimal reproduction: FREQUENCIA analytic and Sionna clear-link controls both ran; Sionna returned received paths and the expected output fields. The original external raw artifact SHA-256 was rechecked against the campaign summary and matched.
- The original 270 analytic links and 109 Sionna snapshots were not rerun. Their artifacts and code on the campaign branch were left unchanged.

## NLOS

The same TX/RX pair and radio settings were used across the clear control, wall-only control, and three reflector positions: TX `(200, 500, 8) m`, primary RX `(800, 500, 8) m`, 915 MHz, 125 kHz, 14 dBm, seed `20261005`. The wall is the finite plane `x=500 m`, `y=400..600 m`, `z=0..20 m`. It intersects the direct TX→RX segment at `(500, 500, 8) m`. Sionna ran with LOS enabled, specular reflection enabled, and `max_depth=1` throughout.

| Case | Direct path | Sionna state | Received power | Paths / evidence |
|---|---|---|---:|---|
| Clear control | Clear; no obstacle mesh loaded | `LOS_RECEIVED` | −68.301 dBm | 2 paths, including an LOS interaction-free path |
| Wall only | Blocked by wall | `NO_PATH` | `null` | 0 paths; no imputed value |
| Reflector `y=250 m` | Blocked by wall | `GEOMETRIC_NLOS_WITH_RECEIVED_PATH` | −78.887 dBm | 1 specular path; hit `(499.999, 250, 8) m`, delay `2.605219 µs` |
| Reflector `y=300 m` | Blocked by wall | `GEOMETRIC_NLOS_WITH_RECEIVED_PATH` | −77.772 dBm | 1 specular path; hit `(499.999, 300, 8) m`, delay `2.405365 µs` |
| Reflector `y=350 m` | Blocked by wall | `NO_PATH` | `null` | 0 paths |

The reflected path legs are checked against the wall bounds, and the interaction vertex must lie on the requested reflector plane. Both received NLOS cases satisfy those checks. Path lengths are not directly emitted by Sionna; the evidence labels lengths derived from the recorded delay. No receiver result was substituted or inferred from an object merely being present in the scene.

The five scenario cases emitted 20 rows: 5 analytic and 15 Sionna receiver rows. Across those Sionna rows there were 3 clear `LOS_RECEIVED`, 4 geometric received NLOS links, 8 `NO_PATH`, and 0 simulation failures. All NO_PATH records retain null power/CFR and remain in the counts.

Status: **closed for this bounded simulated geometry**. This proves the configured Sionna route can produce received geometric NLOS. It does not establish field or farm-wide propagation realism.

## Antenna Orientation

- Model: Sionna RT 2.2.0.
- Pattern: `PlanarArray(1×1, pattern="iso", polarization="V")` at TX and RX in FREQUENCIA `rf/sionna_backend.py::run_sionna_snapshot`.
- Orientation supported by this wrapper: no orientation input; a single isotropic element has no meaningful directional orientation response.
- Requested/effective orientation sweep: not run because no meaningful effect exists in this model.
- Status: `NOT_MEANINGFULLY_TESTABLE_WITH_CURRENT_ISOTROPIC_MODEL` (`MODEL_LIMITATION`).

This is a limit of the configured antenna model, not evidence that RIOSE supports or rejects directional orientation.

## Vegetation

- Capability: no foliage propagation model in the configured farm backend. Trees and pasture are inventory metadata, not ray-traced vegetation with a vegetation material.
- Method/results: not tested as physical vegetation. The Sionna scene can accept geometry/material proxies, but its single obstacle material here is a concrete proxy.
- Classification: `NOT_TESTED` / `MODEL_LIMITATION`; a future geometric/material proxy must be called `VEGETATION_PROXY_SIMULATED`.
- Limitation: no foliage attenuation, scattering, seasonal state, or calibrated vegetation properties are claimed.

Vegetation does not block the simulated campaign gate because the current limitation is explicit and no arbitrary foliage-loss model was added.

## Model Comparison

- Analytic: FREQUENCIA free-space plus fixed ground reflection; it ignores obstacle geometry.
- Sionna: configured PathSolver with LOS and specular reflections; not ground truth.
- Paired cases with a received result from both backends: 3.
- Sionna minus analytic power disagreement: mean −3.595 dB (min −7.495, max +3.091 dB).
- Interpretation: `MODEL_DISAGREEMENT`. Analytic rows explicitly attest that requested obstacle geometry was unsupported and ignored by that backend. No “analytic error against Sionna” claim is made.

## Evidence

- RIOSE SHA: `95a81bc7b7ad8a45f008307fa301fb24506de04a`; the runner recorded the dirty worktree state above.
- FREQUENCIA SHA: `ba2bdabf003722aae8292580e048f7092d0356d6`, clean detached source worktree.
- Sionna RT: `2.2.0`; deterministic seed: `20261005`.
- Requested/effective solver values, positions, geometry description, mesh hashes, backend states, paths, power, delay, and output hashes are in [gap-closure-evidence.json](gap-closure-evidence.json).
- Raw JSONL: [/home/gusta/.cache/RIOSE/rf_realism_gap_closure/formal/gap-closure-raw-runs.jsonl](/home/gusta/.cache/RIOSE/rf_realism_gap_closure/formal/gap-closure-raw-runs.jsonl), SHA-256 `988b7a569a2efd7b60238f480ba338ac0fb9fa3d2bb6ee773eccea5c9e0727c2`.
- Run summary: [/home/gusta/.cache/RIOSE/rf_realism_gap_closure/formal/gap-closure-summary.json](/home/gusta/.cache/RIOSE/rf_realism_gap_closure/formal/gap-closure-summary.json), SHA-256 `16bbff0e7a779080fbf2da05786660cd00f8fb79081340f4c42f583128780a9c`.
- Original campaign raw JSONL SHA-256 `a99a6500a34ed40ce51c16f0abea70bc680e2ae3c22e869917b54d69492b7296` was verified against its original summary.
- The finalized original summary's executed RIOSE SHA is `f231ffc`; its campaign spec records the earlier `2c9c477` provenance value. This difference is disclosed as-is and the archived campaign artifacts were not rewritten.
- Sionna backend source SHA-256: `2f2b352fe2f40d73cf2ee810b8aa1c730975f272bcb18edde112a7780891726d`; analytic source SHA-256: `158158af3fb50d50d9ed4c86a43acc26fcb49bb730b97d158651267c8bee7f5e`.

## Tests

- Focused RF follow-up tests: 4 passed.
- RF integration (campaign, FARM RF, runner): 33 passed.
- Full suite: 473 passed, 7 skipped, 0 failed; one upstream Starlette/httpx deprecation warning.
- Compileall: PASS.
- `git diff --check`: PASS.
- Gap-closure Sionna run: 5 Sionna snapshots, 5 analytic comparisons, 20 records, 0 simulation failures.

Timeout note: the earlier three 0.2-second subprocess fixture failures were scheduling-sensitive test-infrastructure behavior. The timeout is explicitly supplied by a synthetic runner test, not an RF runtime contract; that fixture passed 5/5 in isolation before, and the full suite passes here. No timeout was raised to mask the issue.

## Red Team

- Critical: 0.
- Major: 0.
- Minor: 1, resolved in the evidence presentation: Sionna does not emit path length directly; delay is retained and any path length is labeled as derived.
- Resolved checks: direct segment blocked; both NLOS interactions lie on the requested reflector; reflected legs avoid the blocker; Sionna PathSolver was used with no fallback; requested/effective obstacle and solver values are recorded; geometry/output hashes match; no-path rows and denominators are retained; seed sweep includes received and no-path outcomes; orientation and vegetation limits are accurately labeled; backend disagreement is not treated as truth.
- Remaining red-team blockers: none.
- Delegation: the independent native red-team audit ran successfully. Earlier specialized launches that depended on unsupported account models were not counted as completed audits.

## Final RF Verdict

**PASS_SIMULATED**. The campaign may advance from `PARTIAL` to `PASS_SIMULATED` for the stated simulated scope: a clear LOS control, received geometric NLOS with a verified specular interaction, and a separate no-path control are distinguished and hash-linked. Orientation and vegetation remain explicit model limitations. No result is `VALIDATED`; all conclusions remain `SIMULATED`.
