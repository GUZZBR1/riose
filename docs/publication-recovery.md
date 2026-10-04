# Publication recovery policy (MVP 10)

`PublicationRecoveryService` accepts an injected lookup port and a frozen
recovery snapshot. Each `reconcile` call performs at most one lookup, records
the explicit observation time and query count, and stops before calling the
port when the configured query budget is exhausted. Budgets are capped at 20
lookups and 10 publication attempts. A service instance reserves a lookup
before calling the port, so concurrent calls or replaying an older snapshot
cannot consume the same budget twice while that service instance is alive.
The caller must persist and resume the returned `RecoverySnapshot` across
process restarts; the reservation map itself is process-local. The service
never submits a publication.

Correlated lookup results resolve to `RESOLVED_SUBMITTED` or
`RESOLVED_CONFIRMED`. `NOT_FOUND` maps to `WAIT`, since an indexer or lookup
source may be incomplete. Timeout and lookup exceptions map to `UNAVAILABLE`
with a fixed reason code and preserve the publication attempt. A contradictory
digest, destination, network, reference, attempt, or evidence provenance maps
to `INVALID` without overwriting that attempt.

`SAFE_TO_RETRY` requires source-bound `VALIDATED` evidence, an injected
verifier that validates its provenance and attempt binding, separate caller
authorization, and remaining attempt budget. `SIMULATED` proof fixtures can
exercise lookup behavior but can never authorize a live retry. Not-found,
timeout, unavailable lookup, and absence of a saved reference are never such
proof. Only the recovery service releases the interrupted attempt to `READY`
after those checks; the general state machine has no retry-release signal.
Recovery does not begin or submit the next attempt. The caller can then pass
that returned state through `BeginAttempt` with a new attempt id.

Fixtures cover crash before send and after destination acceptance, repeated
reconciliation, stale-snapshot replay, query budget exhaustion, proof
provenance, mismatch, and simulated evidence. There is no background polling,
scheduler, automatic resend, or change to the local animal event chain.
