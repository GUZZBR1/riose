# Commitment V1 (MVP 03)

Commitment V1 is a chain-neutral local binding around an already-validated
event-chain digest. It is separate from Event Contract V1 and does not alter
event bytes, event hashes, or historical rows. Callers can use
`create_commitment_from_chain_evidence` after the local chain verifier reports
a supported, valid SHA-256 chain.

The local subject reference is generated with `new_subject_ref()` (32 bytes
from the operating system CSPRNG, rendered as 64 lowercase hex characters).
The deterministic blockchain demo uses a fixed synthetic reference only inside
its disposable test scenario; it is not a production subject reference.
The pure preimage is deterministic UTF-8 JSON with sorted keys, compact
separators, ASCII escaping, and these exact fields:

```json
{"algorithm":"sha256","domain":"riose:livestock-commitment:v1","schema_version":1,"source_digest":"<64 lowercase hex>","subject_ref":"<64 lowercase hex>"}
```

`digest` is lowercase SHA-256 of those bytes. The golden vector is covered by
`test_commitment_v1_preimage_and_digest_match_the_golden_vector`. Creation and
verification are pure and offline; unsupported schema versions, algorithms,
or malformed inputs fail explicitly.

The local `CommitmentV1` keeps `source_digest` and `subject_ref` together so
the binding can be verified later. `public_envelope()` projects only the
existing allowlisted `{version, algorithm, commitment}` DTO. The random
`subject_ref` and source digest never enter the envelope. Reuse of a subject
reference enables correlation, and a leaked reference plus a predictable
source can make guessing easier; a hash is not anonymity or proof of origin.
Keep the reference local, generate one per subject, and do not publish raw
events, identifiers, payloads, or secrets.
