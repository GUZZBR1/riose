# Simulation Contract V1

The dependency-free Python boundary is `riose.simulation_contract.v1`. Its
request and result versions are `riose.simulation.request/v1` and
`riose.simulation.result/v1`. `python -m riose.simulation_contract` validates
and serializes the committed fixture pair without launching a simulator.

## Identity and units

Source identifiers are opaque and typed by `(source_system, source_kind,
source_id)`. A mapping explicitly names the RIOSE identifier kind and value.
V1 requires a one-to-one mapping: repeated source identities and two sources
claiming the same RIOSE identity fail. Each request transmitter must map to its
declared `tag_id`; each receiver must map to its declared `anchor_id`. Missing,
unknown, and contradictory mappings fail closed. No animal/device/transmitter
or gateway/receiver identity is inferred from string equality. FARM requests
may additionally declare `animal_ref`, `device_ref`, and `gateway_ref`; each
has a typed explicit mapping. The FARM adapter checks the supported upstream
identities (`animal-###`, `tx-###`, `GW-*`, and `rx-GW-*`) before it builds the
external `ExperimentSpec`. The RIOSE-side `device_id` remains an explicit
request mapping because the current FARM model does not emit device IDs.

Coordinates are three-element `[east, north, up]` vectors in meters under the
explicit `ENU_LOCAL` frame. Timestamps, simulated propagation delay, and
physical measured ToF are separate seconds-valued fields. Frequency and
bandwidth use Hz; transmit and simulated received power use dBm; phase uses
radians. `rssi_dbm` is reserved for a backend metric whose semantics are
explicitly justified; it cannot coexist with `received_power_dbm` in one V1
observation. Missing backend metrics remain `null`.

## Evidence and channel states

Every fixture result, observation, and location is `SIMULATED`; validators
reject promotion to `VALIDATED`. Channel/path state (`PATH`, `NO_PATH`,
`UNKNOWN`), packet transmit state (`TRANSMITTED`, `NOT_TRANSMITTED`,
`UNKNOWN`), and reception state (`RECEIVED`, `NOT_RECEIVED`,
`NOT_APPLICABLE`, `DATA_UNAVAILABLE`, `UNKNOWN`) are independent. `NO_PATH`
cannot carry received-signal metrics. A ray-tracing backend may provide
simulated received power when packet outcome is `DATA_UNAVAILABLE`; it remains
distinct from RSSI, and RSSI/SNR still require a modeled PHY reception. The
existing adapter carries received power in provenance sidecars and leaves
canonical RSSI null by default. Propagation delay can enter canonical `tof_ns`
only with `SIMULATED_PROPAGATION_DELAY` provenance; it is never labeled
measured ToF. No conversion asserts physical measurements.

## Determinism and provenance

`canonical_json` sorts object keys, uses compact UTF-8 JSON, preserves array
order, and rejects NaN/Infinity. `content_hash` is SHA-256 of those exact bytes;
it is a content digest, not a chain or signature. Request provenance allows
unknown revisions explicitly (`null`) and records dirty state and creation
time. Result provenance reserves request/output hashes and completion time.
The fixture deliberately leaves unavailable hashes and revisions null.

The V1 validator rejects unsupported schema versions and unknown object fields.
There is no migration framework. Backend-specific PHY/solver parameters remain
opaque JSON objects; this contract does not declare backend capabilities.
