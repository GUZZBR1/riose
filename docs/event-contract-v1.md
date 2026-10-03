# Livestock tracking Event Contract V1

V1 names the event digest format already used by `domain/identity.py`. It does
not add a second chain or change the bytes used by historical events.

## Hashed representation

The SHA-256 input is UTF-8 (no BOM and no trailing newline) for one JSON object
containing exactly these fields:

```json
{"animal_id":"…","event_type":"…","payload":{},"previous_hash":"…","timestamp":0.0}
```

Serialization uses Python's JSON representation with keys sorted at every
object level, separators `,` and `:`, and `ensure_ascii=False`. Strings are
encoded as UTF-8 without Unicode normalization. Arrays retain their order.
JSON values are limited to objects with string keys, arrays, strings, booleans,
null, integers, and finite floating point numbers. NaN and either infinity are
invalid. Timestamp is a finite JSON number; writers store it as a float. The
serializer preserves Python's JSON number rendering, including the distinction
between an integer and a floating point value.

Only `animal_id`, `event_type`, `timestamp`, `payload`, and `previous_hash`
participate in the digest. `schema_version` identifies the format outside those
bytes. New SQLite events store `v1`; a NULL or absent version means a legacy
event and is checked using the same V1-compatible bytes. Unknown versions fail
verification explicitly. Adding the nullable column does not rewrite existing
rows or hashes.

`event_id`, `signature`, and other storage/API metadata are excluded. The
current signature field does not prove a signature was checked or authenticated.
The hash chain detects changes to the represented event data and links; it does
not prove authorship, physical identity, sensor authenticity, event truth, or
that a database has not had a trailing suffix removed. It is a local integrity
check, not an authenticity claim.

## Frozen vector

Input fields:

- `animal_id`: `cow-π`
- `event_type`: `WEIGHT_RECORDED`
- `timestamp`: `12.5`
- `payload`: `{"z":"quote:\"/snowman:☃","a":[true,null,1.25]}`
- `previous_hash`: 64 zero characters

Expected canonical bytes (shown as UTF-8 text):

```text
{"animal_id":"cow-π","event_type":"WEIGHT_RECORDED","payload":{"a":[true,null,1.25],"z":"quote:\"/snowman:☃"},"previous_hash":"0000000000000000000000000000000000000000000000000000000000000000","timestamp":12.5}
```

Expected SHA-256: `6acfbf7db10fde03c9779925db291056a55086b3549dbf05030b2be60cb58dd8`.

