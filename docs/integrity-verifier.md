# RIOSE integrity verifier (MVP 14)

`IntegrityVerifier` is read-only and consumes an explicit local chain summary,
an optional stored `PublicationReceipt`, and an optional already-observed
external lookup result. It performs no network fetch, repair, rehash, or
SQLite write. `Store.event_chain_evidence(animal_id)` reuses the existing
`verify_event_chain` implementation and returns only the validity, head digest,
event count, algorithm/version, and evidence level; it does not include the
animal id or event payload in the verification result.

`INVALID` is reserved for a verifiable contradiction: a broken local chain,
local head/commitment mismatch, receipt or external observation mismatch, an
observed rejection, or incompatible evidence provenance. Missing receipts,
unavailable observations, unconfirmed publication, unsupported versions, and
simulation-only evidence are `UNAVAILABLE`. An RPC timeout is never treated
as tampering. `FUTURE` and `EXPERIMENTAL` evidence sources also remain
`UNAVAILABLE`; an `ASSUMED` RPC observation can be reported as consistent while
retaining its `ASSUMED` label.

`VALID` means the provided local chain, receipt, and confirmed external
observation are internally consistent. It does not establish author identity,
consensus independently of the configured RPC, or finality beyond the
source's reported level. A `SIMULATED` observation remains `SIMULATED` and
cannot become a public anchor.
