# Adversarial validation

These checks cover software contracts and CPU simulation behavior. **They do
not validate radio performance or animal response on a physical farm.**

## Automated coverage

- Observation types and serialized dataset feature schemas exclude x/y ground
  truth; labels are written to a separate file. Inference has no truth argument.
- Fixed seeds reproduce episodes. Packet loss, complete packet loss, NLOS,
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
