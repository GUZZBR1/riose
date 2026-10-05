# Simulation Lab Runner — frequencia

The runner provides an explicit process boundary to the independent
`GUZZBR1/frequencia` repository. Its expected engine revision is pinned in
`src/riose/simulation_lab/runner.py` as
`ba2bdabf003722aae8292580e048f7092d0356d6`. It never clones, checks out,
resets, cleans, or writes into that repository. Point `FREQUENCIA_REPO` or
`--repo` at an existing checkout; a different SHA, remote, missing entrypoint,
or dirty checkout blocks execution. `--expected-sha` is an explicit laboratory
pin override, while `--allow-dirty` explicitly opts into local modifications.

## Commands

```bash
python -m riose.simulation_lab doctor --repo /path/to/frequencia
python -m riose.simulation_lab run request.json --repo /path/to/frequencia --dry-run
python -m riose.simulation_lab run request.json --repo /path/to/frequencia
```

The installed `riose-simulation-lab` command has the same subcommands. The
workspace root defaults to the user cache directory (or
`RIOSE_SIMULATION_RUNS`) and each run uses a unique directory containing the
validated request, bounded stdout/stderr logs, manifest, Simulation Result V1,
and adapter output. The analytical smoke outputs remain outside the repository;
the FARM Sionna runner stores raw engine artifacts under the external
`frequencia/results/riose_simulation_lab/` directory and leaves those files
ignored by the local repository.

The doctor reports Python, analytic, Sionna RT, ns-3, LoRaWAN integration code,
and GPU availability separately. ns-3 capability is checked at
`FREQUENCIA_NS3_ROOT` or `~/.local/share/frequencia/ns-3.48`, including its
compiled LoRaWAN library; it does not depend on `ns3` being on `PATH`.
Capability presence is not evidence that a particular run used that capability. Sionna runs use the configured external
`frequencia/.venv-sionna-agent1` Python; missing Sionna or that environment
fails explicitly without switching backend.

## Current MVP scope

The analytic entrypoint
`experiments/farm_rf/run_experiment.py --backend analytic --output-dir ...`
remains available for analytic requests. FARM Sionna requests use the separate
upstream ExperimentSpec runner described below. Neither path silently changes
the requested backend; both retain `SIMULATED` evidence.

The process boundary has a timeout, per-stream log cap, structured failures,
explicit working directory, and `shell=False`. Nonzero exit, missing/malformed
summary, timeout, or excessive output fails the run. For Sionna output, the
runner does not alter tracked engine source; it writes under the external
results directory and appends one narrow local ignore rule to
`.git/info/exclude` so the generated raw artifacts stay out of normal Git
tracking.

## FARM Sionna RT request campaign

`backend: "sionna-rt"` dispatches to the existing `hub.run` ExperimentSpec
path and `scripts/run_farm_sionna_experiment.py`; it does not use the analytic
smoke entrypoint. A request's explicit tag, animal, device, gateway, receiver,
and anchor mappings are checked against FARM's supported IDs. The trajectory,
radio settings, solver parameters, and gateway positions become a compact
upstream config/spec/CSV. The runner validates FARM status, frame, complete
link count, `NO_PATH` consistency, required raw/metrics/summary/manifest
artifacts, and backend identity before building the V1 result.

When `solver.parameters.network.enabled` is true, the runner passes actual
Sionna paths, power, transmitter positions, and gateway positions to
FREQUENCIA's existing `network.adapter` and compiled ns-3/LoRaWAN adapter. It
then uses upstream `temporal.detectors`, `temporal.clock`, `temporal.phy`, and
`localization.network_pipeline`; RIOSE only adapts the artifacts and performs
the explicitly separate score pass. GroundTruth is not an argument to the
estimator. The request currently supports upstream's single 125 kHz channel,
SF 7–12, 0–14 dBm, payload 1–51 bytes, and explicit frequency/seed/interval.
These are simulation inputs, not a certified Brazilian regional plan. Coding
rate is not exposed by this adapter and is not claimed as configured.

