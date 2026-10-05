# RF Realism Campaign results

## Status

**RF REALISM CAMPAIGN: PARTIAL — requested propagation campaign executed; unsupported or unverified features remain explicit.** All outputs are `SIMULATED`; nothing here is field, deployment, hardware, regulatory, or physical validation.

| Area | Status | Evidence / limitation |
|---|---|---|
| Analytic backend | COMPLETE | 270 direct calls to FREQUENCIA's real `rf.channel.simulate_link`; this is a deterministic free-space plus single flat-ground-reflection model. |
| Sionna RT | COMPLETE | 109 real snapshots on Sionna RT 2.2.0; 0 simulation failures. CPU execution. |
| LOS | COMPLETE | Baseline, distance, height, geometry, and Monte Carlo have valid direct paths. |
| Geometric NLOS | PARTIAL | A finite synthetic wall intersects all 3 checked direct rays. Sionna returned `NO_PATH` on those 3 links; it did not produce an obstructed-but-received NLOS path. A separate reflection-only solver control is labeled configuration-forced, not geometry-produced NLOS. |
| Multipath | COMPLETE within wrapper | Direct-only and ground-reflection controls were executed; path components, CIR/CFR, and delay arrays are preserved. Diffuse scattering, refraction, and diffraction are disabled. |
| Orientation | NOT TESTED | Current Sionna wrapper uses a fixed isotropic 1x1 array and exposes no tag yaw/pitch/roll. Analytic model ignores orientation. |
| Height | COMPLETE as assumed sweep | 9 matched TX/RX height combinations; heights are scenario assumptions, not a measured tag placement. |
| Terrain | PARTIAL | Flat control versus synthetic relief mesh: 1 of 3 relief links had `NO_PATH`, 2 retained LOS. Surface is procedural and unsurveyed. |
| Vegetation | NOT TESTED | Tree inventory has no ray-traced vegetation mesh or vegetation RF material. |
| Farm geometries | COMPLETE for synthetic layouts | Six layouts, 9 TX samples each, 3–6 gateways each. Includes corners, asymmetry, one-side concentration, sparse, six-gateway, and 1000×400 m elongated property layouts. |
| Monte Carlo | COMPLETE for position sampling | 30 seeded positions, 30 analytic links and 90 Sionna links. The Sionna path solver is deterministic; this is not stochastic fading. |
| Analytic × Sionna | COMPLETE for paired inputs | 267 received-power pairs use identical TX/RX coordinates, frequency, bandwidth, and TX power. Treat differences as model disagreement. |
| Independent red team | PARTIAL | Three native subagent launches failed due unsupported account/model combinations. A separate sequential adversarial audit was completed by the primary agent; it is not an independent reviewer. |

## Git

| Field | Value |
|---|---|
| Repository | `GUZZBR1/riose` |
| `origin/main` at audit | `6b2dda81016150e6df9687d14aa4584d23eb6302` |
| Branch base / initial SHA | `2c9c477321505ba7983acf63d1f07c634cf7002a` (`research/simulation-lab`, clean, 12 commits ahead of `origin/main`) |
| Final branch | `research/rf-realism-campaign` |
| Campaign execution SHA | `f231ffc783f7881d63675faa782efbbb605eb778` (clean source tree; execution and aggregate provenance bind to this revision) |
| Commits | `196eb19`, `9108d1b`, `f231ffc`, plus the final aggregate-evidence commit; campaign work is isolated from other worktrees. |
| Push / PR / merge | None / none / none |
| FREQUENCIA | External repository; campaign used a clean detached worktree at the pinned revision. Existing primary checkout had unrelated dirty documentation/results and was not modified. |

## Agents

Required roles were attempted as architecture auditor, Sionna specialist, and analytic/red-team critic. The account rejected child model launches (`gpt-5.3-codex` and `gpt-5.4-mini` unsupported). The primary agent performed sequential architecture, Sionna, analytic, and adversarial passes. This is documented as a delegation limitation, not represented as an independent agent sign-off.

## Campaign scale and setup

- Frequency 915 MHz; bandwidth 125 kHz; TX power 14 dBm; seed 20261005.
- Analytic: 270 per-link calls, deterministic, seed not consumed.
- Sionna: 109 solver snapshots; each has 3–6 receiver links.
- Raw records: 656; simulation failures: 0; `NO_PATH` links: 4; deterministic repeat comparison: identical physical observables.
- Runtime: 15.17 s in the final verified run.
- Environment: Sionna RT 2.2.0, Mitsuba 3.9.1, Dr.Jit 1.5.0, NumPy 2.5.3; WSL2/Linux, CPU (`CUDA_VISIBLE_DEVICES=-1`).
- Inputs and raw artifact hashes: [aggregate-summary.json](aggregate-summary.json). The full raw path, including each Sionna path/CIR/CFR record, remains outside Git under the per-run cache path in that summary.

