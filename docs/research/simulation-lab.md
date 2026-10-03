# RIOSE Simulation Lab

## Purpose and boundaries

`research/simulation-lab` is an experimental workbench for future simulation research related to RIOSE. Product behavior and public contracts remain in the existing product areas, including `src/riose/products/livestock_tracking/simulation`, `src/riose/products/ear_tag/digital_twin`, and their established tests. This document does not introduce a second simulation or digital-twin architecture.

The lab may later explore RF propagation, Sionna RT, FARM, ns-3, LoRa/LoRaWAN, temporal and clock models, TDoA, localization, campaigns, sweeps, and simulated evidence. No such integration or capability is established by this foundation.

`GUZZBR1/frequencia` remains an independent project and repository. Future work may integrate with it through an explicit, reviewed interface; its source must not be copied into RIOSE or treated as a vendored dependency.

## Evidence and provenance

**SIMULAÇÃO ≠ VALIDAÇÃO FÍSICA.** Results from Sionna, ns-3, analytical models, digital twins, or any other simulator are simulated results. They must not be promoted automatically to physical or experimental evidence, product readiness, or measured claims.

Future reports must identify the result as simulated and record enough provenance to reproduce and assess it, including the simulator and version, configuration, input data references, code revision, random seeds where applicable, and execution date. Missing provenance must be stated rather than inferred.

## Dependencies and artifacts

Keep heavyweight simulators, external checkouts, downloads, virtual environments, caches, builds, and temporary outputs outside tracked product code and source history. Do not add heavyweight dependencies as part of this foundation. The current `.gitignore` already covers common environments, caches, and selected generated results; preserve its existing dataset and result conventions. Add narrowly scoped ignore rules only when a concrete lab artifact path is introduced, so legitimate RIOSE datasets and evidence remain versionable.

Do not commit large raw datasets or unfiltered simulator outputs. Keep them in an appropriate external or ignored storage location and retain compact, reviewable summaries with provenance when they are useful to the repository. Track small inputs or artifacts only when licensing, size, and reproducibility are clear.

## Future integration with `main`

This branch is a research staging area; do not assume it will be merged wholesale into `main`. Develop and evaluate experiments here, then select mature work, create a clean branch from the then-current `main`, and selectively port approved code and evidence into a small, auditable pull request. Keep laboratory-only environments, caches, datasets, raw outputs, dependencies, and temporary tools out of that port unless each item is explicitly reviewed and justified.
