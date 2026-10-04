# External anchoring signer contract (MVP 11)

`AnchoringSignerPort` is separate from the legacy `EventSigner`: it signs exact
transaction bytes with explicit network, expected public key, and purpose. Its
request has no private-key, seed, wallet, or credential field. RIOSE passes no
secret into this process; a signer implementation must keep custody outside
the application boundary.

The typed result is `SIGNED`, `UNAVAILABLE`, or `REJECTED`. A signed result is
bound to a declared public key and is accepted only after an injected
`SignatureVerifier` validates the same immutable message and scope. A signature
does not mean the transaction was submitted or confirmed. Exceptions become
allowlisted reason codes; raw exception text is discarded.

The included signer and verifier fakes produce a deterministic byte string
marked `SIMULATED`; it is intentionally not a cryptographic signature and must
never be used for a real transaction. There is no wallet, HSM, seed generation,
key storage, concrete provider, RPC, or production signer in this MVP. Local
event writes do not initialize or invoke the signer boundary.