`network.traffic_interval_s` may be `null` for an exact source-timestamp
schedule. This synchronizes tags that share a trajectory timestamp. A positive
value requests a deterministic, seed-derived per-tag phase within that window;
the offset is reused at every epoch, so it models a fixed periodic phase and
does not add per-packet jitter. Neither mode models application retries.

The network result distinguishes `NOT_TRANSMITTED`, `NO_PATH`, `INTERFERENCE`,
`UNDER_SENSITIVITY`, `NO_DEMODULATOR`, `UNTRACED_DROP`, and `RX` outcomes as
reported by ns-3. `RX` means gateway PHY reception; no LoRaWAN server/application
delivery is modeled. Packet PDR is delivered packets divided by packets with a
transmission start; gateway event counts and causes remain visible separately.
The summary's `drops` counts only the network's interference, sensitivity,
demodulator, and untraced drop outcomes; `NO_PATH` and `NOT_TRANSMITTED` have
separate counts.
No transmission yields a null PDR, and disabling the network leaves all network
metrics null. A path can exist while a packet is lost. The summary reports
packet-level PDR, gateway receptions/drops/collisions, plus TDoA attempt,
eligibility, convergence, and conditional error metrics together.

Detector mode, clock offset/drift/jitter/quantization, correlated jitter,
timestamp error, noise, and thresholds are present with explicit units in the
request and run manifest. Timestamp outputs are labeled
`SIMULATED_CLOCK_TIMESTAMP_MODEL`; ns-3's 1 ps numerical resolution is recorded
as a simulator setting and never described as hardware precision. FREQUENCIA's
2D TDoA output is ENU east/north only. A failed or under-observed solve maps to
an Estimate with a null position and its upstream failure status, never a
fabricated coordinate. Canonical observations preserve RF path/power separately
from PHY reception, and keep simulated received power distinct from physical
RSSI. Network, timestamps, localization, scoring, and their hashes are stored
in the run workspace manifest/artifacts. Each completed run also writes a
human-readable `summary.md` beside its JSON result, scoring, network, temporal,
and provenance files. Generated raw RF output remains in the external ignored
FREQUENCIA results directory.

All artifacts remain `SIMULATED`. The upstream terrain/shed meshes, omitted
FARM inventory, isotropic antennas, uncalibrated materials, the timestamp
detector assumptions, and the absence of server delivery/physical calibration
are limitations, not evidence of field performance. A locally dirty engine
checkout requires the explicit `--allow-dirty` flag and is recorded in the
manifest.

## Small network/localization scenarios

Three compact requests make the observability changes repeatable:

- `examples/farm_rf_v1.json` is the baseline. The recorded run produced a
  packet PDR of 1.0, six gateway PHY receptions, two TDoA attempts, one
  convergence and one failure. Its conditional RMSE was 4,349.93 m, so the
  convergence is not an accuracy claim.
- `examples/farm_rf_collision_v1.json` has two devices and a 10 ms seeded
  traffic phase interval. The recorded run produced 4 transmitted packets,
  12 `INTERFERENCE` gateway outcomes and PDR 0.0. It uses ns-3's simulated
  collisions rather than a hand-authored loss count.
- `examples/farm_rf_localization_failure_v1.json` keeps the baseline network
  but sets the absolute path detector threshold to 0 dBm. This explicit,
  deliberately severe detector setting yielded six PHY receptions but no
  eligible TDoA timestamps; all localization attempts failed with null
  positions and null conditional error.

Run any request with the command shown above. FREQUENCIA FARM V1 currently
requires 3–8 configured gateways, so its end-to-end runner cannot launch a
two-gateway campaign. The upstream localization API and RIOSE result adapter
are separately tested for fewer than three observations and return
`LT3_TIMESTAMPS` with a null position. No gateway count is silently padded.
