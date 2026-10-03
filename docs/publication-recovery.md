# Publication recovery policy (MVP 10)

`PublicationRecoveryService` accepts an injected lookup port and a frozen
recovery snapshot. Each `reconcile` call performs at most one lookup, records
the explicit observation time and query count, and stops before calling the
port when the configured query budget is exhausted. The service never submits
or retries a publication.

Correlated lookup results resolve to `RESOLVED_SUBMITTED` or
`RESOLVED_CONFIRMED`. `NOT_FOUND` maps to `WAIT`, since an indexer or lookup
source may be incomplete. Timeout and lookup exceptions map to `UNAVAILABLE`
with a fixed reason code and preserve the publication attempt. A contradictory
digest, destination, network, reference, attempt, or evidence provenance maps
to `INVALID` without overwriting that attempt.

`SAFE_TO_RETRY` requires a typed proof that the particular attempt was not
accepted, plus an explicit caller authorization and remaining attempt budget.
Not-found, timeout, unavailable lookup, and absence of a saved reference are
never such proof. The decision does not trigger a retry; the caller must use a
separate policy transition.

Fixtures cover crash before send and after destination acceptance, repeated
reconciliation, query budget exhaustion, mismatch, and simulated evidence.
There is no background polling, scheduler, RPC client, automatic resend, or
change to the local animal event chain.
