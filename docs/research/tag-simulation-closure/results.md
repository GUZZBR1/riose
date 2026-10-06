# Tag simulation closure results

**STATUS: PASS (simulated tag sensor gate); antenna: PARTIAL_SIMULATED.** The requested dataset → RESD → Renode LIS2DW12 → Zephyr firmware → captured trace path is demonstrated for STATIC, WALK and RUN, with an independent golden axis/sign probe. The current free-space openEMS run met the time-domain energy criterion but failed RF-result validation; antenna remains isolated from focused tag runs, with no accepted RF or physical-performance claim.

## Gate summary

- **TAG SENSOR PIPELINE:** PASS (simulated). Profile inputs reach Renode-backed sensor registers, are read by the Zephyr firmware, and produce real firmware UART `SIMULATED_TRACE` records. Robot checks every captured axis against the selected RESD first sample through register quantization and firmware mg conversion.
- **DATASET:** Five distinct deterministic dataset profiles are labelled `SIMULATED`, each with 128 XYZ samples at 12.5 Hz (10.24 s). STATIC/WALK/RUN are exercised end-to-end; IMPACT and RANDOM_MOVEMENT are converted and content-checked but not yet run through firmware.
- **RESD:** Five profile streams are converted with Renode 1.17 `csv2resd.py`. The converter compares generated values with source rows and rejects invalid metadata, timestamps, empty streams, wrong axis shapes, and values outside the sensor's physical ±16 g range.
- **RENODE:** Full Robot platform suite passes. Four profile-bound tests (STATIC, WALK, RUN, GOLDEN_AXIS_PROBE) also passed twice consecutively, with deterministic UART traces.
- **LIS2DW12:** Profile output scale/axis expectations match configured high-performance 14-bit, ±2 g mode (`int(µg / 244) * 4`). Golden probe checks positive X, negative Y, Z, axis order and quantization.
- **FIRMWARE:** Fresh Zephyr 4.2.1 ELF for `nucleo_l031k6` built with the Renode-only minimal logger and structured trace option. Image uses 32,640 / 32,768 bytes flash and 3,984 / 8,192 bytes RAM. The flash margin is 128 bytes; this is a maintenance risk for future simulation-profile firmware changes.
- **ANTENNA:** `PARTIAL_SIMULATED`. The solver reported its energy criterion before the nominal excitation length, so source-tail completion is not established; the computed S11 curve also had a positive dB value and was rejected by the result validator. There are no accepted RF metrics or mesh-refinement proof. `--skip-antenna` marks antenna stages `NOT_RUN`, makes them nonrequired and enables tag-focused gate runs.
- **REGRESSION:** Complete Python, Robot, CTest, Python compile and diff checks passed; counts below.
- **EVIDENCE:** Captured UART lines and their SHA-256 are retained in `firmware-trace-capture.log`; `firmware-trace-evidence.json` binds traces to source datasets, RESD streams and the ELF.

## Pipeline map and root cause

`hardware/models/lis2dw12/datasets/<profile>.csv` → `hardware/renode/scripts/dataset_to_resd.py` → Renode `LIS2DW12WakeModel` → LIS2DW12 output registers over I²C → Zephyr sensor read → UART `SIMULATED_TRACE` captured by Robot on `sysbus.usart2`.

- **Observed bug:** no failure of profile propagation was reproducible in the existing path; the previous smoke tests showed register reads but did not capture the firmware trace.
- **First incorrect boundary:** the Renode Zephyr configuration disabled logging, so the firmware trace callback had no observable UART output.
- **Cause:** missing simulation logging configuration and insufficient profile coverage (the prior end-to-end checks covered STATIC and WALK, not RUN or a controlled axis probe).
- **Fix:** enabled the minimal logger and structured trace option in the Renode-only board config; Robot now captures and validates UART trace fields against the selected RESD sample. Added RUN and controlled golden probe tests plus an explicit missing-RESD failure check.

## Profile results and trace evidence

