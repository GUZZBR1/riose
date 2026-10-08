# Independent Red Team Report

## Outcome

The independent post-implementation red-team review found no unresolved material bypass among the exercised cases. It verified that the reported bypasses reject on the updated tree.

## Attack paths exercised

- Solana keypair path permissions, symlink/dangling symlink, directory/FIFO, oversized/trailing/malformed data, and descriptor path replacement.
- EVM signer special files/trailing bytes and persisted transaction priority-fee cap.
- Solana RPC duplicate object keys, invalid JSON constants, deep nesting, and transaction signature substitution.
- Event payload duplicate keys across chain verification, outbox binding, and enqueue.
- Commitment V1 digest/source/subject mutation and public envelope schema mutation.
- EVM receipt mutations: sender, transaction hash, removed log, commitment/publisher topic, log payload, block hash, and calldata.
- Exception redaction and static secret-pattern scan.

## Fixes resulting from red-team review

The review found four bypass classes after initial fixes: Event/outbox parser disagreement on duplicate keys; EVM signer acceptance of trailing bytes/FIFO; EVM priority fee above configured cap; Solana RPC duplicate keys and a wrong returned transaction signature. All were corrected and targeted tests/probes passed.

## Limits

No live RPC or public chain was attacked. Native Windows ACL handling, hostile concurrent filesystem writes, broad dependency exploitability, and remote freshness were not established. Dependency advisory matches are retained as tooling residuals rather than claimed exploitable product vulnerabilities.
