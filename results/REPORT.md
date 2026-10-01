# Cattle RF benchmark report

**Evidence: SIMULATED. Not validated on a physical farm.**

- Profile: full
- Scenario count: 24
- Runtime: 89.2 seconds

## Mean localization error by method

| Method | Mean error (m) |
|---|---:|
| gps_oracle_reference | 0.00 |
| strongest_anchor | 300.50 |
| weighted_centroid | 177.48 |
| path_loss | 277.83 |
| extra_trees | 426.35 |
| gradient_boosting | 450.21 |
| temporal_fusion | 168.24 |

## Interpretation and limits

All metrics come from a seeded software model and do not establish field performance. RSSI varies with assumed path loss, shadowing, obstacles, and packet loss. Fingerprint models train on distinct seeds and are evaluated on separate seeds; this still does not prove transfer to a farm.

STM32WLE5 reference configuration; idle/BLE/Wi-Fi/alert currents are assumptions; no battery capacity is configured, so battery life is unavailable.

Cost entries are marked PRICE_RESEARCH_REQUIRED; blank values are not estimates.

GPS appears only as a zero-error oracle computed after inference from isolated truth; it is never passed to an estimator.
Robustness axes: stress_metrics.csv and stress_errors.csv.

Raw data: metrics.csv, localization_errors.csv, energy.csv. CDF: plots/localization_error_cdf.png.
