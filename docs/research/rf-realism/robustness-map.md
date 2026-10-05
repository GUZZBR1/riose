# Simulated RF robustness map

Classification concerns only the named model/configuration and the engineering threshold. It is not a statement about a real property, hardware, or field performance.

| Condition | Analytic | Sionna RT | RF observability result | Risk / confidence | Limitation |
|---|---|---|---|---|---|
| Open, clear LOS control | `ROBUST_SIMULATED` | `ROBUST_SIMULATED` | 4/4 links each have paths and exceed the −127 dBm engineering assumption | Medium confidence for code behavior | Fixed isotropic/scalar antenna; no receiver detection model |
| 5–1000 m distance sweep | `ROBUST_SIMULATED` at threshold; received power falls with distance | Same | 8/8 matched links each; 1 km powers −80.73 / −85.75 dBm, still 46.27 / 41.25 dB over threshold | Medium confidence for model response | Not a measured range or sensitivity result; far links are path-loss-only assumptions |
| TX/RX height combinations | `ROBUST_SIMULATED` | `ROBUST_SIMULATED` | 9/9 links each; changing height shifts modeled power by several dB | Medium | Assumed heights; no ear-tag placement evidence |
| Six gateway layouts × 9 sample positions | `ROBUST_SIMULATED` | `ROBUST_SIMULATED` | 9/9 positions per layout have ≥1 link above threshold; all 216 link records per backend had paths | Medium for synthetic geometry only | Sparse grid, no surveyed property; threshold is lenient engineering assumption |
| Seeded 30-position Monte Carlo | `ROBUST_SIMULATED` | `ROBUST_SIMULATED` | Analytic 30/30 links; Sionna 90/90 gateway links; all exceed threshold | Medium for deterministic position sampling | No random fading, shadowing, or stochastic materials; Sionna solver is deterministic |
| Flat LOS with ground reflection | `ROBUST_SIMULATED` | `ROBUST_SIMULATED` | Two components in control; Sionna path power differs by model | Medium | Analytic reflection coefficient −0.35 is uncalibrated; Sionna uses configured material proxy |
| Reflection-only solver control | `NOT_TESTED` as environmental NLOS | `DEGRADED_SIMULATED` (one reflection path, NLOS status) | 4/4 Sionna links have reflected path | Low for field interpretation | LOS path was disabled by solver setting; explicitly NOT geometry-produced NLOS |
| Direct path crossing synthetic wall | `MODEL_DISAGREEMENT` | `OUTAGE_SIMULATED` | Analytic ignores the wall and returns paths on 3/3 links; Sionna returns `NO_PATH` for 3/3 geometrically blocked links | Medium for this exact synthetic mesh | No successful received NLOS path; no diffraction; wall is a proxy |
| Synthetic terrain relief | `NOT_TESTED` (analytic has no terrain) | `MIXED_SIMULATED`: 2 LOS, 1 `NO_PATH` | 2/3 relief links have paths, 1/3 no path; flat control 3/3 LOS | Low to medium | Procedural unsurveyed relief; endpoint heights follow the same synthetic surface |
| Vegetation / pasture / fences | `NOT_TESTED` | `NOT_TESTED` | No path observability result | None | Metadata only; not ray-traced or assigned RF materials |
| Tag yaw/pitch/roll or polarization rotation | `NOT_TESTED` | `NOT_TESTED` | No orientation response can be inferred | None | Fixed isotropic 1×1 array; no pose interface |
| Paired analytic × Sionna links | `MODEL_DISAGREEMENT` | `MODEL_DISAGREEMENT` | 267 pairs; Sionna−analytic mean −1.86 dB, P10 −4.66 dB, P50 −1.46 dB, P90 +1.53 dB | Medium for difference under matched code/config | Neither backend is truth; RF power definitions and propagation implementations differ |

## Interpretation

In these idealized model cases, available LOS links stay well above the declared engineering threshold out to 1 km and throughout the synthetic geometry samples. The model's visible degradation is a decreasing received-power trend with distance, model disagreement, and the `NO_PATH` outcomes in the wall/relief tests. That does not establish a usable 1 km radio range: the campaign has no calibrated antenna, receiver sensitivity, LoRa demodulator, or field measurements.

`NO_PATH` means the configured ray solver found no path. It is not a transmitter-off event, a receiver miss, or a simulation failure. The three wall results and the one relief result retain null power and are not assigned a numeric floor.
