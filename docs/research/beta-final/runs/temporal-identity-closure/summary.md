# Simulation Lab campaign: riose-h2-temporal-identity-closure

Evidence status: **SIMULATED**

## RF

- Backend: `sionna-rt`
- Links: 16
- LOS / NLOS / NO_PATH: 10 / 0 / 6

## Network

- Engine: `ns-3.48/lorawan-v0.3.7`
- Packets transmitted: 4
- Gateway PHY receptions: 10
- Network drop events / collisions: 0 / 0
- NO_PATH / not transmitted events: 6 / 0
- Packet delivery ratio: 1.0
- LoRa: 915000000 Hz, 125000 Hz, SF7, 14.0 dBm, 12 byte payload

## Localization

- Method / frame: FREQUENCIA TDoA / ENU_LOCAL
- Attempts / eligible / converged / failed: 4 / 2 / 1 / 1
- Convergence among eligible: 0.5
- Operational quality accepted / rejected / not evaluated: 1 / 0 / 3
- Conditional RMSE / median / p90 error: 53.42034529689755 / 53.42034529689755 / 53.42034529689755 m

## Temporal model

- Timestamp output is a `SIMULATED_CLOCK_TIMESTAMP_MODEL`.
- ns-3 numerical resolution is not physical hardware timestamp precision.
- Runtime: 7.406 s
- PHY reception is gateway reception; application/server delivery is not modeled.
- No result in this report represents field validation.
