# Deterministic wake-step fixture

This SIMULATED test stimulus is not an animal-motion dataset and is not
Gazebo-derived. It starts stationary at (0, 0, 1) g, then steps to
(0.576, 0.793, 0) g at 12.5 Hz. The modeled LIS2DW12 quantization maps the
stimulated X/Y values to the asserted telemetry values (575, 793, 0) mg. The
step crosses the configured approximate high-pass threshold once. This only
checks firmware behavior under the Renode model; it does not validate the
physical sensor or its comparator.

Generate a RESD file with the repository converter:

```sh
python3 hardware/renode/scripts/dataset_to_resd.py WAKE_STEP \
  --manifest hardware/renode/tests/fixtures/wakeup_step/manifest.json \
  --output /tmp/riose-wake-step.resd
```

Pass the result as `RIOSE_LIS2DW12_WAKE_RESD` to `gazebo-bridge.robot`.
