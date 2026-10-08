# SC-4 Red Team Report

Status: PASS for the cases exercised by local tests and static policy checks; no remote GitHub or external chain oracle was available.

No permanent regression was introduced. The table records the current control and its limit.

| Adversarial case | Control / evidence | Result and boundary |
|---|---|---|
| Convergence without ground truth is called accurate | Existing dynamic localization tests are in SCIENTIFIC; invariant map requires ground-truth scoring | Automated test coverage is wired; no claim promotion occurs from convergence alone |
| PHY receive is reported as application delivery | Event V1 and adapter contract tests are in SCIENTIFIC | Contract regression coverage; no physical radio capture was made |
| Weak RF profile or simulated network is represented as field truth | Farm RF/network tests and provenance classification rules | Simulated evidence remains SIMULATED; no field validation |
| Claim has stale source SHA or mismatched source tree | Evidence validator resolves commit tree and compares recorded tree | Negative policy tests reject mismatch |
| Evidence artifact, configuration, or patch was modified | SHA-256 checks over repository-contained artifacts/config and exact base-to-tested diff | Negative policy tests reject tampered hashes |
| Claim references missing or differently classified evidence | Claim/evidence ID link validation enforces exact class agreement | Negative policy tests reject missing/mixed evidence |
| Mock/local EVM is promoted to REAL_ON_CHAIN | Validator forbids mock/local/Ganache/Anvil and requires network, chain ID, verified receipt, and hashed receipt artifact | Negative policy tests reject mock/local and incomplete Base Sepolia evidence; validator is not an independent chain oracle |
| Local simulation is promoted to measured lab or field | Validator requires physical capture/reviewer or field run/protocol/reviewer provenance | Negative policy tests reject missing provenance |
| Heavy interface uses external/unbounded target backend | Interface rejects testnet/Sepolia/devnet, RPC/public chain, Ganache/Anvil, field/hardware and similar backend labels | Policy tests reject public-chain and physical backends; interface emits only REQUEST_ONLY |
| Heavy request uses caller-supplied or missing config hash | Config hash is calculated from a repository-contained config file; absent config is unavailable | Policy tests confirm calculated hash and reject external config paths |
| Unknown pytest skip is silently accepted | Skip governance defaults to UNEXPLAINED and blocks unknown/environment/external/regression classes | Policy test confirms unknown skip is a failure; full suite reported zero skips |
| Workflow permissions or third-party action trust expands | Static workflow policy checks read-only permissions, pinned action SHAs, no checkout credentials, no secrets, and no untrusted shell interpolation | Fast gate policy tests passed; GitHub-hosted execution and branch protection were not available |

Residual red-team limits: repository-local tests do not prove a public chain receipt, field measurement, hardware operation, or protection-rule enforcement. Branch protection and remote CI remain NOT_VERIFIED/NOT_EXECUTED.
