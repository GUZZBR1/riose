# SC-3 reproducibility report

## Verdict

**reported_status: PARTIAL_IN_SCOPE**
**governed_status: PARTIAL_IN_SCOPE**
**clean_room_status: PARTIAL_EXTERNAL_BLOCKED**
**remote_freshness: UNVERIFIED**

SC-3 produced a canonical locked bootstrap, doctor/preflight, environment/dependency evidence, local mock smoke, and repeatable host/package artifacts. It did not close the full clean-room objective: the EVM extras and npm dependencies require uncached packages while registry DNS is unavailable. The unfiltered Python regression therefore fails collection in the two EVM modules that directly import `eth_account`.

## What was verified

- A new isolated worktree was created on `software-closure/sc3-reproducible-environment` from the locally available `fork/main` ref `b2ddf11098ecd87b954bf97af26f8ecb8862b58a`. The original dirty checkout and its untracked files were preserved.
- `uv lock --check --offline` passed. The existing cache installed the project, Python core/dev dependencies, and Solana extra in two fresh virtualenvs; the remaining non-EVM suite passed **851 tests with 7 skips in each environment**. `compileall` passed.
- Two clean host CMake build directories each passed **39/39 CTest**. Five generated trace files matched byte-for-byte.
- Wheel and sdist built twice offline with identical SHA-256 hashes. The wheel installed into a new temporary virtualenv and `riose` imported from that virtualenv's `site-packages`.
- The integrated mock smoke passed with a new temporary SQLite database: synthetic Event V1, persistence, Commitment V1, publication queue, close/reopen, local mock submit, and receipt reconciliation to `VERIFIED`.
- `contracts/package-lock.json` was normalized by npm, root dependencies and engines match `package.json`, and the lock-only offline check passed. The live `npm ci` could not download Ganache because registry DNS returned `EAI_AGAIN`.

## Work added

- `scripts/bootstrap.sh` makes `uv sync --locked` the only Python bootstrap path; `setup.sh` is a compatibility wrapper.
- `scripts/doctor.sh` and `scripts/reproducibility.py` check lockfiles, interpreter/tool versions, import provenance, optional tools, and generate a machine-readable environment manifest. Doctor never probes registries or prints secret values.
- `.nvmrc` and `contracts/package.json` pin the Node/npm test environment. CI now installs the locked Node/npm and Python EVM dependencies and compiles the registry.
- Operational `uv run`/`uv sync` entrypoints enforce the lock.
- `scripts/integrated_smoke.py` exercises existing Event/SQLite/Commitment/outbox/mock-adapter capabilities without adding a public-chain path.
- `reproducibility/` contains discovery, dependency matrix, environment, run, cache, artifact, red-team, claims, and limitation evidence.

## Open gates

- Live fetch could not resolve `github.com`; local `fork/main` and `origin/main` refs diverge, so the remote base remains unverified.
- Full Python test collection and EVM tests need the missing `cytoolz==1.1.0`/`ckzg==2.1.8` and installed npm packages. `npm ci` returned `EAI_AGAIN` and empty-cache installation returned `ENOTCACHED`.
- Solidity compile, Ganache execution, and full clean-room second pass remain unverified.
- Zephyr/west/SDK, Renode, CadQuery export, Gazebo/ROS, ngspice, openEMS, CSXCAD, and Sionna/FREQUENCIA campaigns were not run. FREQUENCIA remains external.
- No independent subagent red-team review was available; the primary agent completed the checklist and records the limitation.

No public chain or real funds were used. The mock smoke and local CTest are not public or physical validation. Evidence inventory and hashes are in `manifest.json`.

## CODEX_TO_FACTORY_PACKET

MISSION: SC-3 Reproducible Environment & Clean-Room Build
REPOSITORY: GUZZBR1/riose
BASE_SHA: b2ddf11098ecd87b954bf97af26f8ecb8862b58a
FINAL_SHA: supplied in the delivery message; evidence commit contains this packet
BRANCH: software-closure/sc3-reproducible-environment
TREE: clean after evidence commit
REMOTE_FRESHNESS: UNVERIFIED
REPORTED_STATUS: PARTIAL_IN_SCOPE
CLEAN_ROOM_STATUS: PARTIAL_EXTERNAL_BLOCKED
REPRODUCIBILITY_LEVEL: WORKS_ON_CURRENT_MACHINE
DEPENDENCY_MATRIX: reproducibility/dependency_matrix.json
HIDDEN_DEPENDENCIES_FOUND: Windows PATH pollution in WSL, globally installed uv prerequisite, demo default SQLite state path, missing EVM/npm cache artifacts
HIDDEN_DEPENDENCIES_FIXED: locked canonical bootstrap, no pip fallback, locked operational uv invocations, Node/npm pin, CI EVM setup, import-origin doctor, temp DB smoke
BOOTSTRAP: core/dev/Solana offline install PASS; complete EVM bootstrap EXTERNAL_BLOCKED
DOCTOR: EXTERNAL_BLOCKED for uncached registry/EVM dependencies; report at reproducibility/doctor_report.json
PYTHON: lock consistency PASS; 851 passed, 7 skipped in two venvs excluding two EVM modules; package builds bitwise matched
NODE_NPM: version/lock checks PASS; npm ci EXTERNAL_BLOCKED by EAI_AGAIN
SOLIDITY: solc 0.8.37 locked; compile not run because node_modules absent
FIRMWARE_BUILD: CMake/CTest PASS 39/39 twice; Zephyr target not configured
OPTIONAL_DEPENDENCIES: classified in dependency matrix and firmware report
LOCAL_BLOCKCHAIN: local-mock integrated smoke PASS; Ganache gate blocked
CACHE_STATUS: PARTIALLY_CACHED
SECOND_PASS: core/dev/Solana install and 851-test run, host CTest, mock smoke, wheel/sdist repeated; full EVM dependency pass not achieved
INTEGRATED_SMOKE: PASS with simulated event and mock receipt; `REAL_ON_CHAIN=NOT_EXECUTED`
TESTS: bootstrap partial; focused/core suite 851 passed + 7 skips excluding EVM modules; full Python collection blocked; CMake/CTest 39/39 twice; EVM/Solana-public/Solidity/npm live gates external-blocked; wheel/sdist and compileall PASS
RED_TEAM: primary-agent checklist PARTIAL; no independent review available
REAL_ON_CHAIN: NOT_EXECUTED
CLAIMS: cached core test reproduction, repeatable CTest traces and Python packages, semantic mock smoke; no full clean-room or public claims
LIMITATIONS: DNS failure, divergent stale refs, EVM/npm packages unavailable, optional external toolchains absent
EVIDENCE_PATH: reproducibility/
GIT_STATUS: clean after evidence commit; source checkout unmodified except shared Git refs/worktree metadata
FACTORY_REVIEW_READY: YES
