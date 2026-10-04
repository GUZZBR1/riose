# RIOSE Simulation Lab

## Purpose and boundaries

`research/simulation-lab` is an experimental workbench for future simulation research related to RIOSE. Product behavior and public contracts remain in the existing product areas, including `src/riose/products/livestock_tracking/simulation`, `src/riose/products/ear_tag/digital_twin`, and their established tests. The lab reuses the versioned request/result contract, external runner, result adapter, and evidence provenance modules without adding a second product simulation domain.

The FARM RF campaign dispatches a small request to the independent `GUZZBR1/frequencia` repository. `frequencia` owns the FARM environment, generated terrain/obstacle meshes, Sionna RT calls, and rich RF outputs. RIOSE owns the request, explicit identity mappings, runner boundary, canonical adapter call, and run manifest. See [runner limits and commands](simulation-lab-runner.md).

`GUZZBR1/frequencia` remains an independent project and repository. The lab
connects to its pinned external checkout through the existing runner boundary;
its source must not be copied into RIOSE or treated as a vendored dependency.

## Evidence and provenance

**SIMULAÇÃO ≠ VALIDAÇÃO FÍSICA.** Results from Sionna, ns-3, analytical models, digital twins, or any other simulator are simulated results. They must not be promoted automatically to physical or experimental evidence, product readiness, or measured claims.

Future reports must identify the result as simulated and record enough provenance to reproduce and assess it, including the simulator and version, configuration, input data references, code revision, random seeds where applicable, and execution date. Missing provenance must be stated rather than inferred.

## Dependencies and artifacts

Keep heavyweight simulators, external checkouts, downloads, virtual environments, caches, builds, and temporary outputs outside tracked product code and source history. Do not add heavyweight dependencies as part of this foundation. The current `.gitignore` already covers common environments, caches, and selected generated results; preserve its existing dataset and result conventions. Add narrowly scoped ignore rules only when a concrete lab artifact path is introduced, so legitimate RIOSE datasets and evidence remain versionable.

Do not commit large raw datasets or unfiltered simulator outputs. Keep them in an appropriate external or ignored storage location and retain compact, reviewable summaries with provenance when they are useful to the repository. Track small inputs or artifacts only when licensing, size, and reproducibility are clear.

## Future integration with `main`

This branch is a research staging area; do not assume it will be merged wholesale into `main`. Develop and evaluate experiments here, then select mature work, create a clean branch from the then-current `main`, and selectively port approved code and evidence into a small, auditable pull request. Keep laboratory-only environments, caches, datasets, raw outputs, dependencies, and temporary tools out of that port unless each item is explicitly reviewed and justified.

## Simulation Result V1 adapter

`riose.simulation_adapter` converts a validated `riose.simulation.result/v1`
document into the existing `RFObservation` and `Estimate` contracts. It needs
explicit one-to-one ID mappings and returns conversion counts/reasons plus
per-record provenance sidecars that link canonical records back to the source
run. The sidecars retain channel, transmit, receive, path, backend, coordinate
frame, and provenance details that the canonical records do not model.

The adapter preserves `SIMULATED`, rejects `VALIDATED` simulation rows, and
does not synthesize missing metrics. `received_power_dbm` stays in the sidecar
and canonical `rssi_dbm` remains null unless the caller opts into the
compatibility mapping. Propagation delay is converted from seconds to
nanoseconds but labeled `SIMULATED_PROPAGATION_DELAY`, not measured ToF.
Location output becomes an `Estimate` only when supplied in the result; its
`ENU_LOCAL` frame and vertical coordinate remain in provenance because the
existing estimate contract stores only x/y. Ground truth is not an adapter
input or estimate fallback.

Run the compact demonstration with `python -m riose.simulation_adapter` from
the repository root. It consumes only the committed fixture and runs no
simulator or campaign.

## FARM RF Digital Twin smoke

Run the committed request with the independent checkout and its configured
Sionna environment:

```bash
PYTHONPATH=src python -m riose.simulation_lab run examples/farm_rf_v1.json \
  --repo /path/to/frequencia --timeout 1800
```

