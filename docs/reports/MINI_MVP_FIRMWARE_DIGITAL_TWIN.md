# MINI-MVP 1 — Firmware & Digital Twin Completion Gate

**Reported status:** `PASS`
**Governed candidate status:** `PASS_SIMULATED`
**Evidence captured:** 2026-10-06

PASS applies to the original software and simulated scope of Mini-MVP 1. It does not claim physical, laboratory, RF, or field validation. Hardware flash/run remains outside this phase's gate.

## Provenance and delivery boundary

- Canonical repository: `GUZZBR1/riose`; authoritative remote: `fork` (`https://github.com/GUZZBR1/riose.git`).
- Canonical base and original checkpoint: `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`.
- Approved product tree: `bb9713f64467d498c4547bbe9bc1e32f5617dadf`.
- Isolated branch: `mini-mvp/firmware-digital-twin`.
- Tested implementation commit: `3c694b25132f0ae65c57b88ce37939e854ddbb07`.
- No push, pull request, merge, or `main` modification.
- Completion report and test matrix are evidence artifacts; source/test changes are in the tested implementation commit.

## Closure of the three gaps

### 1. Synthetic RESD movement Robot failure — closed

The original movement case replayed the general WALK RESD dataset but asserted one exact payload vector `(575,793,0) mg`, one wake, and two transmissions. That walking trace does not contain the asserted vector. Its first movement samples also produce a modeled high-pass response below the configured 62.5 mg wake threshold, so one startup TX was correct for those inputs. This was a fixture/expectation mismatch, not a firmware comparator defect or a Robot timing failure.

The replacement fixture starts at `(0,0,1) g`, then steps to `(0.576,0.793,0) g` at 12.5 Hz. The extra X precision accounts for LIS2DW12 register quantization so firmware telemetry remains exactly 575 mg. The fixture is explicitly `SIMULATED`, deterministic, not Gazebo-derived, and not animal data. The Robot assertions were retained: exactly two TX/TX_DONE, one wake/event-source read, three output reads, behavior 3, exact signed XYZ payload, CRC, TX trace metadata, IRQ clear, and final SLEEP state.

The full Robot suite passed **4/4** both in the working tree and in a clean detached checkout built from the implementation commit. The movement output was `tx=2`, `completed=2`, `wake_events=1`, `samples_read=3`, `imu_mg=(575,793,0)`, `WU_SRC=15`, `WU_IRQ=False`, `CRC=True`, `final_state=SLEEP`. The generated RESD SHA-256 is `fce895e711e9f6f50f3ce1bb2d5f1cc29d9869e8e240545a1b441f2e5a22bacb`.

### 2. Full Python suite — closed

The repository declares FastAPI in the normal project dependencies, and its CI runs `uv sync --locked --extra dev` followed by `uv run pytest -q`. The exact sync command could not build the local Hatchling project because package-index DNS was unavailable. The locked dependencies were available locally, so `uv sync --locked --extra dev --no-install-project` installed them without changing project architecture; tests then ran against the checked-out source with explicit `PYTHONPATH`.

The full suite passed **617 tests**, skipped **7**, with one Starlette/httpx deprecation warning. It passed in both the active checkout and clean detached checkout. FastAPI was present during both runs. The package build through Hatchling remains unverified in this network-constrained environment; this did not prevent full source test collection or execution.

### 3. Core identity mapping — classified

- **Original Mini-MVP identity coherence requirement:** `IN_SCOPE_REQUIRED` when identity concepts are present. The firmware boot/config identity flows into the encoded telemetry `tag_id`; the Renode trace parser rejects packet identity divergence; the RESD Robot checks the transmitted packet identity; the MVP3 telemetry adapter checks packet ID against BOOT identity; and `AnchorReceiver` keys events by `(tag_id, sequence)` while retaining the same ID. Scenario identity is `1`. Focused telemetry, livestock backend identity, and temporal identity tests passed **22/22**; the full Python suite also passed.
- **General Core enrollment mapping from firmware `uint32 tag_id` to livestock `animal_id`/`hardware_id`: `FUTURE_PHASE`.** Core maintains a separate hardware-to-animal mapping (`animal_id_for_hardware_id`). A general enrollment bridge is not required by this Mini-MVP DoD: the mission preserves product boundaries and schedules broader cross-product integration later. The architecture explicitly says one product must not reach into another product's implementation. This follow-up does not block the gate.

## Regression results

| Check | Result | Evidence / boundary |
|---|---|---|
| Zephyr NUCLEO-L031K6 build | PASS | Fresh build from clean checkout; 28,980/32,768 B flash, 5,016/8,192 B RAM; not physically flashed |
| Renode Robot RESD suite | PASS, 4/4 | General WALK sample/register replay plus dedicated wake-step firmware case; run from clean checkout |
| Full Python | PASS, 617 passed / 7 skipped | Active and clean checkout; locked dependencies from uv cache, explicit source path |
| Focused identity/temporal | PASS, 22/22 | Telemetry, Core backend identity, temporal identity tests |
| Embedded CTest | PASS, 39/39 | Fresh CMake configure/build from clean checkout, default assertion-enabled profile |
| Firmware host CTest | PASS, 11/11 | Fresh CMake configure/build from clean checkout |
| Gazebo → Renode live `02_walking` | PASS, 11/11 | Previously captured gate; 801 injections, 2 movement-derived TX, 16 simulated seconds, zero maximum barrier error. The fixture-only Robot correction does not modify this live integration path. |
| RESD conversion | PASS | Re-generated from committed manifest/CSV; deterministic output hash recorded above |
| Diff integrity | PASS | `git diff --check`; no firmware production source was changed |

The clean-checkout evidence files are in `docs/reports/evidence/`. The original Robot failure was reproduced before the correction (3 passed / 1 failed); the successful clean-checkout result invalidates that failure as a current gate result while the root cause remains documented here.

## Semantic regression review

**PASS.** The material change is confined to a test fixture, Robot input selection, build setup, and documentation. No production firmware source or packet contract changed.

- LIS2DW12 scale and units remain ±2 g, 0.244 mg/LSB, input in g, register quantization unchanged.
- Movement semantics remain the configured high-pass wake comparator at the production register setup; the fixture drives a deterministic step and keeps exact wake/payload assertions. It does not claim gait recognition or biological classification.
- SX1262 packet format, configuration, logical TX/TX_DONE behavior, and timing model are unchanged. TX_DONE still represents configured Renode model latency, not computed LoRa airtime; there is no emulated over-air receiver.
- Tag identity and telemetry encoding are unchanged; identity remains consistent across boot, firmware packet, Renode trace, and logical anchor processing for scenario `tag_id=1`.
- Temporal attribution and firmware/simulator contract are unchanged. The separate live Gazebo lockstep evidence remains `SIMULATED`; it is not a physical shared clock measurement.

## Scientific classification and remaining work

- `TESTED_SOFTWARE`: firmware FSM/encoding, scale conversion, identity/temporal contracts, fault handling, builds, and test suites.
- `SIMULATED`: Gazebo motion/IMU, RESD replay, Renode LIS2DW12/SX1262 models, wake/TX behavior, and clock mapping.
- `MEASURED_LAB`: none.
- `FIELD_VALIDATED`: none.

**Remaining in-scope gaps:** none identified against the compiled Mini-MVP 1 software/simulated DoD.
**Future follow-ups:** general Core enrollment bridge; physical flash, sensor calibration, RF/antenna, power, clock-drift, and field evaluation. These are outside this phase and are not implied by PASS.

No biological classification, physical sensor performance, radio propagation, or field efficacy is claimed.
