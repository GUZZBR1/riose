# Mini-MVP 5 — Persistence & Reliability

## Verdict

**PASS_WITH_LIMITATIONS** for the tested local SQLite deployment contract. Independent local processes can append through the canonical `Store`/API paths without a fork in the tested 2, 4 and 8 writer configurations. This does not establish distributed-host or network-filesystem safety, unlimited writer capacity, power-loss behavior, or request-level idempotency for the event API.

| Field | Result |
|---|---|
| Canonical base | `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed` |
| Approved product tree | `bb9713f64467d498c4547bbe9bc1e32f5617dadf` |
| Branch | `mini-mvp/persistence-reliability` |
| Final implementation SHA | `e00726564f2d75d75086e44457e74cd6d15ab1ac` |
| Final branch HEAD | The report-only commit is reported in the final response; it contains no source changes after the implementation SHA above |
| Main modified | No |
| Push / PR | No / No |
| Python suite | 629 passed, 7 skipped |
| Multi-worker gate | `YES_TESTED` for local independent Store/API writers in the tested configuration |

## Workspace reconciliation checkpoint

- `PRE_RECONCILIATION_HEAD`: `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`.
- `ORIGINAL_BASE`: `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`.
- `MERGE_BASE`: same SHA; the mission worktree started exactly at the expected base.
- `CLASSIFICATION`: **A — CURRENT_BASE_CONFIRMED**. The local cached `fork/main` points to the expected canonical commit and its product tree matches the approved tree.
- `REMOTE`: `fork` (`GUZZBR1/riose`); fetch failed because `github.com` did not resolve in the environment. The cached local ref was inspected, but live remote state could not be revalidated.
- `LOCAL_WORK_PRESERVED`: Yes. The mission worktree was clean before source changes; there was no pre-existing mission work to recover. `RECOVERY_REF`: not applicable.
- `ALREADY_PRESENT`: SQLite WAL schema, event contract v1, animal creation transaction, additive legacy `schema_version` migration, behavior observation persistence/idempotency, API event writes and CLI demo persistence.
- `STILL_REQUIRED`: read-head/write serialization, actual spawned-process coverage, rollback and kill/reopen evidence, reliability reports and deployment gate. These items were retained in the mission.
- `SUPERSEDED_OR_CONFLICTING`: none identified in the canonical worktree. Other worktrees and branches were left untouched.
- Baseline was rerun after reconciliation: **617 passed, 7 skipped**. Python was run from the existing project environment because the mission checkout had no virtual environment of its own.
- `MAIN_MODIFIED`: No. `PUSH`: No. `PR`: No. `SAFE_TO_CONTINUE`: Yes.

## Persistence architecture map

| Component | Responsibility and paths | Boundary and integrity | Findings / action |
|---|---|---|---|
| `Store` (`adapters/persistence/sqlite_store.py`) | One SQLite connection per Store; local livestock profile, event log, simulation telemetry/positions, metrics, behavior observations | Per-instance `RLock`; WAL; foreign keys enabled on its connection | Reused the existing store. Added write serialization to event append and explicit rollback for the multi-table `save_episode` operation. |
| `animal_events` / `identity.py` | Event append, canonical event bytes and local chain verifier | Per-animal order is `event_id`; `previous_hash` links to the preceding row; SHA-256 over frozen v1 canonical bytes | `BEGIN IMMEDIATE` now covers head read, verification, digest calculation and insert for an append that owns its transaction. An existing caller transaction must already be write-serialized (the production `create_animal` caller uses `BEGIN IMMEDIATE`). |
| Animal registration | API `POST /api/animals`, `Store.create_animal`, CLI demo seeding | `BEGIN IMMEDIATE` groups animal row with `ANIMAL_CREATED`; rollback on error | Existing atomic behavior retained and regression-tested. |
| Behavior observations / predictions | API behavior route and `Store.save_behavior_observation`; prediction observations share this model | Unique `(animal_id,idempotency_key)`, `BEGIN IMMEDIATE`, exact retry returns existing record; conflicting retry raises and maps to HTTP 409 | Existing model/version/source/evidence provenance persists and survives reopen. This is not coupled to the event chain in the canonical design. |
| Simulation episode | CLI `demo` / API simulation: telemetry, estimates/positions, optional debug truth | `save_episode` now groups its table writes in one immediate transaction and rolls back on any stage failure | `save_anchors`, `save_episode`, metrics and demo animal seeding are separate caller-level operations; a complete simulation run is not one all-or-nothing transaction. |
| API event route | Validate animal, call Store append, return event data and local chain verification | Store commits before returning; API verifies after append | Valid event write and chain verification are tested. No event idempotency key exists; request retries append distinct events. |
| CLI persistence | `cattle-rf demo --db` saves simulation artifacts and ensures animals through the same Store | Store-managed transactions; reopening sees the saved rows | CLI smoke test covers the write and reopen path. CLI has no separate event-chain writer. |
| Migrations | `SCHEMA` uses `CREATE TABLE/INDEX IF NOT EXISTS`; constructor adds nullable `animal_events.schema_version` when absent | Idempotent startup DDL; old rows remain NULL and keep old hashes | No declared migration version table or supported migration matrix exists. Legacy migration and restart are tested; interruption at each DDL statement was not injected. |
| Publication / blockchain | No publication outbox in this persistence adapter | Separate publication authority remains outside this mission | No second chain or publication model was added. |

