# Simulation Lab protocol for agents

The Simulation Lab is a research/staging environment. Its outputs are
`SIMULATED`; they do not establish physical, field, deployment, localization,
or regulatory validation.

## Non-negotiable boundaries

- Preserve `SIMULATED != VALIDATED`. Sionna, ns-3, analytic, localization,
  timing, and digital-twin results must never become `VALIDATED` by conversion,
  summary, or packaging.
- `GUZZBR1/frequencia` remains an external engine. Keep the RIOSE boundary at
  versioned contracts and process/files; do not vendor/copy the engine or add
  Sionna, ns-3, openEMS, or other heavy simulation stacks as required RIOSE
  dependencies.
- Use `REUSE -> EXTEND -> CREATE -> REPLACE`. Read the existing contracts,
  runner, adapter, pipeline, tests, and docs before introducing an interface.
- Record RIOSE and engine revisions and dirty states, backend, seed,
  requested/effective parameters, hashes, environment/tool versions, and
  evidence classification. Distinguish values the request asked for from
  values the engine actually consumed; unsupported values must be rejected or
  labeled unsupported with no invented effective value.
- Refuse a dirty `frequencia` checkout by default. An explicitly authorized
  dirty run must record `dirty=true`, its revision, and the override.
- Never fabricate RSSI, SNR, ToF, positions, PDR, or physical validation.
  Leave unknown values null or `NOT_AVAILABLE` and retain failure reasons.
- Ground truth is for post-estimation scoring only. It must not be passed into
  the estimator or substituted for an absent estimate.
- `PHY_RECEIVED` does not mean application/server delivery. Numerical time
  resolution (including 1 ps) does not mean hardware timing accuracy.
- Keep large raw results, generated geometry, caches, and environments out of
  Git unless a small, reviewable artifact is specifically justified.
- Treat future integration with `main` as selective and separately audited.
  Never use destructive Git operations in a worktree that may contain other
  feature work.

## Current request-to-engine binding audit

This table describes the supported `sionna-rt` FARM route at the pinned
`frequencia` revision `ba2bdabf003722aae8292580e048f7092d0356d6`. The exact
generated config, trajectory, ExperimentSpec, raw output, and optional network
artifacts are hashed in each run manifest. The request itself is preserved and
hashed. `NOT_RUN` and `NOT_AVAILABLE` are deliberate outcomes, not defaults.

| Request values | Support and forwarding | Effective value and verification |
| --- | --- | --- |
| backend | `sionna-rt` selects the explicit FARM ExperimentSpec route; there is no analytic fallback | Result backend, engine summary, and manifest must identify Sionna RT |
| seed | Forwarded to FARM scenario config and ExperimentSpec RF settings; when enabled, forwarded again to ns-3 input | Network artifact must echo the seed; generated config/spec/input hashes bind the other stages |
| frequency, bandwidth, TX power | Forwarded to FARM radio config and ExperimentSpec; passed to network input | Sionna summary and ns-3 output are checked against requested values; ns-3 is limited to 915 MHz campaign settings, 125 kHz, and 0–14 dBm |
| tag, animal, device, transmitter, gateway, receiver, anchor IDs | Explicit mappings only; FARM ID conventions are validated before launch | Result IDs and adapter sidecars retain source-to-RIOSE mapping; no inference by coincidental string equality |
| receiver positions | Forwarded as FARM gateway coordinates; gateway elevation is converted from local ENU elevation to height above synthetic terrain | Generated config hash and raw result links; conversion rule and terrain assumptions stay in the manifest |
| tag positions and inline trajectories | Written as the explicit trajectory CSV; initial sample must match request position and all timestamps must be shared/evenly spaced whole seconds | Trajectory SHA and raw link identities/timestamps are checked for completeness |
| `trajectory.reference` | Unsupported by FARM Sionna; rejected before engine setup | No effective value is claimed |
| scenario | Uses the pinned FARM reference config plus the explicit request overrides; unmodeled inventory/material assumptions remain from the base config | Base and generated config hashes, engine scenario metadata, mesh hashes, and materials are recorded |
| Sionna solver settings | `max_depth`, `samples_per_src`, `max_num_paths_per_src`, `cfr_points`, `los`, and `specular_reflection` are forwarded; unknown solver keys are rejected (network/temporal are handled separately) | Effective solver configuration is taken from the engine manifest and tied to generated config/raw-output hashes |
| LoRa spreading factor and payload | Used only when the ns-3 network stage is enabled; supported SF 7–12 and payload 1–51 bytes | ns-3 output is checked against the requested SF and payload; no PHY reception is inferred from a path |
| network interval | Used only when network simulation is enabled | ns-3 packet output is checked against the requested interval and seed |
| detector, clocks, noise, timestamp errors, localization iterations | Validated and forwarded to the existing FREQUENCIA temporal and TDoA APIs; temporal options require an enabled network stage | Network input hash, per-reception timestamp records, localization output, and scoring are retained and hashed |
| `radio.phy` | LoRa technology/SF is checked by the network route; Sionna propagation itself does not simulate LoRa packet PHY. Unsupported technology or inconsistent SF is rejected | When network is disabled, SF/packet settings have no effective value and must not be described as used |
| CIR/CFR and detailed channel arrays | May exist in FREQUENCIA raw artifacts, but are not represented in Simulation Result V1 or canonical RIOSE records | Raw output SHA and external run artifacts preserve provenance; the evidence packager does not copy large raw arrays by default |
| analytic backend | Runs FREQUENCIA's built-in smoke scenario, not a request-specific FARM campaign | Request geometry/radio/seed remain requested only; effective values are unavailable and explicitly described as unsupported by that smoke route |

When engine support or verification changes, update this binding table, the
manifest/report behavior, and focused tests together. Never infer equality
from a request hash alone: a hash identifies the request, not the engine's
effective configuration.

## Evidence interpretation

- Sionna simulation is not field validation; ns-3 simulation is not deployment
  validation; TDoA convergence is not accurate localization.
- A received path, a PHY reception, and application delivery are separate
  events. Preserve them separately, including `NO_PATH`, collision/drop,
  detector rejection, and failed/null estimates.
- A reported simulator resolution is a numerical setting, not physical
  hardware accuracy.
- Verify packages independently. Hashes provide integrity checks for listed
  files, not a cryptographic signature or proof of authenticity against an
  actor able to rewrite the package and manifest.
- Before modifying or committing, inspect the complete worktree and stage only
  understood files. Keep feature commits semantically intact and report
  unrelated local changes without including them.
