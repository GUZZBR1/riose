# RIOSE Multichain Final Integration: compiled DoD

Mission: reconcile M3, Base M4A, and Arbitrum M4B into one local candidate.
Integration base: `60bbb7f29bc98cf5c69caf798276929c859c8d2f`.
Branch: `multichain/final-integration`. Recovery ref created before integration:
`recovery/multichain-final-preintegration` -> M3.

## Baseline, anti-duplication, and direct Git evidence

| Authority | SHA | Parent | Change set directly observed |
|---|---|---|---|
| M3 | `60bbb7f29bc98cf5c69caf798276929c859c8d2f` | M2 | Shared Event V1, canonical SHA-256 commitment, generic dispatcher/outbox, Solana adapter, generic EVM registry/config, local contract and tests |
| M4A Base | `df9d281dffb56b33047dd56837acb320fd58cef8` | M3 through `1fc1193861ee50d16fc9c4a4308b6be1c21bb25b` | `MULTICHAIN_MVP4A_BASE_DOD.md`, focused Base identity test; no production EVM source change |
| M4B Arbitrum | `65a70357513d137390a6e97a95a75e966a870c73` | M3 `60bbb7f` | Arbitrum DOD and M3 handoff correction; generic EVM config/adapter/nonce/CLI changes and EVM tests |

Anti-duplication decisions (pre-integration):

| Concern | Decision | Reason |
|---|---|---|
| Event V1 and canonical commitment | REUSE | Both M4 candidates retain the M3 domain and exact commitment bytes. |
| Solana adapter and dispatcher | REUSE | No M4 candidate changes Solana or generic dispatcher behavior. |
| Shared EVM adapter/config/contract | MERGE M4B onto M3 | Arbitrum added generic deployment checks, gas estimate, and nonce send ordering; no second adapter/contract is needed. |
| Base-specific implementation | REUSE M4A test/evidence only | M4A verifies Base Sepolia identity through the shared config and adds no Base production adapter. |
| Arbitrum-specific config constraints | ADAPT after review | Keep named network checks at EVM configuration boundary; keep domain/dispatcher chain-neutral. Verify Base and Arbitrum profiles side by side. |
| Duplicate EVM branch tests | MERGE | M4A and M4B edit `test_evm_registry.py`; preserve both test intents and avoid dropping coverage. |
| Conflicting docs | ADAPT | Preserve historical M4 reports; add a final reconciliation report and only correct demonstrably wrong current wording with an auditable erratum. |

M4A and M4B are sibling branches with M3 as their Git merge base. M4B does not
contain the M4A Base report or Base-specific identity test.
M4B's production changes are generic to the EVM layer. No branch will be
merged blindly; cherry-picks and any conflict resolutions are reviewed against
the source diffs and tests.

## Trust boundaries and evidence impact

1. Persisted Event V1 and M3 canonical commitment are authoritative. Each of
   the Solana, Base, and Arbitrum targets must reuse the same digest; only
   transport encoding may vary.
2. Network config/RPC are untrusted. Check configured chain ID, genesis,
   contract code and immutable publisher. Base and Arbitrum config identities
   must not be accepted from chain ID alone.
3. Signer files remain outside Git, logs, receipts and SQLite. Signed EVM wire
   is validated and replayed exactly; no automatic re-sign/replacement.
4. Receipt and event data are RPC claims; keep evidence `ASSUMED` unless an
   independent verifier is actually used. L2 depth does not prove L1 finality.
5. SQLite nonce reservations coordinate workers only when they share the same
   Store/database. Separate local databases cannot see each other's rows;
   document this boundary and do not claim cross-database protection.
6. Local EVM, mocked Solana and public-chain transactions are separate evidence
   classes. This mission does not require public writes.

Evidence possibly invalidated by M4 integration: generic EVM config/adapter,
receipt validation, nonce reservation and ordering, CLI network routing, EVM
tests, Base identity test, Arbitrum tests, full Python suite, contract/local
EVM evidence, and M3/M4 reports. Solana/domain/persistence evidence is retained
only after final regressions demonstrate no incompatible changes.

## Compiled gates

