# EVM Core handoff after Mini-MVP 2

This handoff describes the publication seam only. No Base, Arbitrum, EVM
adapter, contract, wallet, or deployment is part of Mini-MVP 2.

## Stable local inputs and storage

- Event V1 and the verified event prefix remain local. The outbox stores one
  immutable canonical public envelope per event, reused across targets.
- A queued target identifies `chain`, `network`, and `adapter_id`. The
  dispatcher requires an exact match, verifies the local event/commitment
  binding, and passes the persisted envelope unchanged to the adapter.
- `ChainAdapter.prepare(envelope)` returns a `PreparedPublication` with
  transaction ID, signed payload bytes, and bounded metadata. The generic
  outbox durably records it as PREPARED before `submit` is called.
- `ChainAdapter.validate_prepared(prepared, envelope)` must authenticate a
  reloaded payload and bind it to that exact envelope before re-submission.
  `submit` must be idempotent when called repeatedly with the same bytes.
- `get_receipt` returns a correlated `ChainReceipt` or `None`; `verify`
  decides whether a confirmed receipt proves the exact envelope. A malformed
  or unavailable observation stays ambiguous rather than becoming a success.
- One SQLite processing claim per target coordinates workers. Claims renew
  while active; attempt and receipt writes are fenced by the claim token.
  After a crash or lost claim, another worker may replay only the persisted
  payload. It must not create a new attempt merely because a query is absent.

## Requirements for a later EVM adapter

1. Define an explicit allowlisted chain ID/network identity and exact target
   adapter ID. Never infer a network from an RPC URL.
2. Persist the fully signed wire transaction, hash, nonce, chain ID, sender,
   contract destination, calldata/commitment binding, and validity metadata
   before broadcast. Keep key material out of outbox rows, receipts, logs, and
   CLI output.
3. On recovery, parse and validate the persisted wire against the envelope,
   chain ID, nonce, destination, and expected contract method. Re-broadcast
   the identical wire if needed; an absent receipt alone does not authorize a
   new nonce or signature.
4. Return normalized receipt states and sanitized technical reason codes.
   Treat malformed RPC data, timeouts, and pending transactions as UNKNOWN.
   Mark RETRYABLE with `safe_to_retry` only after proving a new attempt cannot
   duplicate a successful publication. A rejected transaction is terminal
   only when the receipt proves rejection.
5. Preserve target independence: one failed chain request cannot change
   Event V1, the canonical commitment, or a separate target's journal.

## Evidence required before EVM Core approval

Provide adapter-specific tests for signed-wire integrity, chain ID mismatch,
nonce replacement/expiry ambiguity, same-wire replay, contract event or state
confirmation, malformed receipts, target isolation, two-worker contention,
restart from PREPARED/UNKNOWN/CONFIRMED, and no private data leakage. Run the
full repository regression and review the actual chain result independently.
Mini-MVP 2's Solana single-endpoint evidence is labeled ASSUMED; it is not
evidence for EVM behavior.