The request declares `sionna-rt`; dispatch does not fall back to the analytic
backend. The runner creates an upstream FARM `ExperimentSpec`, trajectory CSV,
and effective config outside tracked source, invokes `python -m hub.run`,
validates the engine artifacts, emits a Simulation Result V1, and calls the
existing `riose.simulation_adapter` to create canonical observations with
provenance sidecars. Engine output stays under
`frequencia/results/riose_simulation_lab/`; RIOSE run manifests, results, and
adapted records stay in the external RIOSE simulation run cache. The runner
adds a local `.git/info/exclude` rule for generated external engine output.

The request uses one synthetic tag/transmitter, four gateways, three
timestamps, 915 MHz, and a bounded solver configuration. Its gateway `z`
coordinates are ENU elevations; the adapter converts them to the upstream
FARM config's height-above-terrain field using the declared terrain equation.
Trajectory `z` values remain absolute ENU elevations. The upstream solver
uses the terrain mesh and shed/obstacle mesh. Trees, fences, paddocks, roads,
corral, troughs, and feeders remain configured inventory outside the
ray-traced meshes. Material and isotropic antenna assumptions are retained in
the run manifest.

All Sionna outputs remain `SIMULATED`. Simulated received power stays distinct
from physical RSSI; after Feature 5 integration, gateway PHY reception, SNR,
and TDoA are available from their respective simulation stages. Propagation
delay is labeled simulated in adapter provenance. This run does not validate
physical range, antennas, hardware, animal behavior, or field accuracy.

## Simulation evidence pipeline V1

`riose.simulation_evidence` packages a completed V1 request/result pair or a
failed-run `failure.json`. Build input directories contain `request.json`,
either `result.json` or `failure.json`, and optional source files selected
explicitly with `--artifact`. It accepts both root-level fixtures and the
runner's `request/request.json`, `result/result.json`, and `manifest.json`
layout. Selected files are copied below `plots/`; raw result files, logs, and
unselected artifacts are never copied automatically. Artifact selection is
optional for runs with no generated figures.

```sh
python -m riose.simulation_evidence build examples/simulation-evidence-campaign PACKAGE_DIR \
  --artifact link-overview.svg
python -m riose.simulation_evidence build CAMPAIGN_DIR PACKAGE_DIR \
  --artifact link-overview.svg --riose-repo . --frequencia-repo ../frequencia
python -m riose.simulation_evidence verify PACKAGE_DIR
```

The builder validates V1 inputs, derives a null-aware summary, records
request, canonical source-result, and available engine-output hashes, emits a
report from the manifest and summary, checks
the package, and atomically publishes it only when valid. Verification rejects
unknown schemas, non-SIMULATED classifications, request/configuration/backend
mismatches, modified or missing outputs, unsafe paths and symlinks, extra files,
secret-like inputs, and packages exceeding the configured 25 MiB total / 10 MiB
per-source-file limits. Existing destination paths are preserved. Every
included figure must be selected explicitly. Configuration separates requested
values from values recovered from a run manifest or hash-checked engine summary;
the built-in analytical smoke currently ignores several request parameters, so
unknown used values stay `NOT_AVAILABLE`.

The package is an integrity-checked index, not a signed authenticity claim:
the manifest itself is not self-hashed. SHA-256 detects accidental or
uncoordinated changes to listed files, not an attacker who can rewrite the
entire package and its manifest. The current V1 result contract does not carry
network collisions, localization convergence, or ground-truth errors; those
summary values remain `NOT_AVAILABLE`, never fabricated zeros. V1 link rows do
not identify network packets, so TX/RX/drop/PDR metrics also remain unavailable
instead of treating each receiver link as a distinct transmission. The packager
does not execute a simulator, and physical/field validation remains
`NOT_VALIDATED`.

### Simulation Lab feature audit (current checkout)

- **1. Simulation Contract — PARTIAL.** Request/result V1 validated the real
  FARM output path and identities, ISO timestamps/provenance, ENU positions,
  LOS/NO_PATH, power, delay, phase, SNR, packet/reception states, and null
  localization estimates. CIR/CFR arrays and full multipath channel data stay
  in hash-identified external raw output; they are not represented in the
  compact V1 result or canonical adapter. See the binding audit in
  [`simulation-lab-agent-protocol.md`](simulation-lab-agent-protocol.md).
