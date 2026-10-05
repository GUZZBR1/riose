# Network fault matrix

| Fault / condition | Injected | Observable effect | Expected degradation | Recovery | Status |
|---|---|---|---|---|---|
| High contention | Yes: larger tag count and shorter seeded phase windows | ns-3 gateway `INTERFERENCE` events, packet PDR | More overlapping transmissions reduce gateway RX and unique-packet PDR | Not modeled | SIMULATED / tested |
| Synchronized burst | Yes: all tags use exact source timestamps | Same-epoch transmissions, explicit PHY outcomes | Collision loss under deliberate synchronization | Not modeled | SIMULATED / tested |
| Near-synchronized burst | Yes: deterministic per-device phase within 10 ms | PHY event outcomes | High overlap while retaining non-identical tag phases | Not modeled | SIMULATED / tested |
| Packet loss from interference | Yes, as output from the ns-3 PHY | `INTERFERENCE` gateway outcomes and packet with no RX | Lower PDR; denominator remains TX-start packets | No retry/recovery layer | SIMULATED / tested |
| Weak/bad link | Synthetic positions and Sionna FARM channel output | `UNDER_SENSITIVITY` or `NO_PATH` | Fewer gateway receptions and eligible anchors | Not modeled | SIMULATED / partial |
| Gateway offline | No | No distinct offline state | Cannot claim gateway-failure tolerance | Not modeled | NOT_SUPPORTED |
| Gateway intermittent / recovery | No | No availability timeline or recovery state | Cannot estimate outage duration or failover | Not modeled | NOT_SUPPORTED |
| Packet duplication | No | No application duplicate event | No deduplication claim | Not modeled | NOT_SUPPORTED |
| Delayed / reordered application packet | No | No application receive timestamp or queue | No ordering or application latency claim | Not modeled | NOT_SUPPORTED |
| Non-LoRa high interference | No | No independent emitter model | Coexistence is untested | Not modeled | NOT_SUPPORTED |

An RF `NO_PATH` outcome is kept distinct from a gateway outage. A gateway outage
and packet loss at the PHY are different modeled events in the requested
contract; this simulator currently exposes only the latter's RF/network
outcomes. Every rate in the campaign includes its numerator and denominator.
