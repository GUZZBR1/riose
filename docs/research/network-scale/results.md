# Simulated network scale campaign

**Status: PARTIAL — reproducible PHY-level capacity evidence; application delivery, gateway failure/recovery, and calibrated deployment capacity are not modeled.**

## Scope and provenance

The campaign exercised the Simulation Lab adapter against FREQUENCIA's Sionna RT 2.2.0 CPU channel and ns-3 3.48 / LoRaWAN module v0.3.7. It used a synthetic uniform FARM field, 3–8 corner/midpoint gateways, one 125 kHz channel, SF7–12, 0–14 dBm, and 1–51 byte payloads. Positions, channel/material parameters, and antenna assumptions are not field calibrated. Results are simulated evidence, not deployment or product claims.

The RIOSE worktree is based on Simulation Lab commit `2c9c477` (the lab branch is derived from the research checkout, not the upstream mainline). The run source commits were `722805fdd75fffa09a0bd221788d5bcb867d1abc` for the first campaign and `4b555ea5c1eb98cfc8179a2fa839ccf0ae725800` for the refinement. FREQUENCIA was pinned to clean commit `ba2bdabf003722aae8292580e048f7092d0356d6` for every run. The campaign ledgers record per-run source state and hashes.

Campaign ledger SHA-256 values:

| Ledger | Requested rows | Unique requests | Completed | Failed | Canonical spec SHA-256 |
|---|---:|---:|---:|---:|---|
| Initial | 34 | 31 | 34 (including 3 deduplicated references) | 0 | `1eb8f8e2e23450a338bbf5d3b7ad7295454ef83ad3248243402850cc717b6a8f` |
| Refinement | 9 | 9 | 9 | 0 | `b6d10294c96d19c6bf7c0c145e8de011c78bd73f2c61ac79d8bf40306e892da4` |

The ledger hashes and evidence inputs are consolidated per configuration and per run in [capacity-envelope.json](capacity-envelope.json). The original C envelope covers 40 unique configurations/runs, 43 requested rows, and 0 failed unique runs. C.1 adds a 2-row pilot ledger, a 27-row/24-unique exploratory controlled ledger (including invalid 1-second rows), and an 18-row/18-unique corrected population ledger. The current consolidated envelope contains 78 unique runs, 90 requested rows, and 0 failed unique runs; seeds are 20261005–20261009. Its grouped labels are reporting bins only and must be interpreted with schedule completion and the C.1 exclusions. The original C-only packet/runtime totals above describe only those 40 original unique runs.

## Metric definitions

- **PHY PDR:** unique packet IDs received by at least one gateway divided by packets with TX start. Each rate below includes its numerator and denominator.
- **Localization input availability:** TX-start packet epochs with at least three distinct non-null detector/clock timestamps divided by TX-start packets. This counts eligible input epochs, not a successful or accurate location estimate.
- **Latency:** gateway PHY RX-end timestamp minus TX-start timestamp for received packets. This excludes application queues, network-server delivery, and end-device behavior.
- **Gateway outcome events:** per-gateway PHY outcomes; one packet can contribute several gateway events. They are not packet-level loss counts.
- **Analysis labels:** `ROBUST_SIMULATED` means mean PDR ≥0.95; `DEGRADED_SIMULATED` means 0.70≤PDR<0.95; `OVERLOADED_SIMULATED` means 0<PDR<0.70; zero PDR is outage. These are reporting bins only, not acceptance requirements.

## Results

### Population sweep — four gateways, SF7, 12 B, 60 s cadence

| Tags | TX / RX | Mean PHY PDR | Localization input availability | Notes |
|---:|---:|---:|---:|---|
| 1 | 3 / 3 | 1.000 | 1.000 | One run |
| 5 | 15 / 15 | 1.000 | 0.600 | One run |
| 10 | 30 / 30 | 1.000 | 0.700 | One run |
| 17 | 153 / 153 | 1.000 | 0.706 | Three seeds |
| 18 | 162 / 153 | 0.944 | 0.667 | Three seeds |
| 19 | 171 / 162 | 0.947 | 0.632 | Three seeds |
| 20 | 300 / 270 | 0.900 | 0.600 | Five seeds |
| 50 | 750 / 669 | 0.892 | 0.536 mean (sample SD 0.030) | Five seeds; PDR sample SD 0.011, range 0.880–0.900 |
| 100 | 1,500 / 1,321 | 0.881 | 0.485 mean | Five seeds; PDR sample SD 0.013, range 0.867–0.900 |

