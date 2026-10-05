# RIOSE Beta claim matrix

All execution records in this campaign are `SIMULATED`. “Allowed” applies only to the narrowly worded claim in the first column.

| Claim | Evidence | Classification | Allowed? | Limitation |
|---|---|---|---|---|
| The RESD-to-Renode tag workflow reads a sensor model | Tag closure report: firmware/Zephyr/Renode ran; raw STATIC and WALK LIS2DW12 values both remained 0 | SIMULATED | Partially | Dataset-value propagation is not demonstrated; no physical tag measurement |
| RF paths and gateway reception are produced by the declared Sionna scene | Archived `network_results.json`, per-gateway events and effective config in 13 runs | SIMULATED | Yes, for these declared synthetic scenes | No calibrated farm materials, field measurements, or general propagation guarantee |
| The system has demonstrated LoRaWAN capacity for livestock deployments | Ten-tag 60 s nominal and two-tag 0.01 s collision scenario | SIMULATED | No, beyond the tested scenario sizes/configurations | Not a capacity sweep; no application/server delivery; 2-tag stress had 0/12 TX packets received by a gateway |
| Localization V2 behavior under declared synthetic faults is characterized | 28 cases, 10 seeds, 6,720 epochs; same-source seed-100 replay | SIMULATED | Yes, for the analytic 2D LOS harness | No physical clock/NLOS/RF validation; wrong calibration produced 50/50 bad accepted estimates in that case |
| Behavior ML identifies real animal behavior | Synthetic fixtures and module tests | EXPERIMENTAL | No | No external measured animal/farm validation or held-out field labels |
| BioSignature detects a biological condition | Offline experimental module | EXPERIMENTAL | No | No biological GroundTruth; it is not diagnostic |
| Health anomaly output is a diagnosis | Synthetic safe-state behavior such as `INVESTIGATE` | EXPERIMENTAL | No | No clinical data; `INVESTIGATE` is advisory only |
| The system detects estrus or improves reproduction outcomes | Reproduction research/demo fixtures | EXPERIMENTAL | No | No paired reproductive dataset or validated endpoint |
| The system detects pregnancy | No pregnancy-specific validated evidence | NOT_EVALUATED | No | No pregnancy labels or clinical validation |
| RIOSE hardware is validated | No physical RIOSE tag measurement in this work | NOT_EVALUATED | No | Simulator output cannot prove hardware behavior |
| RIOSE is field validated | No field deployment/evaluation in this work | NOT_EVALUATED | No | No farm trial or external field ground truth |
| Offline commitment/outbox/receipt integrity checks work in the tested software path | Fake/offline adapter, local receipt and integrity/tamper tests | SIMULATED | Yes, for the offline software demo | No Beta-run REAL_ON_CHAIN publication; chain state would not prove physical truth |
| The software pipeline preserves requested/effective simulator configuration and run provenance | Scenario/request/runtime manifests with SHAs, seeds and artifact hashes | SIMULATED | Yes, for archived executions | Hashes establish content identity, not author identity or physical truth |
| Matching seed and source reproduce synthetic estimator content | Dynamic seed 100: 672 records equal after excluding `runtime_ms`; Beta baseline same-request normalized digest matched | SIMULATED | Yes, within those exact replay scopes | Wall-clock timings vary; other hosts/backends not compared |
| The simulated energy value is measured battery life | Firmware trace integration and assumed-current models | ENGINEERING_ESTIMATE | No | No battery capacity configuration or physical current measurement |
