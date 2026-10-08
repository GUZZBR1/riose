# SC-3 reproducibility report

## Verdict

**reported_status: PARTIAL_IN_SCOPE**
**governed_status: PARTIAL_IN_SCOPE**
**clean_room_status: PARTIAL_EXTERNAL_BLOCKED**
**remote_freshness: UNVERIFIED**

The isolated branch has a canonical locked bootstrap, doctor/preflight, dependency classification, local mock smoke, and clean-source build evidence. Full EVM/npm/Solidity gates remain blocked by DNS and missing cached artifacts. Independent red-team findings were corrected where locally actionable.

## Verified

- The branch is based on local fork/main b2ddf11098ecd87b954bf97af26f8ecb8862b58a; live GitHub freshness remains unverified. The original dirty checkout was preserved.
- uv.lock check passes. Latest non-EVM Python regression on source 97aeeacf1878f0d12a4b4b518a4c3c529f35841e: **854 passed, 7 skipped, 1 warning**. The full suite fails collection because two EVM modules import unavailable eth_account.
- Three doctor regression tests pass. A real minimal-PATH doctor run reports missing optional Node/npm/CMake as OPTIONAL_MISSING and exits 0; a synthetic foreign riose import reports INCOMPATIBLE and exits 1. A mismatched local solc version also reports INCOMPATIBLE. The actual doctor reports EXTERNAL_BLOCKED because EVM packages are absent and registry access is unavailable.
- Two clean CMake build directories passed **39/39 CTest**; five trace files matched byte-for-byte.
- Two detached clean worktrees at source ada955dd4238dad6f6d614f2520d058fb6edeaf7 (tree c973a8bd7b4cebd8f257f4fe2f002d9da76d81bc) produced identical wheel and sdist hashes. Fresh checkout with core.autocrlf=true kept shell scripts and reproducibility JSON/Markdown on LF; bash -n passed and doctor.sh ran through its shebang. An empty-cache offline build failed at the unpinned hatchling dependency. Builds used uv 0.11.26, Python 3.12.3, and cached hatchling 1.32.4; the wheel imported from a fresh venv site-packages. The PEP 517 builder is not captured in uv.lock, so this is scoped cached evidence, not a fresh-network claim. Earlier dirty-snapshot sdist evidence was superseded.
- Integrated mock smoke passed with a new temporary SQLite database, close/reopen, local mock submit, and receipt reconciliation to VERIFIED. REAL_ON_CHAIN=NOT_EXECUTED.
- Solidity compile commands in CI and README now pass the source file required by compile_registry.cjs. Execution remains blocked until npm installs solc.

## Open gates

- Latest git fetch could not resolve github.com; local fork/upstream refs diverge.
- Canonical bootstrap could not fetch ckzg 2.1.8; empty cache also lacked EVM wheels. npm registry returned EAI_AGAIN, and empty-cache install returned ENOTCACHED.
- Ganache, solc compilation, EVM Python tests, and local Solana validator tests were not run. No public network or real funds were used.
- Zephyr/west/SDK, Renode, CadQuery export, Gazebo/ROS, ngspice, openEMS, CSXCAD, and external RF campaigns remain outside the completed gates; FREQUENCIA remains external.
- pyproject.toml still declares unpinned hatchling. Two clean cached builds selected hatchling 1.32.4 and matched, but the build backend is not locked for uncached fresh-network reproduction.

Evidence and the independent red-team dispositions are in this directory. manifest.json hashes the evidence files except itself.

## CODEX_TO_FACTORY_PACKET

MISSION: SC-3 Reproducible Environment & Clean-Room Build
REPOSITORY: GUZZBR1/riose
BASE_SHA: b2ddf11098ecd87b954bf97af26f8ecb8862b58a
FINAL_SHA: supplied in delivery message; evidence commit contains this packet
BRANCH: software-closure/sc3-reproducible-environment
TREE: clean after evidence commit
REMOTE_FRESHNESS: UNVERIFIED
REPORTED_STATUS: PARTIAL_IN_SCOPE
CLEAN_ROOM_STATUS: PARTIAL_EXTERNAL_BLOCKED
REPRODUCIBILITY_LEVEL: CACHED_REPRODUCTION
DEPENDENCY_MATRIX: reproducibility/dependency_matrix.json
HIDDEN_DEPENDENCIES_FOUND: Windows PATH pollution in WSL, external uv prerequisite, default persistent SQLite path, uncached EVM/npm packages, unpinned PEP 517 backend
HIDDEN_DEPENDENCIES_FIXED: locked bootstrap/operations, import-origin enforcement, optional-tool doctor statuses, local Ganache/solc lock checks, correct Solidity argv, temporary database smoke
BOOTSTRAP: core/dev/Solana cache install PASS; EVM extra EXTERNAL_BLOCKED on ckzg wheel DNS resolution
DOCTOR: EXTERNAL_BLOCKED for uncached EVM/network; doctor regression tests 3/3 PASS
PYTHON: latest non-EVM regression 854 passed, 7 skipped; full collection blocked by missing eth_account
NODE_NPM: lock/version checks PASS; npm ci EXTERNAL_BLOCKED by EAI_AGAIN
SOLIDITY: locked solc 0.8.37; compile command fixed; execution blocked because node_modules is absent
FIRMWARE_BUILD: CMake/CTest 39/39 twice; Zephyr target not configured
OPTIONAL_DEPENDENCIES: classified in dependency matrix and firmware report
LOCAL_BLOCKCHAIN: local-mock integrated smoke PASS; Ganache gate blocked
CACHE_STATUS: PARTIALLY_CACHED
SECOND_PASS: second Python venv and CMake build passed; post-review suite 854/7; clean source package builds repeated; full EVM pass not achieved
INTEGRATED_SMOKE: PASS with synthetic event and mock receipt; REAL_ON_CHAIN=NOT_EXECUTED
TESTS: bootstrap partial; doctor 3 passed; focused/non-EVM 854 passed, 7 skipped; full Python blocked at EVM collection; CMake/CTest 39/39 twice; npm/Solidity/EVM blocked; wheel/sdist matched twice from clean source; compileall PASS
RED_TEAM: independent native read-only audit completed; actionable findings fixed; unpinned PEP 517 backend remains disclosed
REAL_ON_CHAIN: NOT_EXECUTED
CLAIMS: cached core regression; repeatable CTest traces and package artifacts under observed cached tools; semantic local mock smoke; no full clean-room/public claims
LIMITATIONS: DNS failures, diverged stale refs, EVM/npm dependencies unavailable, unpinned build backend, optional external toolchains absent
EVIDENCE_PATH: reproducibility/
GIT_STATUS: clean after evidence commit; original checkout preserved
FACTORY_REVIEW_READY: YES