The refined 17→18-tag transition crosses the report's 95% bin, but it does **not** establish a collision-limited capacity boundary: there were no interference events at 17, 18, or 19 tags, and the lost packets were `NO_PATH`. In the 20-tag seed 20261005 run, two tags (animal-018 and animal-020) had only `NO_PATH` outcomes. At 50 and 100 tags, interference appears (79 and 235 gateway events across five runs respectively), alongside the baseline RF path ceiling. Thus 17 tags is not a supported capacity claim.

### Cadence — 20 tags, four gateways, SF7, 12 B

| Cadence | TX / RX | PHY PDR | Interference gateway events | Localization input availability |
|---:|---:|---:|---:|---:|
| 1 s | 60 / 45 | 0.750 | 52 | 0.100 |
| 10 s | 60 / 51 | 0.850 | 12 | 0.550 |
| 60 s | 60 / 54 | 0.900 | 0 | 0.600 |
| 300 s | 60 / 54 | 0.900 | 0 | 0.600 |

The 1-second case also reported 26 packet IDs with at least one interference event; the 10-second case reported six. The stable 60/300-second outcomes and the 17–19-tag losses show the importance of separating RF path loss from contention.

### Gateway count — 20 tags, 60 s, SF7, 12 B

| Gateways | TX / RX | PHY PDR | Localization input availability |
|---:|---:|---:|---:|
| 3 | 60 / 54 | 0.900 | 0.300 |
| 4 | 60 / 54 | 0.900 | 0.600 |
| 6 | 60 / 54 | 0.900 | 0.850 |
| 8 | 60 / 54 | 0.900 | 0.900 |

For this geometry, more gateways increased the availability of multi-anchor input epochs but did not change packet PDR. This is not a gateway-outage or placement optimization study.

### Synchronization — 20 tags, four gateways, 60 s period, SF7, 12 B

| Schedule | TX / RX | PHY PDR | Interference gateway events | Localization input availability |
|---|---:|---:|---:|---:|
| Exact source timestamps | 60 / 3 | 0.050 | 93 | 0.000 |
| Deterministic per-tag phases within 10 ms | 60 / 3 | 0.050 | 93 | 0.000 |

The simulated TX airtime is 56.576 ms, longer than the 10 ms phase window. Both schedules therefore create heavily overlapping bursts. Positive-cadence phases are deterministic per tag and reused at every epoch; the model does not add per-packet phase jitter.

### Payload and spreading factor — 20 tags, four gateways, 10 s cadence

| Dimension | Value | TX / RX | PHY PDR | Modeled airtime per TX |
|---|---:|---:|---:|---:|
| Payload | 1 B | 60 / 51 | 0.850 | 41.216 ms |
| Payload | 12 B | 60 / 51 | 0.850 | 56.576 ms |
| Payload | 24 B | 60 / 51 | 0.850 | 71.936 ms |
| Payload | 51 B | 60 / 50 | 0.833 | 112.896 ms |
| SF | 7 | 60 / 51 | 0.850 | 56.576 ms |
| SF | 9 | 60 / 49 | 0.817 | 185.344 ms |
| SF | 12 | 60 / 31 | 0.517 | 1.482752 s |

The SF12 case had 115 interference gateway events out of 240 gateway outcomes (47.9%). This modeled comparison is not a physical range or field-coverage finding.

## Failures, recovery, and application behavior

The runner distinguishes `NO_PATH`, `UNDER_SENSITIVITY`, `INTERFERENCE`, `NO_DEMODULATOR`, and `NOT_TRANSMITTED` PHY outcomes. `NO_PATH` means the channel model did not supply a receivable path; it is not evidence that a gateway was offline. No explicit gateway outage/availability/recovery timeline, duty-cycle enforcement, retransmissions, ADR, downlink, application/network-server delivery, packet ordering/duplication handling, or independent non-LoRa interferer is modeled. The external adapter uses an unrestricted synthetic sub-band. **Application delivery must be treated as `APPLICATION_DELIVERY_NOT_MODELED`.**

