# Simulation interoperability

RIOSE exposes a small versioned JSON boundary for simulation requests and
results, plus an adapter to the existing livestock tracking RF observation and
localization estimate types. The contract can be used with an in-repository or
external simulator; it does not invoke or install a simulator.

## Version 1 semantics

Requests use `riose.simulation.request/v1`; outputs use
`riose.simulation.result/v1`. Unknown fields and unsupported versions are
rejected so a producer cannot silently change the meaning of a record.
Identifiers are connected to RIOSE tag and anchor identifiers with explicit
source-to-RIOSE mappings. The adapter checks those mappings and preserves
source identifiers and provenance in a sidecar aligned with each converted
record.

Trajectory, observation, and estimate timestamps are seconds on the declared
`SIMULATION` clock. They are not wall-clock timestamps and do not establish
hardware clock accuracy. ISO-8601 `created_at` and `completed_at` fields record
wall-clock provenance separately.

V1 uses local east/north/up coordinates in the `ENU_LOCAL` frame and meters.
Radio fields name their units (`frequency_hz`, `received_power_dbm`,
`propagation_delay_s`, and `backend_reported_tof_s`). Producers must only
populate a numeric field after its unit and semantics are known. Both ToF inputs
are simulated backend values; propagation delay takes precedence when the
legacy canonical `tof_ns` field can carry only one value, and the sidecar retains
both inputs. Unsupported or unconvertible
measurements remain `null` and should be described in `limitations`; the
adapter does not replace missing values with zero. Unknown units cannot be
converted into these normalized V1 fields by assumption.

Every request and result is explicitly `SIMULATED`. Conversion preserves that
evidence status. A simulated value is not measured hardware data, and
simulation output is not hardware validation. A numerical estimate or a
solver-reported convergence does not by itself establish accuracy or quality.

Results preserve channel, transmission, and reception/delivery states
separately, including `NO_PATH`, `NOT_TRANSMITTED`, `PHY_RECEIVED`,
`NETWORK_FORWARDED`, and `APPLICATION_DELIVERED`. The adapter's existing
`RFObservation.packet_received` boolean remains for compatibility; the
sidecar retains the detailed source state. Simulated received power is not
relabeled as RSSI by default; an explicit conversion option is required and the
result remains simulated. Direct RSSI values require the producer to declare
`SIMULATED_RECEIVER_RSSI` semantics. Propagation delay is distinguished from
measured time-of-flight in provenance.

Result positions converted to `Estimate` must be marked `position_kind` as
`ESTIMATE`. Ground truth is not an estimator input and is not accepted as a
result position. The adapter does not infer an estimate from truth or synthesize
one when the backend provides none.

Canonical JSON and its local SHA-256 content hash support deterministic
fixtures and provenance. The hash is not a blockchain commitment. External
simulators such as FREQUENCIA remain separate optional tools; contract and
adapter use requires only the normal RIOSE Python package dependencies.