The analytic adapter in the existing RIOSE Simulation Lab does **not** map request values into FREQUENCIA: it executes a fixed smoke scenario. This campaign calls the actual external FREQUENCIA analytic function directly and records its effective model. The Sionna request adapter supports a narrower FARM config; this campaign calls the existing FREQUENCIA direct Sionna wrapper to configure exact matched link positions. No simulator architecture or dependency was copied into RIOSE.

The `NO_PATH` denominator is retained separately from simulation failure. This campaign has no transmitter-off state or LoRa receiver/detector; therefore `NOT_TRANSMITTED` and `NOT_RECEIVED` are not generated or inferred.

## Distance

Matched link TX `(d, 0, 1.5 m)` to RX `(0, 0, 8 m)`. Each backend produced 8/8 links; no `NO_PATH`; all exceeded the declared engineering threshold of −127 dBm. Selected P50s are −53.05 dBm analytic and −52.75 dBm Sionna. At 1 km, received power was −80.73 dBm analytic and −85.75 dBm Sionna. These are idealized simulated powers, not receiver sensitivity or range claims.

| Distance | Analytic dBm | Sionna dBm |
|---:|---:|---:|
| 5 m | −35.48 | −36.07 |
| 10 m | −38.09 | −41.14 |
| 25 m | −46.09 | −46.10 |
| 50 m | −49.24 | −50.69 |
| 100 m | −56.87 | −54.81 |
| 250 m | −64.47 | −62.97 |
| 500 m | −73.21 | −73.97 |
| 1000 m | −80.73 | −85.75 |

## Height

Nine matched combinations of TX heights 1.0/1.5/2.5 m and RX heights 4/8/12 m at a 100 m horizontal separation. All 9 links per backend had paths and exceeded the engineering threshold. Across the sweep, analytic power ranged −60.44 to −55.10 dBm; Sionna ranged −62.14 to −53.05 dBm. This describes sensitivity of these assumptions only.

## Orientation

Not tested. Both paths use orientation-independent isotropic/scalar assumptions. No ear-tag antenna pattern, yaw, pitch, roll, or polarization rotation result is claimed.

## LOS / NLOS and combined stress

- Clear controls produced valid LOS paths.
- The test wall is a finite vertical synthetic mesh at x=500 m, y=400–600 m, z=0–20 m. Segment-plane arithmetic confirmed direct-path intersection for all 3 TX/RX pairs. Sionna produced `NO_PATH` for 3/3; analytic produced 3 paths because the model cannot consume an obstacle. The analytic outputs explicitly label the wall `NOT_SUPPORTED_IGNORED_BY_ANALYTIC_BACKEND`.
- In a separate solver control with `los=False`, `specular_reflection=True`, Sionna returned one reflection path and status `NLOS` on 4 links. This status is explicitly marked `LOS_PATH_DISABLED_BY_SOLVER_CONFIGURATION; NOT_GEOMETRIC_NLOS`.
- No link was assigned artificial power for `NO_PATH`; the 3 geometric obstruction links remain outage under this model configuration, not `NOT_RECEIVED` events.

## Multipath

Analytic links contain exactly two modeled components: a direct free-space path and one flat-ground image path with fixed coefficient −0.35. Sionna controls returned 2 paths with LOS plus specular ground reflection, 1 path in direct-only mode, and 1 path in reflection-only mode. The analytic reflection coefficient is not calibrated. Sionna diffuse reflection, refraction, and diffraction are explicitly disabled. No stochastic scattering or measured antenna response is present.

## Terrain and vegetation

The relief is generated from the pinned FREQUENCIA Brazil reference geometry and is not surveyed. Endpoints use the synthetic local terrain elevation plus assumed antenna height. Of 3 relief links, 1 returned `NO_PATH` and 2 returned LOS paths. This is a terrain-mesh proxy, not terrain validation. Vegetation, fences, pasture, and animal-body obstruction are not ray-traced.

## Farm geometry