## Red-team findings and residual evidence gaps

The independent review confirmed that the key PDR denominator and multi-gateway PHY outcomes are retained, and the campaign envelope includes raw-output, request, manifest, and network-artifact hashes per run. This closes the earlier evidence packager gap for these campaign results. The wrapper also records failed requests in its ledger; this campaign had no failures.

Residual risks remain: (1) the FREQUENCIA manifest does not independently attest that every Sionna input was consumed; (2) an upstream runner failure before workspace allocation may not produce an upstream failure manifest, though the outer campaign ledger records its failed request; and (3) localization eligibility reported by the adapter relies on estimator/status fields. The campaign's availability numerator is independently recomputed from distinct non-null detector/clock timestamps, which reduces but does not eliminate contract risk. Do not treat these artifacts as attestation of physical inputs or location accuracy.

## Verification

The focused Simulation Lab tests passed 59 tests before the final report/aggregation edits. The final full-suite regression passed using the Simulation Lab virtual environment.

| Check | Result |
|---|---|
| Unique simulations | 40 completed, 0 failed |
| Campaign envelope evidence blocks | 40, with request/manifest/raw/network hashes |
| Full repository test suite | 470 passed, 7 skipped; one existing Starlette/httpx deprecation warning |
| Compile / diff hygiene | `compileall` succeeded; `git diff --check` clean; capacity envelope parsed and validated (40/40 unique runs, 0 failures, 22 groups, 40 per-run evidence records) |

## C.1 contention and capacity closure follow-up

**Status: PARTIAL_SIMULATED.** C.1 makes the earlier contention gap reproducible, but does not establish a generic animal-count ceiling or a robust operating region. The original C evidence remains intact. The initial C.1 ledger contains 27 requested rows, 24 unique requests, 27 completed rows, and zero runner failures; it includes three deduplicated references. Its ledger SHA-256 is `fe8765fb05da03b66155ec8657871d3efa089ae055d4518a27959f81261a2330` and spec SHA-256 is `e312ebab8118a90fadb9b46298f12a3289fe637d2bb2b941cfe05a29e8e0ed43`. Every executed run reports verified network parameter binding and stores request, raw output, network output, source revisions, and dirty state.

### Controlled schedule comparison

The new synthetic control places ten tags at the same already exercised RF point `[120, 200, 10.78] m`, with four gateways, 915 MHz, 125 kHz, SF7, 12-byte payload, 14 dBm, and ten common epochs. Each run requested and transmitted 100 packets; every packet had a modeled RF path to at least one gateway. Across three seeds, exact common timestamps and the 10 ms near-synchronized schedule each delivered 0/100 packets per seed (0/300 pooled), with interference observed at packet level for 80/100 and the remaining 20 classified `NO_DEMODULATOR` per seed. The deterministic per-device phase schedule delivered 100/100, 80/100, and 100/100 (280/300 pooled); only the seed with 80/100 had 20 packet-level interference losses. Since geometry, cadence, radio configuration, and RF reachability were held constant, this demonstrates schedule-dependent PHY outcomes for this artificial co-located topology. The 10 ms phase window remains shorter than the 56.576 ms airtime. Three phase seeds and ten repeated epochs are narrow evidence, not a validated real-world capacity boundary.

### Invalidated 1-second schedule evidence

The initial C.1 1-second rows must not be used to estimate capacity or PDR by source event. The adapter queues source event indices and the pinned FREQUENCIA `TxStart` trace consumes them FIFO; ns-3 can defer or cancel queued MAC transmissions when the channel is busy. The red-team audit compared requested phase timestamps with actual TX starts and found source/event identity mismatches in all nine unique 1-second executions (315 mismatched transmitted packet/event associations in total). In one 10-tag example only 40/100 requested packets started, and the start for source epoch 3 was attributed to an earlier event. Thus the reported TX-start PDR may be arithmetically consistent but the packet identity and delay attribution are not. We preserve these runs as an adapter-fidelity finding and exclude them from all capacity conclusions. The adapter bug is upstream of this RIOSE checkout and was not changed here.

