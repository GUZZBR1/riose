# Public commitment envelope (MVP 04)

`riose.products.livestock_tracking.domain.privacy` defines a transport-independent,
fail-closed boundary for a future blockchain publisher. It does not publish,
persist, sign, read keys, or accept an `AnimalEvent`; callers must provide only
an already-computed commitment digest.

## Exact public schema

The only accepted JSON object is:

```json
{"algorithm":"sha256","commitment":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","version":1}
```

The property names are exact and case-sensitive. `version` must be integer `1`
(not boolean), `algorithm` must be `sha256`, and `commitment` must be exactly
64 lowercase hexadecimal characters. There is no `metadata` field and no
optional technical identifier. Unknown or missing properties, including
nested objects, fail closed. UTF-8 JSON input and generated output are limited
to 512 bytes. The serializer emits compact UTF-8 JSON with sorted keys, so the
same accepted envelope always produces the same bytes.

Duplicate JSON keys are rejected during parsing, including duplicates inside
otherwise-disallowed nested objects. Rejection messages identify only a fixed,
non-sensitive schema path or a generic envelope error; caller-provided field
names and values are never copied into the exception text.

## Adversarial field report

Synthetic fixtures verify that the three schema fields pass. Names, animal and
owner IDs, coordinates, veterinary history, raw payloads, event lists, salts,
private-key-like fields, arbitrary metadata, compressed/encoded payload fields,
case variants, and Unicode lookalike keys fail. Malformed digest/version values,
duplicate keys, non-JSON numeric constants, non-object roots, and oversized
UTF-8 documents also fail. Test fixtures contain no real animal or owner data.

## Correlation and entropy limits

A digest is not automatically anonymous. A commitment to a small or guessable
input space can be tested offline, and a stable digest can correlate repeated
records. This guard validates the envelope shape; it does not assess the
entropy or privacy of the committed source, add a secret salt, or make legal
anonymity claims. Callers must not put low-entropy personal attributes directly
into a commitment and assume the digest hides them. Any future technical
identifier or schema extension requires an explicit versioned allowlist change.