Six layouts × nine samples × the layout's 3–6 gateways were run for each backend. Both backends had 9/9 sampled positions with at least one link above the engineering threshold in every layout. Analytic and Sionna each returned available paths for all 216 geometry links. This grid is intentionally sparse and cannot be generalized to a surveyed property.

## Monte Carlo

30 uniform TX positions over the synthetic 1000×1000 m square, seed 20261005, assumed TX heights selected from 1.0/1.5/2.5 m. Analytic produced 30 links; Sionna produced 90 links to three gateways. All had paths and passed the engineering threshold. Power P10/P50/P90 was −75.09/−70.10/−61.32 dBm analytic and −89.44/−76.65/−60.75 dBm Sionna. This samples position uncertainty only; no random fading, material, or environment configuration was varied.

## Analytic × Sionna

Across 267 paired received-power records, Sionna-minus-analytic disagreement had mean −1.86 dB, P10 −4.66 dB, median −1.46 dB, P90 +1.53 dB, and range −6.47 to +5.01 dB. Pairs use matching coordinates and radio inputs; their channel implementations and power semantics differ. Sionna is not treated as truth and these numbers are not error against ground truth.

## Metrics and coverage

Coverage is reported only against `ENGINEERING_ASSUMPTION` −127 dBm, derived from −174 dBm/Hz thermal noise + 10log10(125 kHz) + 6 dB assumed noise figure − 10 dB assumed minimum SNR. All available links in the distance, height, geometry, and Monte Carlo controls exceeded that threshold. It is not hardware sensitivity, LoRa decode probability, or measured observability. SNR columns in raw records are derived from this same noise assumption; RSSI is labeled simulated received power. Per-path delays, path counts, CIR/CFR, null powers, and model pairs are in the external raw JSONL.

## Tests and gates

- Focused Simulation Lab/contract/adapter/evidence tests: **101 passed**.
- Full repository run: first execution **468 passed, 7 skipped, 3 failed**. The 3 failures were parameterizations of a subprocess test with a 0.2-second timeout under full-suite load; the failures timed out before the expected process-output assertions.
- Isolated rerun of that parametrized test: **5 passed**. A second complete run finished **471 passed, 7 skipped, 0 failed** in 80.59 s (one upstream Starlette/httpx deprecation warning).
- `compileall` and `git diff --check`: run again at final gate.

## Sequential red-team review

| Challenge | Evidence / disposition |
|---|---|
| Sionna treated as ground truth | Not done; comparison reports only `MODEL_DISAGREEMENT`. |
| Analytic propagation treated as physical | Not done; all records SIMULATED; model is explicit and uncalibrated. |
| Request forwarded but ignored | Existing analytic adapter limitation was found; this campaign bypasses it through direct pinned FREQUENCIA functions and records actual model values. |
| Fake NLOS | Wall ray intersection tested; all three remain `NO_PATH`; reflection-only NLOS is explicitly configuration-forced. |
| Unit confusion | All geometry is ENU metres, delays seconds, frequency/bandwidth Hz; wall and flat PLY comments state metres. |
| Orientation silently ignored | Matrix and report say NOT TESTED / ignored. |
| Seed cherry-picking | Position generator seed fixed and recorded; Sionna same-request repeat compared with local object IDs excluded; physical outputs matched. Analytic seed is recorded as not consumed. |
| Failed simulations / NO_PATH dropped | Final campaign has zero failures; 4 `NO_PATH` link records stay in raw/aggregates with null power. |
| Stale scene/output reuse | Campaign constructs new runtime scenes, geometry-specific cache keys, and hashed generated meshes/output. An early cache-key mismatch produced six recorded failures in a discarded pilot; the key was corrected before the final clean run. |
| Unhashed external artifacts / dirty checkout | Pinned clean FREQUENCIA worktree SHA and source/mesh/raw hashes are recorded. Original dirty checkout was not modified. |
| Different paired inputs | 267 pairs join on case and exact RX coordinates; TX coordinates and radio values are recorded per row. |

## Limitations and next steps

Analytic: free-space plus one fixed-coefficient ground reflection, always LOS, no shadowing/obstacle/antenna/noise randomness. Sionna: isotropic single-element arrays; finite synthetic geometry and materials; no diffraction/scattering in active wrapper; no receiver/noise/demodulator. Antennas are assumptions rather than measured patterns. Terrain, wall, and land use are proxies; vegetation and animal body are absent. Hardware/field validation has not started.

Use these outputs as simulated input candidates for separate network-scale and dynamic-localization work. They do not establish either system's field performance, and this campaign made no Localization V2 changes.
