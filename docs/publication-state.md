# Publication state policy (MVP 08)

`domain.publication_state.transition(snapshot, signal, policy, now)` is a pure
function. It reads no clock, database, network, adapter, or signer and mutates
none of its frozen inputs. It tracks lifecycle (`QUEUED`, `SUBMITTED`,
`CONFIRMED`) separately from attempt condition (`READY`, `IN_FLIGHT`,
`RETRY_WAIT`, `UNKNOWN`, `FAILED`). `READY` on a confirmed snapshot means no
attempt remains active; `CONFIRMED` is terminal in this policy version.

An attempt begins only with an explicit `BeginAttempt`. `SUBMITTED` requires a
correlated `SubmissionAccepted` reference. Only a matching
`ConfirmationObserved` can advance that lifecycle to `CONFIRMED`. A timeout or
inconclusive query sets the attempt condition to `UNKNOWN` while preserving any
known submitted lifecycle/reference, and it cannot make a retry eligible.

Retry is possible only after the typed `PreAcceptanceFailure` signal, which
represents proof that the current attempt failed before destination acceptance,
and only within the supplied attempt budget. The policy derives a retry
deadline from the supplied `now`; `RetryDue` before the deadline is a no-op.
Each signal must match the snapshot's attempt and destination/network. Stale,
out-of-order, uncorrelated, or malformed signals leave the snapshot unchanged.

No state transition writes to the animal event chain. Evidence provenance is
carried through snapshots, so `SIMULATED` observations remain simulated. This
policy does not provide durable state, a claim/lease, polling, transaction
finality, reorg handling, or concurrency control.
