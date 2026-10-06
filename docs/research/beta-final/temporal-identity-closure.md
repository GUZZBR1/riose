# H.2 Temporal Identity and Cadence Closure

## Verdict

**PASS_SIMULATED** for the H.2 temporal identity and cadence scope. The overall Beta Completion Gate remains **PARTIAL / not ready** because independent A–G readiness constraints remain; this closure updates H integration evidence only.

## Cause found

H.1 used 0/1/2 second trajectory epochs while configuring `traffic_interval_s=60`. In FREQUENCIA, that value controls a deterministic per-device phase window; the trajectory timestamps determine source cadence. The previous C++ adapter scheduled the source timestamp instead of the phase-adjusted schedule value, and attributed `TxStart` events through a FIFO queue. LoRaWAN Class A can defer a busy send by five seconds and cancel/replace that pending send when the next request arrives. With requests at 0, 1, and 2 seconds, request 1 may be replaced by request 2 while FIFO attribution labels the actual PHY packet with the wrong source identity. H.1's 86/129 attributed TX and 43 `NOT_TRANSMITTED` counts were internally consistent but did not establish per-request truth. The historical archive cannot be repaired retroactively.

## Changes

- FREQUENCIA commit `0190048023269da695c84d0ff5e1cf3c6ed502d7` attaches a serialized event identity tag to each packet and resolves `TxStart` from that tag. MAC-replaced requests retain a terminal drop reason. C++ schedules the declared phase-adjusted timestamp.
- RIOSE commit `75dc4689aa66ee3dc97675f90f5d845d4d184098` added stable request IDs and sequence numbers through request, network output, estimator, localization scoring, and event validation. `9ae9ee1bf83eb910cdfce9b25e136adcf89f7e99` corrected the gateway timestamp join to use `request_id`. `a3c5f50a6f656797bc9db9e5354805b74f00237a` bound every gateway outcome and clock row to packet identity and TX status. `2e5d5d92a6552f2cf6cfdba9e6566ac0e3d8aac9` carries requested/scheduled/actual times and PHY UID into clock records.
- TX validation allows the declared 1 ps ns-3 time resolution in either direction. `traffic_interval_s` is reported as the seeded phase-window width; each animal's source cadence comes from request trajectory timestamps.
- Added a two-animal, two-event-per-animal campaign with one predeclared seed and retained source/network/scoring/timestamp artifacts.

## Closure evidence

The campaign ran against clean RIOSE `2e5d5d92a6552f2cf6cfdba9e6566ac0e3d8aac9` and clean FREQUENCIA `0190048023269da695c84d0ff5e1cf3c6ed502d7`, with Sionna RT 2.2.0 and ns-3.48/LoRaWAN v0.3.7. It completed as `SIMULATED`:

- Requests: 4; observed transmissions: 4; untransmitted requests: 0.
- Each tag's source timestamps differ by 60 seconds; actual TX start gaps are 59.99999999999999 and 60.0 seconds.
- The machine-readable per-event record is `runs/temporal-identity-closure/closure-results.json`. It binds request/packet ID, sequence, tag/device/transmitter/animal identity, source/requested/scheduled/actual times, PHY UID, gateway outcomes, and clock-row counts. Request, packet, event, and clock identities are validated by the runner.
- Network conservation: requested = transmitted + not transmitted = 4. Each gateway row is bound to the matching packet, `NOT_TRANSMITTED` cannot have RX, and delivered packets cannot exceed transmitted packets.
- The estimator receives no ground truth. Scoring remains a separate post-estimation step. This run produced four attempts, one accepted score, and three `NOT_EVALUATED` estimates; these are synthetic results.
- Campaign manifest canonical digest: `b45b11618bab06faad2f283900836098a0df8acc24aba30fd648f9bda9b57352`. Its archived file SHA-256 and all component artifact hashes are recorded in `closure-results.json`.

Four failed attempts are retained under `runs/temporal-identity-closure/attempts/`. The first lacked a visible Sionna virtual environment in the isolated checkout. Subsequent attempts exposed and closed the stale event-index timestamp join, strict cross-artifact identity gaps, and missing timing fields in clock records. The final run is the successful single-run campaign manifest; prior failures remain visible as development attempts, not part of its scheduled-run denominator.

## Verification

- FREQUENCIA: `network/test_adapter.py` — 11 passed; includes the adversarial 0/1/2 second Class A deferred/replaced request case, verifying request 1's terminal drop and request 2's actual TX identity.
- RIOSE focused tests: 84 passed after the final validator and clock-field changes.
- Full RIOSE suite after the final code commit: 897 passed, 7 skipped; one existing Starlette/httpx deprecation warning.
- Final campaign: 1 scheduled, 1 completed, 0 failed.
- Independent red-team: no remaining blockers; verified source identity, impossible RX rejection, timestamp-row identity, archived artifact hashes, and 60-second cadence.

## Limits and gate readiness

This is a one-seed, two-animal software simulation, not hardware or field validation. It establishes no application-server delivery, field-calibrated radio performance, cross-seed reproducibility, or large-population capacity. H.1's pooled counts remain historical and unverified for per-event identity. The overall Beta Completion Gate remains not ready due to independent A–G limitations. No A–G source was edited.
