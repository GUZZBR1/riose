# Optional Solana Memo adapter (MVP 12)

`SolanaMemoPublicationAdapter` implements the chain-neutral publication port
for the SPL Memo program. It emits exactly one Memo instruction containing the
canonical public envelope (`version`, `algorithm`, `commitment`) from the
privacy guard. Animal records, event payloads, identifiers, and signer secrets
are not accepted by the adapter.

The adapter is opt-in. Construction requires an RPC URL, descriptive cluster
label, fee payer public key, and expected genesis hash; no endpoint or mainnet
setting is selected by default. Each submit and lookup checks `getGenesisHash`
against that configured value, and the machine network scope is derived from
the full expected hash (not the operator's human cluster label). The label is
for display only; the configured genesis hash is the network identity. A
mismatch stops before transaction submission. The official Solana
Memo program is documented in the [Memo transaction cookbook](https://solana.com/developers/cookbook/transactions/add-memo).

Solders is an optional dependency (`uv sync --extra solana`) used to compile
and parse the versioned transaction. `AnchoringSignerPort` signs the exact
compiled message, and the injected verifier checks that signature before RPC
submission. The adapter checks the RPC-returned transaction signature and
message against the public key, Memo program, exact single instruction, and
requested commitment before reporting an observation.

Lookup requests transaction data at `processed` so the Memo can be correlated
before finality. It reports `SUBMITTED` below the configured commitment and
`CONFIRMED` only when the RPC status has a sufficient level and explicit
`err: null`; an absent transaction is `UNAVAILABLE`, never proof that it was
not accepted. This follows Solana's [`getTransaction`](https://solana.com/docs/rpc/http/gettransaction),
[`getSignatureStatuses`](https://solana.com/docs/rpc/http/getsignaturestatuses),
and [`getGenesisHash`](https://solana.com/docs/rpc/http/getgenesishash)
contracts. RPC observations are labeled `ASSUMED`: the response is checked,
but RIOSE does not run a light client or independently prove consensus.

The HTTP transport uses a fixed timeout, response-size limit, and JSON-RPC
request-id validation. Tests inject an offline RPC fake and a test-only
Solders keypair; they do not contact a Solana cluster. No devnet smoke test or
real transaction was performed. Production signing, endpoint credentials,
fees, and deployment remain outside this MVP.
