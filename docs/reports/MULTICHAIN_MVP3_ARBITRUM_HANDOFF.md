# Arbitrum handoff from the shared EVM core

Status: configuration/deployment handoff only. No Arbitrum transaction or public-chain validation was performed.

Use the same `EVMRegistryAdapter`, `EVMNetworkConfig`, Solidity source, dispatcher, Store, and canonical commitment as the local test and Base handoff. Deploy the registry with the intended publisher as immutable constructor argument. Only deployment/network configuration changes; do not create an `ArbitrumAdapter` or a second commitment format.

Create deployment JSON with `chain` (for example `arbitrum`), numeric `chain_id`, `expected_genesis_hash`, HTTPS `rpc_url`, `contract_address`, `expected_code_hash` of deployed runtime bytecode, `publisher_address`, `confirmations`, `gas_limit`, `max_fee_per_gas_wei`, `max_priority_fee_per_gas_wei`, and optional `explorer_tx_url`. Source these values and the confirmation/finality policy from the selected Arbitrum environment at execution time. The local Ganache gas values are diagnostic only and are not an Arbitrum fee quote. A private key remains in an owner-readable `0600` file outside version control.

Queue/process/reconcile through the existing `cattle-rf publication` commands and `--evm-config`; only `process` of a new attempt needs `--evm-key-file`. The target identity includes chain ID, pinned genesis and contract address; the nonce scope is chain ID/genesis plus signer. A commitment anchored on another chain can be queued independently for this deployment without rehashing Event V1.

Before a public claim: verify the chain/genesis and runtime code, immutable publisher, signer funding, current fee model and finality policy, then submit and independently inspect a real receipt and matching event/log. Single-RPC observations remain `ASSUMED`; configured-depth confirmation cannot guarantee against later reorganization. Arbitrum public on-chain status remains **UNVERIFIED**.
