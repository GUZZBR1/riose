# Idempotent publication intent (MVP 09)

`derive_publication_key` hashes canonical compact JSON containing a key version,
protocol version, purpose, destination, network, and commitment digest. It
contains no animal identity, event payload, or signer material. The key is
stable for the same intent and changes when any scoped component changes.

`IdempotentPublisher` reserves the key before calling the adapter. Existing
submitted or confirmed records reuse their local reference; an in-progress,
unknown, unavailable, or otherwise unresolved record blocks another submit.
Only an explicit, correlated `CONFIRMED` query updates the registry to confirmed.
Exceptions from the adapter are redacted and leave the key unknown.

The `PublicationAttemptRegistry` is a port. The provided in-memory registry is
a thread-safe test fake only; it is volatile and not crash durable. Local
deduplication prevents duplicate calls only to the extent that a registry
implementation is atomic and durable across its intended callers. The key does
not force a remote destination to honor it and does not guarantee exactly-once
external effects. UNKNOWN remains inconclusive and is never automatically
resent by this boundary.