Capture log SHA-256: `a344afba2a23869e4948599ed0e28c52afa4e002214fe2e09e3ccca9c6490591`. Firmware ELF SHA-256: `2b89915e779c870cf8ed63623f28a89cd3da03b51ae9851977b4a284d330c8f6`. The UART capture was returned by Renode Robot's terminal tester waiting on `sysbus.usart2`; these are firmware-originated lines, not Robot-generated summaries.

Each source profile below is from the deterministic synthetic profile generator (seed `20261002`), not measured animal data. Mean, population standard deviation and RMS are calculated over 128 values per axis in g. CSV and RESD SHA-256 values were rechecked from the current files; all five inputs and streams are byte-distinct.

| Profile | N / rate / duration | Mean XYZ (g) | Stddev XYZ (g) | RMS XYZ (g) | CSV SHA-256 | RESD SHA-256 | Firmware evidence |
|---|---|---|---|---|---|---|---|
| STATIC | 128 / 12.5 Hz / 10.24 s | [0.000117, 0.000094, 0.999977] | [0.001445, 0.001265, 0.001439] | [0.001450, 0.001269, 0.999978] | `fafbc464874b97e877b3b35d38201e8d6f86d00f41b03849845261f35fa9b1cd` | `e3e97db1892eed70314f54b15a17f68db26b32554ce6b863c66b976427b229f5` | trace XYZ decoded [0, 0, 1001] mg; Z raw `0x4028` |
| WALK | 128 / 12.5 Hz / 10.24 s | [0.003305, 0.001633, 1.001633] | [0.169807, 0.063678, 0.112849] | [0.169840, 0.063699, 1.007970] | `e1b0da6e675577daad8d855e95ede3b2b6272b5f0380bc38eafcd39e1fd8ee94` | `87796ed42bbb1eeaf7d961fd081cc2bbb142ffbd0b2bccf74fefac8086291125` | trace XYZ decoded [-1, 56, 1159] mg; Z raw `0x4A48` |
| RUN | 128 / 12.5 Hz / 10.24 s | [0.005656, 0.001906, 0.999914] | [0.549398, 0.297236, 0.397523] | [0.549427, 0.297242, 1.076036] | `f2845f9e8325b143eb15988341d4b5110a23a1b0216f4f7800a051c0f78a7d` | `267343d0141ab19fab73a252f5ce6f3f5d6445d1c1a3e447e62bfe2e71fc7562` | trace XYZ decoded [0, 327, 1558] mg; Z raw `0x63D4` |
| IMPACT | 128 / 12.5 Hz / 10.24 s | [0.026508, -0.015867, 1.042297] | [0.158549, 0.095320, 0.253802] | [0.160750, 0.096631, 1.072753] | `d4f5b6f305ebe8aaca81abc56aae66ac1dbf35a0b7c0704b0b95ee0fda9e0282` | `36ae1503b25a7a1da8b0ecd8db65ee1968f53d6f1434ad36e121a001b2b55690` | converted and content-checked; firmware path not exercised |
| RANDOM_MOVEMENT | 128 / 12.5 Hz / 10.24 s | [-0.023703, 0.033023, 1.017383] | [0.097503, 0.079727, 0.070448] | [0.100342, 0.086296, 1.019819] | `c9afa691e11f649893ec543164f2c111c4a03c6ced2f8ed1e0affd3fb5cfa962` | `860a0f3f794bf7c2ef0311363dfa27715c19ab9abb9e7391d95afacf455c05f7` | converted and content-checked; firmware path not exercised |

| Engineering probe | Input XYZ (g) | CSV SHA-256 | RESD SHA-256 | Trace XYZ decoded (mg) | Output XYZ raw |
|---|---|---|---|---|---|
| GOLDEN_AXIS_PROBE | first sample [0.25, -0.125, 1.5]; four samples total | `4e0636d43473d45ec63a3608bcbaeb5567f62e6805b74b248473d167ecd0efd3` | `3c9c84725258b5aa8743369da3380f09d1d5fee98de84146cbfa0e91694391b3` | [249, -124, 1499] | [`0x1000`, `0xFFFFF800`, `0x600C`] |

