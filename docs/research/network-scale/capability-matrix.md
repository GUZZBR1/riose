# Network capability matrix

This matrix describes the RIOSE adapter and the pinned external simulator
`GUZZBR1/frequencia` at `ba2bdabf003722aae8292580e048f7092d0356d6`. The results
are simulated. The adapter source is outside RIOSE; its outcomes are consumed
through a hash-bound process boundary.

| Feature | Supported | Configured | Effective evidence | Tested / limitation |
|---|---|---|---|---|
| Collision / contention | Yes | Tags, timestamps, SF, payload, and traffic phase | ns-3 gateway `INTERFERENCE` event traces | Existing controlled collision case; campaign compares exact synchronization and seeded phases. Collision events are per gateway reception, not unique lost packets. |
| Traffic pattern | Partial | Exact shared timestamps, seeded per-device phase, or a narrow phase window | Requested and effective ns-3 TX timestamps | Device phase is fixed and reused at each epoch. Per-packet jitter and bursty schedules are not representable by the current RIOSE trajectory contract, which requires every tag to use the same timestamp set. |
| RF interference | Partial | Sionna snapshot power and one LoRa channel | PHY outcome causes | Co-channel simulated LoRa interference is observable. External emitters, changing fading during a packet, and cross-channel coexistence are not modeled. |
| Duty cycle | Not effective in this adapter | No duty-cycle request field | No duty-cycle defer/drop output is consumed | The LoRaWAN module has duty-cycle support, but this adapter configures its synthetic sub-band with duty cycle 1.0. Requested duty cycle is not effective. |
| Spreading factor | Yes | SF7–SF12, fixed per run | Result echoes SF; airtime from LoRa PHY | Effective in ns-3; only one SF per run and one 125 kHz channel. |
| Payload and airtime | Yes | Payload 1–51 bytes | Per-packet airtime returned by simulator | Airtime includes LoRa PHY/MAC overhead. Campaign retains TX denominator. |
| Gateway diversity | Yes | 3–8 gateway positions | Per-gateway RX events and packet gateway-ID set | 1–2 gateway end-to-end FARM requests are rejected; no padding is applied. |
| Packet loss | Yes, at PHY | Signal links and traffic load | `NO_PATH`, `UNDER_SENSITIVITY`, `INTERFERENCE`, `NO_DEMODULATOR`, `UNTRACED_DROP` | Packet PDR is unique packets received by ≥1 gateway / packets with TX start. |
| Latency | Partial | PHY timeline | `rx_end_s - tx_start_s` for each RX | This is TX-start-to-gateway-PHY-RX-end, not server or application latency. Propagation delay and clock/TDoA timestamps remain separate. |
| Retransmission / ADR | No | Not configured | Not available | No retransmission, adaptive data rate, or downlink behavior. |
| Application delivery | No | Not configured | `APPLICATION_DELIVERY_NOT_MODELED` | `PHY_RECEIVED` means gateway reception only; there is no network-server/application delivery model. |
| Gateway failure / recovery | Static omission only | A request can contain 3 gateways instead of 4; no online/offline state | Per-gateway PHY events and timestamp counts | A paired 3-vs-4 run represents one gateway absent for the entire scenario. It does not model a time-varying outage or recovery. RF `NO_PATH` is not interpreted as a gateway being offline. |
| Duplicate / reorder | No | Not configured | Not available | Packet identity exists inside the external event adapter; no network-server duplicate suppression or application ordering model. |
| Localization input | Yes, as availability only | Current temporal detector and clock model | Usable distinct gateway timestamps per transmitted packet; minimum 3 | Campaign counts epochs with ≥3 eligible anchors. This is not a localization accuracy assessment. |
| RF backend | Yes | Sionna RT 2.2.0 CPU FARM scenario | Raw result + geometry/config hashes | Synthetic, uncalibrated terrain/materials and idealized isotropic antennas; no field calibration or measured range claim. |

## Semantics and denominators

- `TX_ATTEMPTED` in campaign tables means packets with a non-null ns-3 TX start.
- `PHY_RECEIVED` is counted once per packet if one or more gateways report `RX`.
- `PDR_PHY = PHY_RECEIVED / TX_ATTEMPTED`. When the denominator is zero, PDR is
  null. Requested packets and failed simulations are retained separately.
- `INTERFERENCE` count is gateway-event count. A packet-level interference
  indicator is separately derived when any gateway reports that cause.
- PHY latency is `RX_END - TX_START` and is reported only for RX gateway events.
- Localization-input availability is epochs with at least three non-null
  detector/clock timestamps divided by transmitted packets. Accuracy is not
  inferred from this availability.

## Provenance caveat

The RIOSE runner hashes its generated config, trajectory, ExperimentSpec, raw
Sionna result and network output, and records both repository SHAs. FREQUENCIA's
engine manifest does not attest that it consumed the exact generated config or
trajectory hashes. Treat those values as provenance evidence, not a complete
independent attestation of input consumption. Failed end-to-end runs are
retained by the campaign wrapper; the underlying Sionna runner does not always
write a failure manifest after allocating its run workspace.
