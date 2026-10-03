# Publication receipts (MVP 13)

`PublicationReceipt` is a versioned, immutable observation record. It stores a
commitment digest, destination/network, optional external reference, normalized
status, observation time, source, and evidence level. It has no animal id,
event payload, memo body, credential, or secret field.

The SQLite receipt table is additive and opt-in through
`Store(..., enable_publication_receipts=True)`. It is separate from both the
animal event chain and publication outbox. Rows are append-only: an exact
duplicate receipt id is idempotent, changed content under that id conflicts,
and a later observation uses a new receipt id. `SUBMITTED`, `CONFIRMED`,
`REJECTED`, `UNKNOWN`, and `UNAVAILABLE` remain distinct. A receipt records
what its source reported; its source/evidence fields do not imply authenticity
or finality.

Reopening the database preserves the receipt without modifying existing event
rows. The repository itself performs no RPC, publication, retry, or polling.
