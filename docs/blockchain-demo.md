# Offline blockchain vertical demo (MVP 16)

Run the complete synthetic flow with:

```sh
uv run cattle-rf blockchain-demo
```

The command creates a fixed synthetic event in a temporary SQLite database,
validates the local SHA-256 event chain, builds the guarded public commitment,
using a fixed synthetic local subject reference, submits it to the in-memory
fake adapter, stores a minimized receipt, and
checks it with the integrity verifier. It then alters the synthetic event
payload and shows the local verifier detecting the break. Output is stable
JSON and explicitly labeled `SIMULATED`; the fake confirmation does not
produce a public `VALID` anchor.

All database files are confined to a `TemporaryDirectory` and removed after
success or failure. The command does not open the normal application database,
call Solana/RPC, use credentials or SOL, or change the real adapter capability
from `FUTURE`. Solana remains an optional separate integration.
