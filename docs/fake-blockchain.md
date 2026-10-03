# Simulated blockchain adapter (MVP 06)

`simulation.blockchain.FakeBlockchainAdapter` implements the canonical
`PublicationPort` using only in-memory state. Each instance receives an
explicit sequence of `FakeSubmitOutcome` values. No network, credential,
signer, persistent store, automatic retry, or production capability is used.

Every returned result and capability is marked `SIMULATED`. A scripted
`CONFIRMED` outcome makes submit return `SUBMITTED`; only a later explicit
lookup returns the simulated confirmation. An exhausted outcome sequence,
timeout, missing reference, or unresolved submission remains `UNKNOWN`.
Lookup mismatches are `REJECTED` with an allowlisted reason code.

The fake retains only digest, destination, network, generated reference, and
status in volatile memory. It never stores the request object or raw payload.
References are deterministic within an instance (`simulated-0001`, etc.) and
all state disappears when that instance is discarded. A new instance has no
knowledge of prior references. These outcomes exercise application behavior;
they are not evidence of a public-chain write and do not change the API's
`FUTURE` blockchain capability.
