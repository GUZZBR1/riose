# Simulation Lab campaign: farm-rf-smoke-v1

Evidence status: **SIMULATED**

## RF

- Backend: `sionna-rt`
- Links: 12
- LOS / NLOS / NO_PATH: 9 / 0 / 3

## Network

- Engine: `ns-3.48/lorawan-v0.3.7`
- Packets transmitted: 2
- Gateway PHY receptions: 6
- Network drop events / collisions: 0 / 0
- NO_PATH / not transmitted events: 2 / 4
- Packet delivery ratio: 1.0
- LoRa: 915000000 Hz, 125000 Hz, SF7, 14.0 dBm, 12 byte payload

## Localization

- Method / frame: FREQUENCIA TDoA / ENU_LOCAL
- Attempts / eligible / converged / failed: 2 / 2 / 1 / 1
- Convergence among eligible: 0.5
- Operational quality accepted / rejected / not evaluated: 0 / 1 / 1
- Conditional RMSE / median / p90 error: 4349.931693883372 / 4349.931693883372 / 4349.931693883372 m

## Temporal model

- Timestamp output is a `SIMULATED_CLOCK_TIMESTAMP_MODEL`.
- ns-3 numerical resolution is not physical hardware timestamp precision.
- Runtime: 7.286 s
- PHY reception is gateway reception; application/server delivery is not modeled.
- No result in this report represents field validation.
