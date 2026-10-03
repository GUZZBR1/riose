# RIOSE MVP 2 antenna experiments

Run headlessly from the repository root:

```sh
python -m hardware.antenna.run --spec hardware/spec.yaml --output results/mvp2/antenna
# Add deterministic one-factor sweeps for material, wall thickness, feed gap,
# and assumed animal orientation:
python -m hardware.antenna.run --spec hardware/spec.yaml --output results/mvp2/antenna --sweeps
```

The command builds CSXCAD primitives from `hardware/spec.yaml`, then runs
openEMS headlessly. It writes `antenna_experiments.json` and `antenna.csv` with
the five scenario IDs: free space, PCB, battery, enclosure, and experimental
animal proximity. S11 curves and far-field patterns are included in JSON and
saved as per-run CSV artifacts. `--sweeps` adds `sweeps.csv` and per-case solver
artifacts. A subset run cannot mark the full experiment `COMPLETED`.

The consumed geometry and material records are marked `ASSUMED` unless the
spec says otherwise; `MEASURED` is rejected for MVP 2. The provisional battery
layout is kept clear of the PCB envelope, but remains an assumed placement that
requires mechanical review. Invalid sweep geometry is recorded per case as
`INVALID_INPUT` while other cases continue. The animal case is an assumed
homogeneous dielectric sensitivity approximation, not tissue validation. A
completed solver run records the input/spec/geometry
hashes, solver version, mesh lines and hash, openEMS time-domain energy
convergence statistics, and hashes of the result artifacts. Mesh refinement
convergence is not run and remains an explicit limitation; cell resolution
and time-domain convergence are not interchangeable.

The runner requires the native openEMS executable and Python bindings for
CSXCAD/openEMS. Missing pieces, failed runs, non-convergence, and invalid
geometry keep the affected experiment blocked and leave RF metrics null.
GPU/Sionna RT is separate and optional; inspect its machine-readable report with
`python -m hardware.antenna.capabilities` or call `detect_capabilities()` from
`hardware.antenna.capabilities`.

The Sionna RT capability/scenario manifest is generated separately:

```sh
python -m hardware.antenna.sionna_experiment \
  --spec hardware/spec.yaml --output results/mvp2/antenna/sionna
```

It records the 10 m, obstacle, and orientation-variant scenarios. CPU-only or
missing-Sionna environments mark them `SKIPPED_OPTIONAL` with null metrics. If
CUDA and Sionna are present, a deployment may provide `RIOSE_SIONNA_ADAPTER`
implementing `simulate(scenario, spec_path, output_dir)`; adapter failures are
recorded as blocked optional experiments and never alter the core gate.