## Data lineage

The converter maps CSV columns in XYZ order from g to integer µg, validates manifest provenance/rate/count and uniformly spaced timestamps, invokes Renode's `csv2resd.py`, then parses the RESD v1 payload and compares every XYZ sample with the source values. For the configured high-performance 14-bit ±2 g mode, the register expectation is `int(µg / 244) * 4`; the firmware masks/sign-interprets its register value and converts to mg at 0.976 mg per sensor digit. Robot compares the first RESD sample through both transforms for each captured trace. This is numeric lineage, not byte-for-byte identity across formats.

Raw UART fields are unsigned 32-bit decimal renderings from firmware `%u`; Robot interprets each field as signed by two's-complement conversion. Thus raw WALK Y=`4294967295` decodes to −1 mg and golden Y=`4294967172` decodes to −124 mg. The table and JSON manifest values are the decoded signed values; `firmware-trace-capture.log` preserves the raw firmware lines. Two runs produced the same four lines in the same order; their capture artifact SHA-256 is listed above.

## OpenEMS / antenna

- **Environment:** openEMS native Python binding `0.37.0rc3.post1.dev31+g6761a36e2`, CSXCAD `0.7.0rc3.post1.dev7+g65e759115`, and native executable v0.37.0-rc3-31-g6761a36 were available. The native binary was found under `/home/gusta/.local/opt/openEMS-0.37.0-rc3/bin` and requires `OPENEMS_INSTALL_PATH` or `RIOSE_OPENEMS_EXECUTABLE`; Octave is absent and is not used by this Python backend.
- **Current model/config:** current `hardware/spec.yaml`, 915 MHz center, 401 sampled frequencies from 686.25 MHz to 1.14375 GHz, Gaussian pulse, 300,000 step cap, `EndCriteria=1e-5` (−50 dB), six `PML_8` boundaries, λ/20 maximum grid with feature-edge alignment and 1.4 smoothing, 50 Ω z-directed lumped port, NF2FF box. Four-turn 82 mm × 28 mm × 10 mm planar monopole candidate; trace and finite ground are zero-thickness PEC assumptions. Spec hash `3d3bf8c40183d2cd176cc54f6288af5114e6b36f2f3b5d2b0f811089de0d22cc`; geometry hash `cdf58104c6dc51e71a05bcfb4804c6a0042df0d8102c4ff1b1df65738c088fcb`.
- **Current pilot input hash:** `5c90283be98a87d4d38862d8643de0e29db0b5f01b7a010fb4e0dfc3e9e2ffab`; mesh has 45,864 recorded cells and ~13.1 mm maximum cell width. Free-space scenario omits the PCB substrate. Other scenarios progressively add assumed PCB, battery, enclosure and homogeneous animal-proximity materials; no material is characterized.
- **Bounded runs:** an initial 40 s run reached 5,166/300,000 steps in 34.59 s, before the 42,362-step pulse ended. A second current-spec run reached the −50 dB energy criterion after 39,114 steps / 262.31 s; residual fraction was `1.2322222324902275e-6` (criterion `1e-5`). This occurs 3,248 steps before the nominal excitation length. The solver's energy criterion was met, but whether the remaining excitation tail is negligible is not established; do not treat this as completed transient evidence without that review.
- **RF validation:** the runner then failed with `invalid/missing openEMS RF result: s11_db at row 0 must be <= 0 dB`. Recomputing the port curve from that run's files yielded a diagnostic range of +0.003734 dB at 686.25 MHz to −0.057452 dB at 1.14375 GHz; at 915 MHz it was −0.013794 dB. Its minimum occurred at the upper sweep edge, not a resolved in-band resonance. These diagnostics are not accepted RF metrics. Impedance, gain and efficiency remain null/unaccepted; partial near-/far-field files are not metrics.
- **Probable geometry issue:** the generated free-space trace is an 82 mm horizontal XY meander at z=3.3 mm; its XY extent is inside the projected finite ground-sheet extent, with a 2.1 mm vertical gap and no PCB dielectric in that baseline. That can behave unlike the assumed quarter-wave monopole topology and is a plausible source of the near-total reflection, but requires antenna/port design review rather than an unverified code change.
- **Classification:** `PARTIAL_SIMULATED`. One current-source scenario met the solver energy criterion but has unverified source-tail completion; the RF result was rejected and mesh-refinement/five-scenario evidence is absent. An earlier 304,150-cell artifact used a different 143 mm route and geometry hash `a2ac09422455aea718e9a68775806056854a05be5360f16a471f74d5a36e3bef`; it is stale for this source and excluded. Earlier v1 outputs also had a schema/input mismatch. Historical adjacent-mesh deltas are not current evidence.
- **Next RF work:** review the intended radiating geometry and feed, then rerun with mesh refinement and valid RF artifacts before attempting the five-scenario sweep. Numerical convergence would still not establish physical antenna performance.