- **2. Simulation Lab Runner — PARTIAL.** Pinning, remote/dirty checks,
  isolated process invocation, timeout/output bounds, backend selection,
  request hashing, and generated FARM inputs are implemented. The analytic
  backend still runs a fixed smoke scenario and does not bind request geometry,
  radio values, or seed to that scenario; its effective values remain
  unavailable. The Sionna FARM route binds the supported fields and rejects
  unsupported solver options, but `trajectory.reference` cannot yet be
  resolved and is rejected by the route.
- **3. RIOSE Simulation Adapter — PASS for the current V1 projection.** It
  requires explicit mappings, preserves nulls and failure states, keeps
  simulated power distinct from RSSI, labels propagation delay as simulated,
  preserves `SIMULATED`, and does not accept GroundTruth as an estimator input.
- **4. FARM RF Digital Twin — PASS for the supported synthetic FARM route.**
  Clean pinned `frequencia` run `83e48a4fc1364459b2ec37ae2d154313` produced 12
  links: 9 LOS and 3 NO_PATH. Sionna RT 2.2.0 ran on CPU. The request and
  generated configuration hashes are recorded. The scene uses synthetic,
  uncalibrated terrain/material and idealized isotropic antennas; it does not
  establish physical propagation accuracy.

Each FARM run manifest includes
`riose.simulation.parameter-binding/v1`: Sionna RF/seed/backend/solver and
network settings are checked against engine output. Temporal detector/clock
settings are forwarded to the pinned network adapter and output records are
hashed and checked for reception coverage, but the engine does not attest the
effective temporal configuration; the manifest therefore marks it
`FORWARDED_OUTPUT_HASHED` and leaves effective values unavailable. The runner
checks the exact requested timestamp/tag/receiver link set and each localization
estimate's packet-to-animal/device identity. It also requires one localization
estimate per transmitted packet and cross-checks eligible/converged counts
against estimate statuses. The analytic smoke manifest explicitly marks
request-specific radio, seed, trajectory, and solver values as unsupported or
unbound. Evidence packaging carries those statuses and does not label an
unapplied request seed as used.
- **5. Network & Localization Digital Twin — PASS for supported simulations.**
  That run used ns-3 3.48 and LoRaWAN v0.3.7: 2 transmitted packets, 6 gateway
  PHY receptions, 2 NO_PATH events, simulated packet PDR 1.0, and 2 TDoA
  attempts (1 converged, 1 failed). Conditional RMSE was 4,349.93 m. Controlled
  collision run `fbbdf61cffef45119eab802148b652d9` produced 12 INTERFERENCE
  events and PDR 0.0; controlled detector failure run
  `a5d8a657d5474db48f25e4d20a33149c` retained 6 PHY receptions but had zero
  eligible timestamps and 2 null failed estimates. PHY reception is not
  application delivery; convergence is not accuracy.
- **6. Simulation Evidence Pipeline — PASS for supported V1 and runner
  workspaces.** Three independently verified packages (baseline, collision,
  detector failure) reported valid schema and hashes, with `SIMULATED` status.
  Extra, modified, unsafe, oversized, or symlinked package files fail closed.

## Historical campaign evidence (pre-consolidation source state)

The canonical baseline request was `farm-rf-smoke-v1`, seed `20261003`,
backend `sionna-rt`, 915 MHz, 125 kHz, and 14 dBm. The FARM trajectory had 3
timestamps and 4 gateways. Network settings were SF7, 12-byte payload, and a
60-second traffic interval. Network settings were checked against returned
artifacts. Detector and clock settings were forwarded, while their outputs
were hashed and checked for reception coverage; the engine did not attest
their effective configuration. The campaign's 0–2 second FARM interval has no animal or
physical time interpretation.

| Provenance or result | Value |
| --- | --- |
| RIOSE revision at run | `73e4464d09f75a72bb9f3f5935c7e40bdb1570c3` (`dirty=true`; six-feature work was uncommitted) |
| frequencia | `ba2bdabf003722aae8292580e048f7092d0356d6`, `dirty=false`, canonical upstream remote |
| Environment | Python 3.12.3; Sionna RT 2.2.0 on CPU; ns-3 3.48; LoRaWAN v0.3.7 |
| Request SHA-256 | `5b226a661f6a3d7dd9f3d4fb47832279b3bfa9e95734521a4739972c44ad082e` |
| Raw Sionna output SHA-256 | `a24b5965a263997d5c7446abc76cbd8a697b3d90f9e31757a5cdd61c32ec9c56` |
| Run workspace | `/home/gusta/.cache/RIOSE/simulation_runs/83e48a4fc1364459b2ec37ae2d154313` |
| Evidence package | `/tmp/riose-simlab-evidence-83e48a4fc1364459b2ec37ae2d154313` — 3 artifacts, schema/hash verification PASS |

