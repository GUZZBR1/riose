# SC-5 red-team review

- Testnet identity: **not observed**. All three public endpoint lookups failed at DNS before a JSON-RPC response.
- Mainnet isolation: **PASS locally**. Solana config allowlists Devnet/Testnet genesis identities; EVM prepare and submit fail closed except Base Sepolia, Arbitrum Sepolia, and loopback chain 31337. Regression tests passed.
- Transaction existence, success, and finality: **not applicable**; no transaction was prepared or submitted.
- Commitment equality: **PASS locally only**. One outbox canonical commitment produced equal target rows; no public commitment was verified.
- Signer address/security: **no signer available**; no address queried or secret read. Solana loader hardening is covered on WSL.
- Contract/program: Solana Memo program identifier is in the adapter. Base and Arbitrum deployment addresses and code are absent; remote state could not be queried.
- Receipt correlation: **not applicable**; no attempt or receipt exists.
- Mock evidence: none is presented as public evidence. Unit tests remain local software evidence.
- Privacy: **PASS for exact public payload**. Solana carries the allowlisted envelope; EVM carries the register(bytes32) selector plus commitment. Synthetic identifiers and event JSON are absent.
- Duplicate send/restart: no send occurred. Local outbox survived reopening; duplicate queue reused the same target request. No chain attempt could be reconciled.
- Claims: no public-testnet, production, field, or hardware claim was promoted.
- Platform limit: native Windows ACL behavior was not tested; RPC DNS and signer availability block public execution.
