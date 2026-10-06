# Simulation Lab campaign: network-scale-20-tags

Evidence status: **SIMULATED**

## RF

- Backend: `sionna-rt`
- Links: 80
- LOS / NLOS / NO_PATH: 52 / 0 / 28

## Network

- Engine: `ns-3.48/lorawan-v0.3.7`
- Packets transmitted: 20
- Gateway PHY receptions: 52
- Network drop events / collisions: 0 / 0
- NO_PATH / not transmitted events: 28 / 0
- Packet delivery ratio: 0.85
- LoRa: 915000000 Hz, 125000 Hz, SF7, 14.0 dBm, 12 byte payload

## Localization

- Method / frame: FREQUENCIA TDoA / ENU_LOCAL
- Attempts / eligible / converged / failed: 20 / 13 / 13 / 7
- Convergence among eligible: 1.0
- Operational quality accepted / rejected / not evaluated: 13 / 0 / 7
- Conditional RMSE / median / p90 error: 193.73812664063652 / 118.18960072841904 / 228.87127506743474 m

## Temporal model

- Timestamp output is a `SIMULATED_CLOCK_TIMESTAMP_MODEL`.
- ns-3 numerical resolution is not physical hardware timestamp precision.
- Runtime: 14.374 s
- PHY reception is gateway reception; application/server delivery is not modeled.
- No result in this report represents field validation.
