# Shared evidence bridge (MVP 02)

`riose.evidence.bridge` provides a versioned, product-neutral mapping from a
source's raw status to an evidence class. The bridge preserves the exact
`source_status`, optional `source_ref`, mapping version, explicit inference
method, measurement provenance, and a bounded canonical JSON snapshot of the
source context. Its serializer is deterministic and its parser rejects unknown
fields, duplicate keys, unsupported versions, and evidence classes that do not
match the mapping rules.

| Raw source status | Evidence class | Condition |
| --- | --- | --- |
| `SIMULATED` | `SIMULATED` | Always; never promoted |
| `ASSUMED` | `INFERRED` | Only when an explicit inference method is supplied; otherwise `UNKNOWN` |
| `DATASHEET` | `DECLARED` | Only with a non-empty source reference; otherwise `UNKNOWN` |
| `MEASURED` or `VALIDATED` | `MEASURED` | Only with physical-source, capture, and provenance references that agree; otherwise `UNKNOWN` |
| `EXPERIMENTAL`, `FUTURE`, or an unknown value | `UNKNOWN` | No permissive fallback |

`VALIDATED` records that a check succeeded; by itself it does not identify an
evidence origin and never means physical measurement. The bridge does not
validate scientific quality. A `MEASURED` classification is an auditable
claim only when a physical source is identifiable, the capture is referenced,
and the provenance record can be independently inspected. The digital-only
MVP2 spec continues to reject `MEASURED` regardless of this bridge.

The livestock RF and ear-tag digital-twin adapters are separate boundary
modules. They import the neutral bridge, retain the original product status,
and do not import each other's implementation. The bridge is local metadata;
it is not added to publication envelopes.
