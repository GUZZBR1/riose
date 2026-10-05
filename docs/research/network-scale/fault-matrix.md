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
| Co-located ten-tag synchronized contention | Yes: common timestamp, 10 epochs, 4 gateways, SF7/12 B, 3 seeds | 0/300 PHY packets received; interference and no-demodulator causes kept separate; every packet RF-path eligible | Demonstrates a schedule-dependent PHY outcome for this synthetic control only | Not modeled | SIMULATED / controlled |
| Co-located ten-tag per-device staggering | Yes: seeded phase over 10 s, 10 epochs, 3 seeds | 280/300 PHY received; 20 interference losses; every packet RF-path eligible | Paired contrast with exact and 10 ms schedules; not a generic capacity threshold | Not modeled | SIMULATED / controlled |
| 1 s cadence with deferred MAC TX | Requested in initial closure run; adapter event mapping FIFO | Actual TX starts can be attributed to the wrong source event after ns-3 deferral; 315 mismatches in 9 unique runs | Excluded from PDR/capacity interpretation; retained as an adapter-fidelity failure | Upstream adapter correction required | INVALID EVIDENCE / NOT USED |
| Static omission of fourth gateway | Yes: first 3 vs all 4, 10 tags, 60 s, 10 epochs, 3 seeds | 100/100 received for each seed in both configurations; common first-three-gateway RF records match | Static reception survives omission in this geometry; three-gateway localization input availability is 0/100 vs 100/100 at four gateways | No outage detection or recovery modeled | SIMULATED / static only |
| Duty-cycle restriction | No effective limit; adapter configures 100% duty | Module supports duty-cycle scheduling, but no meaningful cap is applied | Cannot infer duty-cycle-limited cadence or throughput | Adapter duty-cycle support required | NOT_MODELED |
| Application/network-server delivery | No | Simulation terminates at gateway PHY reception | No delivery, ordering, retry, or application latency claim | Not modeled | NOT_MODELED |

An RF `NO_PATH` outcome is kept distinct from a gateway outage. A gateway outage
and packet loss at the PHY are different modeled events in the requested
contract; this simulator currently exposes only the latter's RF/network
outcomes. Every rate in the campaign includes its numerator and denominator.
