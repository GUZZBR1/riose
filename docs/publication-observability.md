# Local publication observability (MVP 15)

`GET /api/publication/observability` is local and read-only. Until a component
owns authoritative publication-state metrics, it reports `enabled: false`,
`state_available: false`, and `null` counts/timestamps. Unknown is not reported
as zero confirmed or zero failed.

The snapshot contract keeps lifecycle counts (`QUEUED`, `SUBMITTED`,
`CONFIRMED`) separate from attempt-condition counts (`IN_FLIGHT`, `RETRY_WAIT`,
`UNKNOWN`, `FAILED`, `UNAVAILABLE`). Each count can remain `null` when missing.
The DTO has no animal ids, commitment ids, references, payloads, or credentials.
The last error can only be an allowlisted `PublicationErrorCode`; exception
messages are never accepted. Reading this surface does not call a publisher,
retry, or RPC adapter and does not gate normal local operation.