No second database, event chain, observation store, identity model or migration framework was introduced.

## SQLite configuration and transaction model

Runtime inspection of a fresh Store returned:

- `journal_mode=wal`
- `synchronous=2` (`FULL`)
- `busy_timeout=5000` ms; `sqlite3.connect` default connection timeout is 5 seconds
- `foreign_keys=1`

WAL permits concurrent readers while SQLite still serializes writers. The defect was in the application’s read/compute/write sequence, not simultaneous physical writes: multiple independent processes could read the same event head before either insert acquired the writer lock. `BEGIN IMMEDIATE` acquires the write reservation before reading that head. A lock release test confirms the append waits on the configured SQLite busy timeout and continues after the existing writer commits. There is no application retry after the timeout expires.

`append_event` starts and owns an immediate transaction when called on a connection without an active transaction. It commits only when `commit=True`; errors roll back only a transaction it opened. `create_animal` already owns an immediate transaction and continues to call the append function with `commit=False`. A caller that passes an already-active transaction to the low-level helper is responsible for having opened it with a write-serializing mode; canonical Store/API write paths satisfy that contract.

`save_episode` now uses `BEGIN IMMEDIATE` around telemetry, positions and debug truth inserts. An injected positions insert error proved that the preceding telemetry insertion is rolled back and no transaction is left open.

## Event-chain semantics

- Genesis: 64 ASCII zeroes.
- Ordering: ascending SQLite `event_id`, not wall-clock time. A regression test appends equal timestamps followed by an earlier timestamp and confirms links still follow event IDs.
- Previous link: the most recent event hash for that animal, or genesis for an empty chain.
- V1 hashed fields: `animal_id`, `event_type`, `timestamp`, `payload`, `previous_hash`.
- Canonicalization: UTF-8 JSON, sorted keys, compact separators, `ensure_ascii=False`, `allow_nan=False`; payloads must be finite JSON-compatible objects with string keys.
- Digest: lowercase SHA-256 hex. The v1 canonical byte/digest vector remains frozen and unchanged.
- Not hashed: `event_id`, `schema_version`, and `signature`. Signature is a placeholder protocol and is not authenticated or verified.
- Persistence: digest is calculated and row inserted within the same immediate write transaction; the transaction commits before the Store call returns.
- Verification: recalculates every stored hash and link; unsupported non-NULL schema versions fail closed. An empty chain currently verifies true.

The verifier detects hashed-field changes, malformed payloads, an interior deletion and event reordering. It cannot prove completeness at the tail: deleting the last event, or deleting the whole chain, leaves no later link that can expose the truncation. A self-consistent rewrite by an actor able to edit the SQLite database is also outside the guarantee. A remote signature, immutable checkpoint or external head anchor would be needed for that stronger claim; this mission did not create one.

## Race reproduction and correction

Before the change, `append_event` selected the current hash before its first write, while `Store.append_animal_event` held only an instance-local `RLock`. Separate processes have distinct locks. A disposable two-process reproduction used a barrier after both head reads and before either insert: both observed the seed hash, both committed successfully with that same `previous_hash`, and the resulting log had a fork. The reproduction used an isolated temporary database and the same read/head/hash/insert sequencing; it did not touch repository data.

The correction reserves the SQLite writer lock before chain verification and head selection. After the correction, spawned independent processes exercise the actual Store append path against one database. No process lost writes, returned an unexplained SQLite error or left a fork at 2, 4 or 8 writers. Every final chain verified and every `PRAGMA integrity_check` returned `ok`.

## Reliability results

| Scenario | Attempted | Successful | Failed | Chain | SQLite integrity |
|---|---:|---:|---:|---|---|
| 2 independent processes × 40 writes | 80 | 80 | 0 | valid | `ok` |
| 4 independent processes × 40 writes | 160 | 160 | 0 | valid | `ok` |
| 8 independent processes × 40 writes | 320 | 320 | 0 | valid | `ok` |
| 8 threads, each with its own Store connection × 40 writes | 320 | 320 | 0 | valid | `ok` |