The campaign generated no CIR/CFR fields in the canonical V1 result. It
retained external raw output by hash instead. The evidence package is an
integrity-checked index, not a signature. The RIOSE revision was dirty at the
time of this campaign, so reproducing that exact software state requires the
corresponding local source snapshot in addition to its commit SHA.

At that point, the full suite reported **460 passed, 7 skipped**, including
request/effective binding divergence, unsupported trajectory handling, and
exact raw-link correspondence cases. One existing Starlette/httpx
deprecation warning remains.

Sionna simulation is not field validation. ns-3 simulation is not deployment
validation. TDoA convergence is not accurate localization. `PHY_RECEIVED` is
not application delivery. A 1 ps simulator resolution is not 1 ps hardware
accuracy. No physical or field validation is claimed.


## Consolidated clean-source campaigns (Cycle 1)

The final campaigns ran from clean RIOSE commit
`7a176e703e25aba997347a1236c9be7845615934` and clean pinned FREQUENCIA
commit `ba2bdabf003722aae8292580e048f7092d0356d6` (Sionna RT 2.2.0 CPU,
ns-3 3.48, LoRaWAN v0.3.7). The outputs below were generated after the
localization completeness and temporal-binding review fixes. They are
simulated synthetic scenarios; none is field validation.

| Campaign | Workspace | Request SHA-256 | Raw output SHA-256 | RF / network / localization outcome | Evidence package |
|---|---|---|---|---|---|
| farm-rf-smoke-v1 | `/home/gusta/.cache/RIOSE/simulation_runs/b29700f6618840d6982891e2f84110f8` | `5b226a661f6a3d7dd9f3d4fb47832279b3bfa9e95734521a4739972c44ad082e` | `5c31de147564cead4497106c194589b13a10f27b5a7a523a21829e53665e0490` | 12 links (9 LOS, 3 NO_PATH); 2 TX, 6 gateway PHY receptions, PDR 1.0; 2 TDoA attempts, 1 converged and 1 failed; conditional RMSE 4,349.93 m | `/tmp/riose-principal-final-evidence-b29700f6618840d6982891e2f84110f8` |
| farm-rf-collision-v1 | `/home/gusta/.cache/RIOSE/simulation_runs/844b357ec4304a338ceb7d73b7b623c5` | `e354f2e654e6483381d95667baafaa35c9b280a524074380cc6eb4958e9da712` | `3a1a90ff1fa0a7ac2da8227abd6013df0e1184b70606354334ab6140ecdfbda1` | 24 links (18 LOS, 6 NO_PATH); 12 INTERFERENCE, PDR 0.0; 4 TDoA attempts, none eligible and no error metrics | `/tmp/testevidence-844` |
| farm-rf-localization-failure-v1 | `/home/gusta/.cache/RIOSE/simulation_runs/db28e7b147164087b31f8b88143b6877` | `634b638480dccb1de1fb1f38fb859bd387852e69409acc6ebc7b884310ed9692` | `b32f856ac4d8f8888436cd735041e77b0a32b27ea9f3ea68c5ee32eadfd6149c` | 12 links; 2 TX, 6 gateway PHY receptions, PDR 1.0; 0 eligible timestamps and 2 failed estimates with null error metrics | `/tmp/testevidence-db28` |

All three manifests record `dirty=false` and the same RIOSE revision. Each
package contains 3 artifacts and verified `valid=true`, schema PASS, hashes
PASS, and `SIMULATED`. The run workspace manifests retain the engine revision,
request binding statuses, and raw-output hash. Temporal detector/clock values
are forwarded and their outputs are hashed/coverage-checked, but are not
independently attested by FREQUENCIA; their effective values remain
unavailable. Localization output must cover every transmitted packet, and
reported eligible/converged counts must match estimate statuses.

The final full suite reports **463 passed, 7 skipped**. One pre-existing
Starlette/httpx deprecation warning remains. These results do not change the
feature audit above: contract and runner are PARTIAL, while the supported
adapter, synthetic RF/network-localization path, and evidence pipeline pass
within their stated limits.