For any schedule, report both **PHY PDR = received / packets with TX start** and **schedule completion = TX starts / requested packets**. C.1 records requested-vs-effective settings and actual TX times; the follow-up also corrects the distinct-TX-start count to count distinct timestamps. A successful PHY PDR conditional on transmitted packets must not hide requests that never reached a TX start.

### Cadence, gateway, and support boundaries

The initial 60-second ten-tag control delivered 100/100 packets for each of three seeds. Its 3-gateway static-omission counterpart also delivered 100/100 per seed, with the same first-three-gateway RF link records as the 4-gateway case. Localization input availability was 1.0 with four gateways and 0.0 with three in this co-located geometry. This is only static removal of gateway four; it does not test outage detection, temporal failure, recovery, or deployment availability.

A corrected population/cadence sweep is retained in a separate ledger. All requests had TX starts and all actual starts matched the pinned seeded-phase formula within 1 ns. At 10-second cadence the 5-tag group received 150/150, 10 tags received 280/300 (20 interference losses), and 20 tags received 490/600 (110 interference losses). At 60-second cadence all groups received every transmitted packet: 5 tags 150/150, 10 tags 300/300, and 20 tags 600/600. The 20-tag 10-second group spans 0.75–0.90 across its three seeds; three seeds are too few to identify a stable overload boundary. These are conditional results for the co-located synthetic topology, not an animal-support number.

Within the corrected tested grid, the largest tested robust configuration was 20 tags at 60-second cadence (600/600 PHY receptions over three seeds). The tested overloaded configurations were the deliberate 10-tag exact-synchronous and 10 ms near-synchronous bursts at 10-second cadence (0/300 PHY receptions each); 20 tags at 10 seconds remained in the reporting `DEGRADED_SIMULATED` range, not the overloaded range. No interpolation between those schedules or loads is justified. The result is therefore a conditional simulated envelope, not a product/deployment capacity limit.

The LoRaWAN module implements duty-cycle scheduling, but the adapter's effective sub-band duty cycle is 100%; duty-cycle limits and their deferrals are therefore `NOT_MODELED`. Per-packet jitter and bursty traffic are not representable by the current shared trajectory timestamp contract. The campaign models gateway PHY reception only: `APPLICATION_DELIVERY=NOT_MODELED`. Localization is input availability only and does not imply localization accuracy. No animal-support claim is made.

The external adapter deletes its temporary input TSV after execution, so a standalone serialized ns-3 scheduled-event file is not retained despite the initial spec wording. Requests, trajectory/configuration hashes, deterministic phase formula, and actual TX starts remain available to reconstruct and audit the intended schedule; this is a provenance limitation rather than missing PHY outcome data.

The reviewer also caught and corrected a reporting bug: synchronized source timestamps can yield fewer distinct TX-start timestamps than TX packets, so `unique_ns3_tx_start_count` now counts unique timestamp values. This value is descriptive only; it is not a count of packet IDs.

### C.1 verification

Focused network regression: 42 passed. Full repository suite: 482 passed, 7 skipped, with one pre-existing Starlette/httpx deprecation warning. `compileall` and `git diff --check` passed. The corrected sweep has 18 requests, 18 unique executions, 18 completions, and zero failures. Its final ledger SHA-256 is `2e67956d79c4bc64b2488b31edd2d17a3339d88fbcd1e4aba826ca1f49b100ac`; spec SHA-256 is `686ce00e48042db42a69c560b6440f641ad835353209f5be5292e5add49ae297`. Every run used clean RIOSE `5510ecaad300e53ff2e5fcc1c195c4b5ea02cb74` and clean FREQUENCIA `ba2bdabf003722aae8292580e048f7092d0356d6`. Independent schedule audit: 2,100 transmitted packet starts, zero mismatches above 1 ns, maximum absolute deviation 5.12e-13 seconds.

