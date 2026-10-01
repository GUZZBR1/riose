# Cattle RF MVP

Local-first prototype for evaluating whether shared sub-GHz anchors can track
cattle without GPS on each animal. The core is a reproducible CPU simulation;
all outputs are labeled by evidence status. Simulated results are not field
validation.

## Status

**In implementation.** The initial vertical slice is one virtual tag, four
anchors, RF observations, localization, and a local dashboard. The intended
demo scales to 100 animals and eight anchors.

## Start

```sh
./setup.sh
./run_demo.sh
```

The dashboard is served locally at `http://127.0.0.1:8000`. Run tests with
`uv run pytest`; run the benchmark with `uv run cattle-rf benchmark`.

## Evidence labels

- `SIMULATED`: produced by the software model, not measured on a farm.
- `ASSUMED`: configured parameter without verified component measurement.
- `EXPERIMENTAL`: exploratory model (for example simulated Wi-Fi CSI).
- `VALIDATED`: reserved for evidence verified against physical measurements.
- `FUTURE`: interface or capability not implemented in this MVP.

Ground truth is maintained separately from receiver-visible observations and
is available only to evaluation and the explicitly enabled dashboard debug
view. Hardware cost fields remain `PRICE_RESEARCH_REQUIRED` until supported by
dated sources.

