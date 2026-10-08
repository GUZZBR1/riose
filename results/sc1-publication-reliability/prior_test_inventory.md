# Existing SC-1 Test Coverage

Discovery was performed against `fork/main` b2ddf11098ecd87b954bf97af26f8ecb8862b58a. The independent read-only coverage pass inspected the same SHA/tree in `/home/gusta/projetos/RIOSE/riose-sc2-security-dependencies`; that checkout is branch `software-closure/sc2-security-dependencies`, clean, and was left untouched.

## Coverage already present

- `test_publication_outbox.py`: atomic/idempotent queue across restart; canonical commitment reuse across targets; failed target isolation; transaction/receipt correlation and append-only guarantees; atomic event + intent; exact persisted attempt; DB reopen and migrations.
- `test_publication_dispatcher.py`: exact payload persistence/replay; reconcile from confirmed; ambiguity and receipt timeouts; target isolation; malformed receipt handling; safe retry evidence; claims and same-target serialization across Store connections.
- `test_publication_cli.py`: unknown send resumes with same signature; confirmed request can be reconciled after an injected interruption before VERIFIED.
- `test_commitment_privacy.py`: Commitment V1 golden vector, determinism, source/subject binding, privacy envelope, and parser failures.
- `test_solana_memo.py`: signed memo shape, explicit cluster, exact commitment observation, malformed response as unknown, persisted payload restart, sanitized RPC and signer errors.
- `test_evm_nonce.py`: reservations across Store connections and processes, shared nonce scope for same-chain contracts, Arbitrum ordered send/lease/replay and stale/unpersisted reservation recovery.
- `test_evm_registry.py` and `test_evm_local.py`: shared EVM adapter/config, receipt correlation, malformed receipts, local deployment/send/revert, and one-event fanout to mocked Solana + local EVM Base/Arbitrum targets.
- `test_event_chain_concurrency.py`: event-chain concurrent writers, process writer termination, SQLite reopen, rollback and hash verification.

## Gaps SC-1 must close

1. The existing `CONFIRMED`→`VERIFIED` recovery test injects a Python exception and reopens persistence; it does not hard-kill the process at the durable receipt boundary.
2. There is no forced process death after possible RPC acceptance but before durable `RPC_ACCEPTED`, or after attempt persistence but before submit. Existing tests model recovery with ordinary exceptions or pre-seeded states.
3. Same-publication dispatcher contention is covered with multiple Store connections in threads, not simultaneous independent publisher processes.
4. EVM ordered submission is covered specifically for Arbitrum. Base has reservation uniqueness but no equivalent sender submission-order lock test.
5. The three-target EVM fanout uses local EVM instances and a mocked Solana adapter; it is software simulation, not public-chain evidence.
6. The retry tests prove explicit `safe_to_retry` gating, but there are no retry caps, due-time scheduling, exponential backoff, or jitter tests.
