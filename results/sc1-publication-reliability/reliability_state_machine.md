# Publication Reliability State Machine

## After SC-1

The existing request states remain evidence-oriented. Two terminal states were added without replacing the existing request, attempt, or receipt model:

| State | Meaning after SC-1 | Automatic behavior |
|---|---|---|
| `QUEUED` | Durable target request with no new signed attempt | Prepare only when due; transient pre-submit failures stay queued with backoff |
| `PREPARED` | Exact signed payload and transaction id persisted before sending | May send/replay the same bytes only when due; Solana additionally checks blockhash expiry |
| `RPC_ACCEPTED` | RPC returned matching persisted transaction id; not proof of chain effect | Observe receipts; never claim verification from RPC acceptance |
| `UNKNOWN` | Submission/observation remains ambiguous | Observe and, when due, replay only the exact persisted bytes; never silently prepare a replacement |
| `RETRYABLE` | Adapter proved `safe_to_retry=true` for prior attempt | New attempt only on due processing, under the same event commitment |
| `CONFIRMED` | A correlated receipt is persisted | Retry second verification when uncertain; conflict becomes manual intervention |
| `VERIFIED` | Exact target/commitment relationship passed adapter verification | Terminal |
| `REJECTED` | Adapter reported a transaction rejection | Terminal; not used for transport or local errors |
| `PERMANENT_FAILURE` | Definitive local/configuration/payload failure with no unresolved chain outcome | Terminal and separate from rejection |
| `MANUAL_INTERVENTION` | Retry cap reached, Solana attempt expired unresolved, verification conflicts, or local configuration/binding cannot safely continue after an attempt | Terminal for automation; receipt and ambiguity evidence remain available |

`retry_count`, `available_at`, `last_failure_class`, and `last_failure_code` live on the existing outbox row. A scheduler claim is denied until due. Forced reconciliation may observe during backoff but cannot replay a signed payload until the previously persisted due time. The default retry policy is five deferrals, exponential delay from 2 seconds up to 300 seconds, with symmetric 20% jitter. Exhaustion stops as `MANUAL_INTERVENTION`, never as a fabricated rejection.

When the current block height exceeds a persisted Solana `last_valid_block_height` and no receipt is observable, the dispatcher enters `MANUAL_INTERVENTION` with `PERSISTED_ATTEMPT_EXPIRED`. It does not create a replacement signature because absence from one RPC observation is insufficient evidence that the earlier transaction did not land.

Current transitions are defined in `domain/publication_state.py`. The next-state shape is:

```text
QUEUED -> PREPARED | PERMANENT_FAILURE | MANUAL_INTERVENTION
PREPARED -> RPC_ACCEPTED | UNKNOWN | RETRYABLE | CONFIRMED | REJECTED | PERMANENT_FAILURE | MANUAL_INTERVENTION
RPC_ACCEPTED -> UNKNOWN | RETRYABLE | CONFIRMED | REJECTED | MANUAL_INTERVENTION
UNKNOWN -> RPC_ACCEPTED | RETRYABLE | CONFIRMED | REJECTED | MANUAL_INTERVENTION
RETRYABLE -> PREPARED | REJECTED | PERMANENT_FAILURE | MANUAL_INTERVENTION
CONFIRMED -> VERIFIED | UNKNOWN | MANUAL_INTERVENTION
VERIFIED | REJECTED | PERMANENT_FAILURE | MANUAL_INTERVENTION -> terminal
```

The manual-intervention transition from `CONFIRMED` preserves the append-only `CONFIRMED` receipt; it does not rewrite evidence as failure.

## Before SC-1

The persisted request state is defined by `domain/publication_state.py`:

| State | Meaning in current code | Allowed next states |
|---|---|---|
| `QUEUED` | Target request is durably queued; no signed attempt yet | `PREPARED`, `REJECTED` |
| `PREPARED` | Signed transaction/payload and target transaction id are durably stored before submit | `RPC_ACCEPTED`, `UNKNOWN`, `RETRYABLE`, `CONFIRMED`, `REJECTED` |
| `RPC_ACCEPTED` | RPC returned the persisted transaction id; this is not proof of on-chain effectiveness | `CONFIRMED`, `UNKNOWN`, `RETRYABLE`, `REJECTED` |
| `UNKNOWN` | Submit/receipt outcome is ambiguous or temporarily unavailable | `RPC_ACCEPTED`, `CONFIRMED`, `RETRYABLE`, `REJECTED` |
| `RETRYABLE` | Adapter provided explicit safe-to-retry evidence; a later `process` can make a new signed attempt | `PREPARED`, `REJECTED` |
| `CONFIRMED` | Adapter observed a target-correlated confirmation; dispatcher may still need a separate verification query | `VERIFIED`, `UNKNOWN` |
| `VERIFIED` | Adapter’s verification query confirmed the exact commitment/transaction relationship | terminal |
| `REJECTED` | Adapter reported permanent transaction rejection | terminal |

The source currently has no durable `SUBMITTING` state. A process crash during RPC leaves `PREPARED`; this preserves the signed bytes and transaction id but cannot tell whether the RPC accepted the transaction. `RPC_ACCEPTED` is an observation, not equivalent to `CONFIRMED` or `VERIFIED`.

## Current transition sequence

```text
QUEUED
  └─ prepare + persist attempt/payload ─> PREPARED
       ├─ submit response matches tx id ─> RPC_ACCEPTED
       ├─ submit exception / mismatch ─> UNKNOWN
       ├─ receipt says retryable + safe_to_retry ─> RETRYABLE
       ├─ receipt says rejected ─> REJECTED
       └─ correlated confirmed receipt ─> CONFIRMED ─ verify exact commitment ─> VERIFIED

PREPARED or UNKNOWN
  └─ reconcile receipt first; if still absent, replay exact persisted payload

RPC_ACCEPTED
  └─ later observation absent ─> UNKNOWN

CONFIRMED
  └─ receipt/verification unavailable ─> remain CONFIRMED; reconcile again
```

The existing dispatcher takes a per-publication SQLite claim and renews it while processing. Claims are released in a `finally` block for ordinary process completion; a process crash leaves a lease that expires. The durable nonce reservation is retained once its token is recorded with a signed attempt.

## Required SC-1 policy invariants

- `UNKNOWN` must never be upgraded to `FAILED` or `REJECTED` without definitive evidence.
- `RPC_ACCEPTED` must never be called `VERIFIED`.
- Only explicit, target-correlated evidence can advance `CONFIRMED`/`VERIFIED`.
- Retry scheduling must be bounded, persisted, restart-safe, and use a due time. Ambiguous submissions must reconcile/replay the exact signed payload, not silently prepare a new commitment or replacement transaction.
- A new signed attempt is only allowed after policy and adapter evidence establish that it cannot create a duplicate effective publication.
- A local terminal error must remain distinguishable from an on-chain transaction rejection.
- Status and retry results are per target; one target outage cannot erase a verified sibling.
- The same canonical commitment remains persisted and reused across retry, restart, and selected targets.