## Tests and verification evidence

- Full Python suite: **725 collected; 718 passed, 7 skipped, 0 failed, 0 deselected** (one existing Starlette/httpx deprecation warning).
- CTest LIS2DW12 model: **1/1 passed**.
- Hardware CTest suite: **38/38 passed**.
- Robot `hardware/renode/tests/platform-smoke.robot`: **18 passed, 0 failed, 0 skipped**, including the missing-RESD failure case and four firmware UART lineage cases.
- Zephyr 4.2.1 build: passed; 32,640 bytes flash / 3,984 bytes RAM.
- `python -m compileall -q src hardware tests`: passed.
- `git diff --check`: passed after final documentation edits.

## Failure cases

`test_dataset_to_resd.py` exercises unsupported profile, missing source CSV, wrong CSV axes, malformed timestamps, empty stream, out-of-range acceleration, invalid/corrupted generated RESD, and stale output removal on failure. A separate Robot case asserts that attempting to bind a nonexistent RESD raises an error instead of silently retaining the sensor default. Same-seed converter runs compare complete RESD bytes. Focused affected Python tests passed **54/54**.

## Red-team findings

- An independent red-team pass identified missing captured trace provenance, outdated gate wording, no explicit golden-axis path, and incomplete failure evidence. The evidence link, UART capture artifact, corrected docs, golden fixture, converter fail-closed tests and missing-RESD Renode check were added.
- A subsequent acceptance audit found absent dataset numerical statistics, missing explicit agent/root-cause/red-team/Git sections, ambiguous labeling of unsigned raw trace fields as signed, and no byte-level repeated-RESD assertion. These documentation and evidence gaps are now addressed; the byte-level converter assertion and missing-RESD Robot case passed in the completed full runs.
- **Critical remaining:** none known for the scoped STATIC/WALK/RUN simulated sensor path after final verification.
- **Major remaining:** IMPACT and RANDOM_MOVEMENT are not yet run through firmware; exact STM32L031K6 behavior is not modeled by Renode; antenna source-tail completion remains unverified because the energy criterion was reached 3,248 steps before nominal excitation end, the S11 output was rejected, and no mesh-refinement proof exists.
- **Minor remaining:** the firmware UART fields are unsigned representations decoded as signed by the test; flash has only 128 bytes spare in the Renode-specific build. No claim beyond simulation is made.

## Agents

