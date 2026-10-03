# Commitment publication contract (MVP 05)

`domain.publication.PublicationPort` is the canonical chain-neutral boundary
for submitting a guarded commitment and explicitly querying its observation.
It describes types and method signatures only. Domain code performs no RPC,
signing, persistence, polling, or retry.

## Request and outcomes

`CommitmentPublicationRequest` contains the guarded public envelope from
`domain.privacy`, an explicit destination and network, a protocol version, and
an optional opaque local idempotency reference. It has no event, animal, owner,
coordinate, raw payload, or credential field. Destination/network identifiers
are required; no implicit mainnet or default adapter exists.

`submit` returns `SUBMITTED`, `REJECTED`, `UNAVAILABLE`, or `UNKNOWN`.
`SubmissionResult` rejects `CONFIRMED`, so a transaction reference or send
acceptance cannot claim confirmation. `query` is a separate operation and may
return `SUBMITTED` when the referenced transaction is observed but still
pending, `CONFIRMED` after a confirmation observation, `REJECTED`, `UNAVAILABLE`,
or `UNKNOWN`, correlated to the requested digest, destination, network, and
reference. Missing observations and transport uncertainty are never represented
as invalid commitment contents.
Reason fields are allowlisted codes rather than exception text.

Every result carries an `EvidenceStatus`. A fake can report `SIMULATED`; an
unconfigured adapter reports disabled with `FUTURE` evidence and no advertised
destinations or networks. This does not change the production API capability,
which remains `FUTURE` until a real adapter is validated.

## Compatibility

The older `identity.BlockchainAdapter.publish(event_hash, payload)` and
`simulation.experimental.BlockchainAdapter.publish(event_hash)` imports are
legacy declarations with incompatible semantics. They remain available for
source compatibility and are not aliases for `PublicationPort`; neither legacy
string return is promoted to `SUBMITTED` or `CONFIRMED`. New code must use the
canonical `PublicationPort`. A later migration can remove the legacy names only
after downstream imports and call sites have moved explicitly.
