# Deterministic wake-step fixture

This SIMULATED test stimulus is intentionally not an animal-motion dataset and is not Gazebo-derived. It preserves the Robot case's deterministic expectations: start stationary at (0, 0, 1) g, then step to (0.576, 0.793, 0) g at 12.5 Hz. LIS2DW12 register quantization maps the stimulated X/Y values to the asserted firmware telemetry (575, 793, 0) mg. The first step exceeds the configured 62.5 mg high-pass threshold once; later plateau samples decay below it.

Generate its RESD file with the repository converter:

    python3 hardware/renode/scripts/dataset_to_resd.py WAKE_STEP --manifest hardware/renode/tests/fixtures/wakeup_step/manifest.json --output /tmp/riose-wake-step.resd --renode-home /home/gusta/.local/opt/renode_1.17.0-portable

Pass the result as RIOSE_LIS2DW12_WAKE_RESD to gazebo-bridge.robot. The separate RIOSE_LIS2DW12_GAZEBO_RESD input remains the source for arbitrary RESD register/sample replay.
