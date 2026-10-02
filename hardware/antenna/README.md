# RIOSE MVP 2 antenna experiments

Run headlessly from the repository root:

```sh
python -m hardware.antenna.run --spec hardware/spec.yaml --output results/mvp2/antenna
```

The command writes `antenna_experiments.json` and `antenna.csv` with the five
scenario IDs: free space, PCB, battery, enclosure, and experimental animal
proximity. If openEMS/CSXCAD are missing, each case is `NOT_AVAILABLE` and RF
metrics are null. If bindings exist without a configured adapter, status is
`ADAPTER_NOT_CONFIGURED`; no analytical estimate is represented as a simulation.

The expected spec records are under `antenna` and each includes `value`,
`unit`, `source`, and `status`. A `MEASURED` status is rejected for MVP 2.
Initial defaults (915 MHz, 82 mm element length, 0 mm feed coordinate, 2 mm
clearance and meandered monopole topology) are all `ASSUMED`, not findings.
The `mechanical` section is recognized as the geometry contract, but no mesh is
silently inferred from dimensions. A solver adapter must disclose mesh source,
geometry hash, materials, solver version, and convergence settings.

Set `RIOSE_OPENEMS_ADAPTER=module.name` to load a Python module exposing
`simulate(spec=..., scenario=..., output_dir=...)`. It may report `COMPLETED`
only after a real openEMS run and must return solver-derived `metrics`. Preserve
raw S-parameter/far-field outputs and provenance. The animal case is an
experimental material approximation, not tissue validation. GPU/Sionna RT is
separate and optional; inspect its machine-readable report with
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