| ID | Required outcome | Evidence | Status |
|---|---|---|---|
| F1 | Isolated candidate at M3 with recovery ref, no main/upstream mutation | Git refs/status/worktree | PASS at start |
| F2 | Direct M3↔M4A, M3↔M4B, M4A↔M4B semantic reconciliation | Git DAG/diffs; cherry-picks; Base publisher fixture reconciled | PASS |
| F3 | One shared EVM adapter/config/contract; no duplicate Base/Arbitrum adapters or domain logic | Final source/diff audit | PASS: one adapter/config/contract; chain-ID-specific gas/nonce behavior remains an adaptation risk |
| F4 | Same canonical commitment for one Event V1 across three independent targets | Eight three-target scenarios assert one persisted commitment for Solana, Base, and Arbitrum | PASS |
| F5 | Three-chain E2E, using mocked/local backends as available; state/receipt independence | Local Ganache instances on chain IDs 84532/421614 plus mocked Solana; one event, three VERIFIED targets and separate receipts | PASS_SIMULATED_OR_LOCAL |
| F6 | Partial failure matrix, all chains unavailable included; Event V1 remains valid | Eight fake-RPC/mock scenarios: success, each single failure, each double failure, and all unavailable; event binding retained | PASS; local three-target success E2E also passed |
| F7 | Recovery, retries, duplicate dispatch, Solana PREPARED, EVM signed raw replay, worker contention | Solana PREPARED restart exact-wire test; EVM pending-nonce-advanced exact-wire test; generic restart/duplicate tests; two-process nonce reservation and worker contention tests | PASS |
| F8 | Reorg/finality finding assessed without unsupported certainty | Test preserves CONFIRMED if receipt disappears before VERIFIED; dispatcher/code and M4 reports audited | PASS_WITH_LIMITATION: post-VERIFIED deep reorg is not detected |
| F9 | Nonce safety across shared DB processes, contracts/targets, and network IDs; separate DB limit explicit | Two-process shared-DB reservation, same-chain multi-contract scope, Base/Arbitrum same-signer fanout, restart and ordering tests | PASS_WITH_LIMITATION: separate SQLite files do not coordinate |
| F10 | Base Sepolia 84532 and Arbitrum Sepolia 421614 validated against configured genesis and RPC | Identity/config tests plus recorded read-only chain/genesis evidence in M4A/M4B reports | PASS: identity is chain ID + genesis + contract/code/publisher; no current public write |
| F11 | Privacy, signer, RPC, deployment, replay, duplicate, malformed-receipt and tooling-security audit | Independent read-only red team; malformed reverted logs and CLI exception leaks fixed with tests; exact npm audit package list and path classes below | PASS_WITH_LIMITATION: native Windows signer ACL policy is not independently enforced |
| F12 | Historical Base/Arbitrum claims consistent; typo search reported without erasing history | Exact report-source inspection | PASS: suspected phrase not found in checked Arbitrum reports |
| F13 | Full regression, contract/local EVM, build/lock/dependency, clean detached checkout | 839 passed / 7 skipped on candidate and detached HEAD; Ganache contract and three-chain local/mock E2E; compileall/solc compile; locked npm install/audit | PASS |
| F14 | Independent red team and Factory Eval Harness after integration | Independent review findings dispositioned; explicit Factory eval case passed after detached verification | PASS |
| F15 | Claims remain bounded; no public write without available safe signer/funding | No public writes, pushes or PRs; all simulated evidence labeled | PASS |

## Change-impact map and checkpoints

| Checkpoint | Work | Status |
|---|---|---|
| C0 | M3 authority, clean state, recovery ref | PASS |
| C1 | Compile this DoD, anti-duplication, branch graph and trust boundaries | PASS |
| C2 | Reconcile changes and integrate M4A/M4B commits | PASS; local recovery fix and Base fixture adaptation applied |
| C3 | Three-chain E2E and partial-failure/recovery/nonce/finality tests | Three-target local/mock success E2E, eight-case failure matrix, Solana/EVM restart tests, two-process nonce test and finality limitation test pass |
| C4 | Toolchain advisory triage and independent red team | PASS_WITH_LIMITATION; exact 38-package audit classified; red-team fixes landed; conditional Windows ACL limitation retained |
| C5 | Full suite/build, clean checkout, Factory Eval Harness | PASS; detached suite and compile passed; Factory evaluation PASS |

## Factory Eval Harness case

