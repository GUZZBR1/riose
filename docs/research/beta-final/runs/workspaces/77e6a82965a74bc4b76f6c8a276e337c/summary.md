# Simulation Lab campaign: riose-beta-simulation-v1

Evidence status: **SIMULATED**

## RF

- Backend: `sionna-rt`
- Links: 120
- LOS / NLOS / NO_PATH: 108 / 0 / 12

## Network

- Engine: `ns-3.48/lorawan-v0.3.7`
- Packets transmitted: 20
- Gateway PHY receptions: 72
- Network drop events / collisions: 0 / 0
- NO_PATH / not transmitted events: 8 / 40
- Packet delivery ratio: 1.0
- LoRa: 915000000 Hz, 125000 Hz, SF7, 14.0 dBm, 12 byte payload

## Localization

- Method / frame: FREQUENCIA TDoA / ENU_LOCAL
- Attempts / eligible / converged / failed: 20 / 20 / 20 / 0
- Convergence among eligible: 1.0
- Operational quality accepted / rejected / not evaluated: 14 / 6 / 0
- Conditional RMSE / median / p90 error: 966.0018550415331 / 103.02656830333405 / 1203.9807756411817 m

## Temporal model

- Timestamp output is a `SIMULATED_CLOCK_TIMESTAMP_MODEL`.
- ns-3 numerical resolution is not physical hardware timestamp precision.
- Runtime: 5.969 s
- PHY reception is gateway reception; application/server delivery is not modeled.
- No result in this report represents field validation.
