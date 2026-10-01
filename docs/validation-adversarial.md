# Adversarial validation notes

These are software and CPU simulation checks. **All RF, position, delivery,
and energy figures below are SIMULATED; none are field validation.**

## Smoke benchmark

Command: `cattle-rf benchmark --profile quick --animals 1 --anchors 4 --duration 60`

Observed output: one scenario, six method rows, twelve recorded localization
errors, about 0.7 seconds runtime using the project's installed virtualenv.
Packet delivery ratio was 0.875. Mean error was 766.7 m for strongest-anchor,
286.9 m for weighted centroid, 142.5 m for path-loss inversion, 631.0 m for
Extra Trees, 640.3 m for Gradient Boosting, and 328.4 m for temporal fusion.
The configured assumed energy profile yielded 1.009 mAh/tag/day; battery life
was unavailable because capacity was not configured. These are single-run
smoke numbers, not comparative performance claims.

## Adversarial checks and current limits

- Tests ensure RF observation contracts and serialized feature CSVs omit
  coordinates, while ground truth remains in a separate file.
- Tests exercise seeded packet loss, forced NLOS attenuation, a missing or
  corrupt anchor measurement, controlled stationary movement, hash-chain
  tampering, CSV serialization, and the dashboard's default/debug truth split.
- A per-anchor clock drift regression applies offsets from -250 ms to +250 ms
  and expects one full-quality estimate that still matches the truth epoch.
  The current exact-timestamp grouping fragments the epoch; this test is
  expected to pass after bounded timestamp clustering is integrated.
- The energy ledger regression expects elapsed ledger time to equal wall time.
  A 60 s normal tag step currently records 60.3 s because the full base-state
  interval is counted before the separately accounted 0.1 s TX and 0.2 s RX.
  The test is expected to pass after energy intervals are made non-overlapping.
- With the project's virtualenv, the API truth-gating test passed. The suite
  reported 28 passing and 2 failing regression checks for the clock-drift and
  energy-accounting issues above. FastAPI and scikit-learn tests skip under a
  system Python where those dependencies are absent; run `./setup.sh` before
  full local validation.