The 8-process case stresses one animal chain with simultaneous starts. An additional test holds a SQLite immediate lock, confirms a second Store waits, releases the first writer, and verifies the append. These are local correctness tests, not production throughput benchmarks.

The kill test starts a spawned writer, observes committed event rows, terminates the process during its append loop, reopens the database, runs SQLite integrity and chain verification, then appends another event. This validates process termination recovery and committed-row consistency. It is not a power-loss, disk-full or hardware durability test.

## Idempotency, API and CLI

- Behavior observation retry with the same `(animal_id,idempotency_key)` and identical values is a no-op returning the original row. Reusing the key with different values is an explicit conflict (HTTP 409). Values retain timestamp, behavior, confidence, model version, source, observation kind and evidence status.
- Event append has no request idempotency key. Repeating an identical `POST /api/events` is a new append, because the API contract models each call as an append command. Clients that may retry after a lost response can create a second event; this remains an in-scope limitation requiring a future explicit idempotency contract.
- Animal creation checks profile/event atomicity; duplicate identity maps to conflict. Event API checks animal existence, validates inputs, commits via Store and returns chain validity. Existing API tests cover valid and invalid writes; lock-timeout-to-HTTP behavior was not injected.
- The CLI demo smoke test ran `run_demo` with one animal/anchor and a temporary DB. It confirmed saved telemetry, positions, metrics and a valid animal event after reopening the database.
- Prediction observations use the existing behavior observation table with `observation_kind=PREDICTION`; there is no separate prediction persistence architecture in this scope.

## Migration, backup and recovery

Fresh schema creation, legacy schema without `schema_version`, additive migration, restart, event append after migration and unchanged legacy hash verification pass. The nullable marker intentionally preserves legacy rows; it is not a general migration version framework. Startup migration interruption was not directly injected, and arbitrary historical schemas are not claimed supported.

No backup/restore API or external recovery snapshot mechanism was found in this store. Recovery evidence here is SQLite transaction recovery after process termination and reopening the same local database. Operators remain responsible for backups appropriate to their deployment. No backup design was added.

## Red-team review

The review targeted the requested attack list: two readers sharing a previous hash; interpreting WAL writer serialization as read/write safety; process versus thread evidence; data loss and silent chain corruption; duplicate retries; post-commit acknowledgment; migration rerun; serialization stability; timestamp ordering; hashed-field tampering; deletion/truncation; WAL and busy timeout; publication/prediction architecture duplication; main and historical evidence modification.

- Two read-only focused subagent audits independently confirmed the race from source; one produced the deterministic two-process reproduction, and one mapped transaction and API/migration boundaries.
- A separate dedicated red-team agent could not start: the app rejected the configured subagent model as unsupported (HTTP 400). The primary agent completed the attack review, but this does not count as an independent red-team sign-off.
- Recovered in-scope gaps: race serialization, append-on-invalid-chain behavior (append now verifies the existing chain before extending it), and `save_episode` partial transaction rollback.
- Remaining gaps: event API retry idempotency, tail/full-chain truncation proof, interrupt-during-migration injection, power-loss/disk-failure simulation, busy-timeout exhaustion mapping, external backup/recovery, and dedicated independent red-team sign-off.

## Workspace and evidence integrity

The work used the isolated `mini-mvp/persistence-reliability` branch/worktree at the expected canonical base. The approved product tree matches the tree of the base commit. The remote fetch attempt failed at DNS resolution; the cached `fork/main` ref matched the expected SHA. Other worktrees, preservation refs, historical evidence, and the main worktree were left untouched. No push or PR was made.

The Python baseline was 617 passed / 7 skipped before changes. The final full Python run from a clean detached checkout at implementation SHA `e00726564f2d75d75086e44457e74cd6d15ab1ac` returned 630 passed / 7 skipped in 50.67 seconds. `compileall`, `git diff --check`, report/matrix JSON validation and final branch HEAD are recorded in the final response and test matrix.

## Knowledge Bus

See `MINI_MVP_PERSISTENCE_KNOWLEDGE_BUS.json`. Key downstream note: any consumer writing the same SQLite file must use the canonical Store event append contract; direct deferred transactions and retryable event API calls need explicit operational/request semantics. No new dependency is imposed on Mini-MVP 3 or 4; the Mini-MVP 6 Beta integration should preserve the tested local-process contract and surface the stated limitations.
