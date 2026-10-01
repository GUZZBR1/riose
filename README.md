# Cattle RF MVP

Local-first prototype for evaluating whether shared sub-GHz anchors can track
cattle without GPS on each animal. The core is a reproducible CPU simulation;
all outputs are labeled by evidence status. Simulated results are not field
validation.

## Status

The CPU-first MVP is implemented and runs locally. It includes a seeded farm
and RF simulator, virtual tag energy/FSM model, six estimators, SQLite animal
identity/event history, editable local dashboard, dataset export, and a
multi-scenario benchmark. All measured errors in this repository are software
simulation results, not farm trials.

## Start

```sh
./setup.sh
./run_demo.sh
```

The dashboard is served locally at `http://127.0.0.1:8000`. It starts with 100
animals and eight anchors; controls change herd size, anchor count/placement,
estimator, and packet loss, then rerun the simulation. Run tests with
`uv run pytest`; run the benchmark with `make benchmark`. `cattle-rf dataset`
creates train/validation/holdout files with ground truth separated from RF
features.

## Local API

The API is served from the same local process. Main routes include
`/api/animals`, `/api/animals/{id}`, `/api/anchors`, `/api/telemetry`,
`/api/positions`, `/api/positions/history`, `/api/events`,
`/api/simulation/run`, `/api/experiments`, and `/api/metrics`. Normal position
responses exclude truth fields; `debug=true` is required to request them.
Animal event hashes are locally verifiable; signatures and public blockchain
publication are future interfaces.

## Results

The checked-in `results/` directory contains the generated full benchmark
tables, error CDF, cost placeholders, report, and a separate holdout dataset.
The detailed run summary and interpretation are in
[`docs/results-2026-10-01.md`](docs/results-2026-10-01.md). A price is left blank
and marked `PRICE_RESEARCH_REQUIRED` until a dated supplier source is entered.

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

## Virtual hardware tag

The new C hardware MVP is isolated under [`hardware/`](hardware/reports/mvp-hardware-report.md)
and does not replace the RF localization simulator above. It contains a
portable firmware FSM, SX1262 SPI command model, LIS2DW12 register/IRQ model,
24-byte telemetry with CRC-16, an integration harness, and a configurable
energy profile. Run `make hardware-test` for the CTest suite or
`make hardware-demo` for the accelerated tag scenarios.

The firmware also builds and runs with Zephyr `native_sim/native/64` against
the same C peripheral models (`make hardware-native-sim` from a configured
Zephyr workspace). The tested Zephyr build is software simulation only.
ngspice 42 ran the single-TX rail transient; the assumed 3.3 V/3 Ω/47 µF model
reached 3.164086 V. Default energy estimates use explicit mixed inputs and do
not calculate autonomy because no battery capacity is selected. Full details,
test counts, energy scenarios, and blockers are in
[`hardware/reports/mvp-hardware-report.md`](hardware/reports/mvp-hardware-report.md).

Wokwi and KiCad remain unverified: their executables are unavailable here, so
the virtual peripherals use local C models and the circuit topology is
documented rather than claiming a compiled KiCad schematic or PCB. No radio
propagation, 134.2 kHz RFID reader, physical battery/brownout, or field animal
behavior is claimed as validated.