```yaml
case_id: multichain-final-three-target-reconciliation
scenario: One persisted Event V1 is published to Solana, Base Sepolia, and Arbitrum Sepolia with independently persisted target states.
input_state: M3 SQLite event/outbox and canonical SHA-256 commitment; one configured adapter per target.
expected_invariants:
  - Each target retains the exact M3 commitment and event binding.
  - Target attempt, receipt, failure, and recovery state are independent.
  - EVM prepared bytes are durable and replayed exactly; no silent re-signing.
  - No private event fields or signer material enter public payloads, receipts, or logs.
allowed_outcomes: [VERIFIED, CONFIRMED, RPC_ACCEPTED, UNKNOWN, RETRYABLE, REJECTED]
forbidden_outcomes:
  - A failure on one chain invalidates Event V1 or another target's state.
  - A recovery path changes a persisted signed EVM transaction.
  - Local/mock evidence is reported as public-chain validation.
trace_requirements: Event ID, commitment, three target IDs, adapter calls, attempt IDs, receipt observations, and recovery actions.
evidence_requirements: Combined E2E, partial-failure matrix, nonce/replay tests, full suite, local contract evidence, independent red-team report.
```

Eval result: **PASS**. The eight-case target matrix preserves the canonical
commitment and independent target states through one/two/all-chain failures;
the local three-chain success E2E verifies separate receipts; Solana PREPARED
and EVM signed-wire recovery tests pass; the finality boundary remains explicit;
the complete suite, contract compile/deploy and independent red-team fixes pass
on the final detached candidate.

## Red-team dispositions

- **Fixed:** status-0 EVM receipts must now contain a well-formed empty `logs`
  list; contradictory/malformed logs remain unknown rather than terminally
  rejected. Added parameterized coverage.
- **Fixed:** CLI catches sanitized `EVMRpcError`; a regression test confirms
  chained endpoint details and tracebacks do not reach stderr.
- **Accepted conditional limitation:** signer-file permission checks use
  POSIX mode bits and `O_NOFOLLOW`; production signer loading is documented
  for Linux/WSL. Native Windows ACL/reparse-point enforcement is not claimed.
- **Tooling audit:** `npm ci --force --ignore-scripts` installed the unchanged
  lockfile; `npm audit` returned 38 advisories (1 low, 8 moderate, 24 high,
  5 critical). Direct vulnerable packages are Ganache 7.9.2 (high) and solc
  0.8.37 (high). The 38 affected package names are `@microsoft/api-extractor`,
  `@microsoft/api-extractor-model`, `@microsoft/tsdoc-config`,
  `@rushstack/node-core-library`, `@rushstack/ts-command-line`,
  `@trufflesuite/uws-js-unofficial`, `ajv`, `argparse`, `bn.js`,
  `brace-expansion`, `braces`, `browserify-sign`, `browserslist`, `cipher-base`,
  `cross-spawn`, `diff`, `elliptic`, `ganache`, `js-yaml`, `json5`, `lodash`,
  `micromatch`, `minimatch`, `mocha`, `nanoid`, `pbkdf2`, `picomatch`,
  `secp256k1`, `semver`, `serialize-javascript`, `sha.js`, `solc`,
  `sprintf-js`, `terser-webpack-plugin`, `tmp`, `validator`, `webpack`, and
  `ws`. All are `DEV_TOOL_ONLY`; exposure when invoking the contract simulator
  or compiler is `BUILD_TIME_RISK`; none is `RUNTIME_PRODUCT_RISK` or reachable
  from the Python product package. No bulk upgrades were applied; the audit's
  Ganache remediation proposes a major-version change and is not a safe
  unreviewed fix.

Baseline evidence in the branch reports: M3 `814 passed / 7 skipped`, M4A
`815 passed / 7 skipped`, M4B `822 passed / 7 skipped`. These are historical
reports, not final-candidate evidence. On the final candidate, `839 passed / 7
skipped` across the complete Python suite in both the branch checkout and a
fresh detached worktree. Contract compilation passed in that detached
worktree. `test_evm_local.py` compiled and deployed the registry into Ganache,
dispatched a commitment, exercised duplicate/revert and exact-wire recovery,
and verified receipts. The three-chain E2E deployed the registry to two
isolated local EVMs configured with chain IDs 84532 and 421614 plus a mocked
Solana adapter, then verified three independent receipts against one
commitment. The locked npm install succeeded on the Windows host after WSL DNS
could not resolve the registry.