| Agent | Role | Parallel | Status | Result |
|---|---|---|---|---|
| `environment_history_audit` | Repository/history and worktree audit | Yes | DONE | Identified base and related historical branches; no automatic cherry-pick or merge. |
| `antenna_audit` | Antenna/openEMS environment and result audit | Yes | DONE | openEMS/CSXCAD available; current run produced no accepted RF metrics. |
| `calibration_math` | Sensor scaling and quantization review | Yes | DONE | Checked g→µg→register→mg transformation used by trace assertions. |
| `dataset_profile_audit` | Profile provenance and numerical distinction | Yes | DONE | Confirmed five deterministic synthetic profiles and distinction by per-axis statistics. |
| `env_recovery` | Environment and test recovery | Yes | DONE | Recovered available Zephyr/Renode/test tool paths for reproducible runs. |
| `trace_capture_audit` | Firmware trace path audit | Yes | DONE | Found logging disabled and no real UART capture; led to Renode logger/UART capture fix. |
| `closure_redteam` | Independent sensor/antenna red team | Yes | DONE | Identified evidence/documentation gaps; findings addressed above. |
| `acceptance_audit` | Final independent acceptance audit | Yes | DONE | Found missing numeric tables, required report sections, signed/raw clarity and repeated RESD byte assertion; addressed. |
| `trace_lineage_review` | Independent lineage review | Attempted | DEFERRED | Specialist launch failed because the configured model was unsupported for this account; evidence review continued through the other audits and direct tests. |

## Git and worktree state

- Repository: `GUZZBR1/riose`; remotes `fork` (`GUZZBR1/riose`) and `origin` (`santleme/riose`).
- Main SHA: `72ad69551b54eb069bb1c5f863dfff4066786965` (`fork/main`, cached local ref; a live fetch was unavailable due network/DNS failure).
- Initial SHA: `72ad69551b54eb069bb1c5f863dfff4066786965`.
- Branch: `research/tag-simulation-closure`.
- Final SHA: `72ad69551b54eb069bb1c5f863dfff4066786965` (no commit created).
- Commits: none. Dirty: yes; seven tracked files modified, documentation and golden fixture files untracked. These are the intended deliverables.
- Push: no. PR: none created. Merge: none.
- Related history audited: `fork/codex/issue-06-lis2dw12` (`84e66fa4fa497f3a9f3b478f10dfa8eb0ac7011e`, generated reproducible LIS2DW12 profiles and pipeline); `fork/codex/issue-6-resd-propagation-followup` (`7f9b4b74caf849c562fe6a1a8ca767e5c80381be`, Renode IRQ/replay lifecycle); antenna convergence upstream (`6619fb4d4f765d1351138a38af5858aa2689a46c`, refinement proof) and antenna follow-up (`0b5bd21256c0ad180fa1050735346f3e4c5d327`, geometry guidance). These branches have distinct scope and were not merged. GitHub PR lookup failed because both `gh` and web/API access were unavailable, so no claim is made that all corresponding PR discussions were reviewed.
- The original checkout `/home/gusta/projetos/RIOSE/riose` remains on `codex/issue-10-antenna-convergence` at `9bc8e972c4e7418669ce94250c58ce91e49cb744`; edits are in the isolated worktree above. No historical branch was modified.

## Limitations

All dataset, Renode, firmware and openEMS evidence is simulated. The Renode MCU is an STM32L071 surrogate for the target L031K6; exact MCU fidelity is not established. No hardware, sensor-accuracy, animal, field, or physical antenna validation was performed. IMPACT and RANDOM_MOVEMENT still need firmware-path tests if those profiles are required in the acceptance set.

**Gate decision: PASS** for the simulated tag sensor pipeline. The antenna is `PARTIAL_SIMULATED` and isolated from tag-focused gate runs. It is not a hardware, field, physical-sensor, animal, or antenna validation result.

Red-team disposition: critical findings resolved for the scoped sensor pipeline; major and minor limits are listed above; no open finding invalidates the scoped STATIC/WALK/RUN trace evidence. Antenna review found that a cited pilot used different geometry, and the current energy criterion is met before nominal excitation duration while S11 validation fails. Antenna remains `PARTIAL_SIMULATED` and isolated. The GitHub PR discussion lookup remains unavailable, recorded as an audit limitation.

## Next step

Run IMPACT and RANDOM_MOVEMENT through the same firmware UART path if they are needed in the acceptance set. For the antenna, review the feed/geometry and reduce/justify the solver cost, then require mesh-refinement evidence before reporting any RF metric. Do not merge or publish this isolated worktree without a separate review.
