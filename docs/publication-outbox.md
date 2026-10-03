# Local publication outbox (MVP 07)

The SQLite publication outbox is opt-in: `Store(path)` creates no outbox table
and leaves existing local operation unchanged. A caller that explicitly needs
the feature uses `Store(path, enable_publication_outbox=True)` and accesses its
`publication_outbox` repository.

Tickets hold only an opaque local ID, a positive envelope version, bounded
non-empty envelope bytes (maximum 512 bytes), an availability timestamp, and
optional local claim metadata. They do not contain animal/event rows, raw
payloads, signer material, or network results. Callers must supply a minimized
synthetic commitment envelope; enqueue is separate from event persistence, so
there is an intentional crash window between the two operations.

`enqueue`, `get`, `list_pending(limit)`, and `claim_due(now, limit,
claim_token)` are local SQLite operations. IDs conflict rather than overwrite.
Claims run inside a short `BEGIN IMMEDIATE` transaction with stable ordering by
availability time and ticket ID. A claim means only that one local consumer
reserved the ticket; it says nothing about submission or confirmation. No
network work happens inside the transaction.

Claims have no lease or automatic recovery in this MVP. If a process crashes
after committing a claim, that ticket remains claimed and requires an explicit
future recovery design. This table does not add retries, a publisher, dedupe,
or a delivery guarantee.
