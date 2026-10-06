# Dynamic Localization & Fault Injection

All outputs are **SIMULATED**.

- RIOSE source revision: `a844bd6039a5c10d22ee0cc0ed1b866db7a8c1b6`
- Localization V2 source SHA-256: `f30f72b2159b50747c321cb5a19532f13043b6d2a51f1a1c32e9315d097a16cc`
- Cases / seeds / epoch attempts: 28 / 10 / 6720
- Full trace archive: `docs/research/dynamic-localization/results.json.gz` (gzip SHA-256 `38fcaea1ef969bdbe6cde0d87c131f073e292cb8f710e7226cda7504348eb338`; decompressed JSON SHA-256 `e0ef0c32822fc660db35624a3411ca26d756afa155f25f51f9a5720679954c43`). Decompress with `gzip -dc results.json.gz > results.json` before parsing.
- False-position threshold: >10 m (predeclared engineering evaluation threshold)
- Quality gate: Localization V2 numerical status plus declared 0–1000 m operating bounds; GroundTruth is joined after estimation.
- Radio model: analytic 2D LOS geometry with affine clock offsets/drift, seeded jitter, quantization and explicit observation loss.
- Timing resolution is a simulation input; it is not evidence of hardware clock accuracy.

## Per-case metrics

| Case | N | Input avail. | Numerical avail. | Accepted avail. | RMSE m | P95 m | False confidence / accepted | Recovery |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| static_control | 240 | 1.0 | 1.0 | 1.0 | 2.023625806127147e-06 | 2.023625806127147e-06 | 0/240 | — |
| straight_walk | 240 | 1.0 | 1.0 | 1.0 | 1.1303775495425568e-06 | 1.7172178929227498e-06 | 0/240 | — |
| turn | 240 | 1.0 | 1.0 | 1.0 | 1.4066726978089435e-06 | 2.265419840221781e-06 | 0/240 | — |
| stop_and_go | 240 | 1.0 | 1.0 | 1.0 | 1.3567557515001014e-06 | 1.646624964583512e-06 | 0/240 | — |
| curve | 240 | 1.0 | 1.0 | 1.0 | 1.2680094304879078e-06 | 1.7762047048379396e-06 | 0/240 | — |
| boundary_crossing | 240 | 1.0 | 1.0 | 1.0 | 1.332896568471201e-06 | 2.3014694250499507e-06 | 0/240 | — |
| bad_geometry | 240 | 1.0 | 0.2916666666666667 | 0.2916666666666667 | 2.672843296875338e-06 | 4.576690297137818e-06 | 0/70 | — |
| bad_zone_crossing | 240 | 0.7916666666666666 | 0.7916666666666666 | 0.7916666666666666 | 1.1383382098696421e-06 | 1.7137959254154978e-06 | 0/190 | 10/10 sustained recovery; max 0 s |
| anchor_loss_recovery | 240 | 1.0 | 1.0 | 1.0 | 1.4178226746448268e-06 | 2.1239192645794117e-06 | 0/240 | service continued (10/10) |
| two_anchor_loss_recovery | 240 | 0.75 | 0.75 | 0.75 | 1.1826707904862042e-06 | 1.7172178929227498e-06 | 0/180 | 10/10 sustained recovery; max 0 s |
| clock_offset_identity | 240 | 1.0 | 1.0 | 1.0 | 5.61073603468137 | 5.61073603468137 | 0/240 | — |
| clock_drift_corrected | 240 | 1.0 | 1.0 | 1.0 | 0.011551362984158748 | 0.012183632645992268 | 0/240 | — |
| clock_drift_wrong_calibration | 240 | 1.0 | 0.20833333333333334 | 0.20833333333333334 | 11.8416662551166 | 12.159287849809978 | 50/50 | — |
| clock_drift_missing_calibration | 240 | 1.0 | 0.0 | 0.0 | None | None | 0/0 | — |
| clock_drift_stale_calibration | 240 | 1.0 | 0.0 | 0.0 | None | None | 0/0 | — |
| jitter_2ns | 240 | 1.0 | 0.2916666666666667 | 0.2916666666666667 | 2.656012758232017 | 4.357526294595247 | 0/70 | — |
| jitter_10ns | 240 | 1.0 | 0.075 | 0.075 | 16.989974323964457 | 27.835868280206803 | 11/18 | — |
| quantization_1ns | 240 | 1.0 | 1.0 | 1.0 | 0.08121311239330245 | 0.11890720145358054 | 0/240 | — |
| missing_timestamp | 240 | 1.0 | 1.0 | 1.0 | 1.1761252662862461e-06 | 1.7172178929227498e-06 | 0/240 | service continued (10/10) |
| corrupted_timestamp | 240 | 1.0 | 1.0 | 1.0 | 1.1761252617097172e-06 | 1.7172178929227498e-06 | 0/240 | service continued (10/10) |
| stale_timestamp | 240 | 1.0 | 1.0 | 1.0 | 1.174108058314901e-06 | 1.7172178929227498e-06 | 0/240 | service continued (10/10) |
| duplicate_timestamp | 240 | 1.0 | 1.0 | 1.0 | 1.174108058314901e-06 | 1.7172178929227498e-06 | 0/240 | service continued (10/10) |
| packet_loss_25pct | 240 | 0.7458333333333333 | 0.7458333333333333 | 0.7458333333333333 | 1.7692224594607764e-06 | 3.387003668972297e-06 | 0/179 | — |
| burst_packet_loss | 240 | 0.8333333333333334 | 0.8333333333333334 | 0.8333333333333334 | 1.311811588466575e-06 | 1.8137663708358738e-06 | 0/200 | 10/10 sustained recovery; max 0 s |
| move_plus_anchor_loss | 240 | 1.0 | 1.0 | 1.0 | 1.5223530268297123e-06 | 2.271153811401477e-06 | 0/240 | service continued (10/10) |
| bad_geometry_plus_jitter | 240 | 1.0 | 0.0125 | 0.0125 | 123.64031603622631 | 173.35884340384385 | 3/3 | — |
| drift_plus_packet_loss | 240 | 0.7458333333333333 | 0.7458333333333333 | 0.7458333333333333 | 0.023396689224036527 | 0.0404208210635622 | 0/179 | — |
| jitter_plus_recovery | 240 | 1.0 | 0.4375 | 0.4375 | 3.3205766189573906 | 5.961447776758134 | 0/105 | service continued (10/10) |

## Interpretation and limits

Availability denominators include every requested epoch. Every trajectory epoch is GroundTruth-evaluable, but spatial error metrics are conditional on an estimate and report their own denominator. False confidence is bad accepted estimates / accepted estimates. `rejected_good_numerical_point` is limited to returned numerical points rejected by the bounds gate whose offline error is within 10 m; it is not a general false-rejection rate for missing estimates.

The fitted beacon calibration uses synthetic reference times and path-delay-free LOS assumptions. Every fitted calibration remains `UNVERIFIED`; identity is an explicit zero-correction comparator. Convergence and the bounds gate do not establish accuracy.

NLOS, physical clock behavior, RSSI/PHY decoding, transport-layer duplicate identity, and unknown-anchor contract behavior are not modeled by this analytic campaign. FREQUENCIA/Sionna/ns-3 results are not substituted for missing inputs. No physical, field, animal-behavior, or hardware claim is made.
