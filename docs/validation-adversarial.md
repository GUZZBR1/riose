# Adversarial validation

These checks cover software contracts and CPU simulation behavior. **They do
not validate radio performance or animal response on a physical farm.**

## Automated coverage

### MVP 2 firmware stress harness

The issue-7 matrix reuses `hardware/tests/integration.c`'s C FSM virtual runner
for `NORMAL`, `ACTIVE`, `ALERT`, and `WORST_REASONABLE_CASE` at 1, 7, and 30
days. The orchestrator checks the exact requested virtual duration, profile,
nonzero progress, zero firmware failures, and successful result status. A
seeded host-HAL probe starts timer and sequence counters near `UINT32_MAX` and
requires both wrap counters to advance; the profiles themselves are controlled
deterministic schedules.

The long-run outputs include firmware context size, zero heap bytes (the C FSM
uses no dynamic allocation), and compiler-reported per-function stack frames
when the compiler supports `-fstack-usage`. Per-function frames do not measure
the runtime call-chain high-water. Energy is an explicitly SIMULATED estimate
from the observed packet count and ASSUMED/DATASHEET values in
`hardware/spec.yaml`; it is not an ngspice result or battery-life prediction.

`hardware/tests/integration.c` exercises the production C FSM against
deterministic peripheral models for supported fault probes.
`fault_scenarios.csv` lists each requested injection, expected recovery,
attempt count, terminal state, trace event, observed recovery flag, and status.
The suite currently covers one-shot SPI and I2C/IMU-read recovery, TX-done
timeout recovery, SX1262 BUSY timeout and retry, missing IRQ deadline recovery,
and CRC rejection followed by a valid frame. Analog voltage/ESR/regulator
feedback, a physical watchdog reset, and unexpected-reset supervision remain
`BLOCKED`; they are not recorded as recovered. The suite therefore reports
`PARTIAL` until those electrical/reset interfaces are available.

All runs use host software models only. They require neither GPU nor physical
hardware and make no claim about measured animal behavior or electrical
performance.

- Observation types and serialized dataset feature schemas exclude x/y ground
  truth; labels are written to a separate file. Inference has no truth argument.
- Fixed seeds reproduce episodes and long-run schedules. Packet loss, complete packet loss, NLOS,
  missing/corrupt anchors, controlled stationary movement, and 250 ms per-anchor
  clock offsets are covered.
- The API hides truth unless debug is explicitly requested. Local event hash
  chains detect payload tampering. Tag energy accounting does not double-count
  TX/RX time. CSI and virtual-fence outputs are explicitly simulated.
- Current suite: **45 passed**. The installed Starlette/httpx pair emits a
  deprecation warning from TestClient but does not fail the tests.

## Known limitations

- Timestamp clustering aligns records only within a 1 s epoch tolerance. Larger
  clock offsets are left unmatched rather than guessed.
- Some energy currents remain assumptions pending measurements on a chosen
  board. Battery life is unavailable until a battery capacity is configured.
- Anchor corruption is not automatically detected by the baseline estimators;
  the test demonstrates its effect instead of hiding it.
- There is no physical RF, firmware, RFID reader, or animal-response evidence.

See the generated full benchmark tables and interpretation in
`results/REPORT.md` and `docs/results-2026-10-01.md`.
