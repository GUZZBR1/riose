# SC-3 reproducibility report

## Verdict

**reported_status: PARTIAL_IN_SCOPE**
**governed_status: PENDING_FACTORY_REVIEW**
**clean_room_status: PARTIAL_EXTERNAL_BLOCKED**
**remote_freshness: UNVERIFIED**

The isolated branch has a canonical locked bootstrap, doctor/preflight, dependency classification, local mock smoke, and clean-source build evidence. Current Python EVM/npm/Solidity gates remain blocked by DNS and missing cached artifacts. Independent red-team findings were corrected where locally actionable; the PEP 517 versions are now constrained.

## Verified

- The branch is based on local fork/main b2ddf11098ecd87b954bf97af26f8ecb8862b58a; live GitHub freshness remains unverified. The original dirty checkout was preserved.
- uv.lock check passes. Latest non-EVM Python regression on source 92ef1b5276096da9f01b5d6218207b9984e5471e: **855 passed, 7 skipped, 1 warning**. The Solana mock suite passed 15/15; full pytest collection fails in the two EVM modules because eth_account is unavailable.
- Four doctor regression tests pass. A real minimal-PATH doctor run reports missing optional Node/npm/CMake as OPTIONAL_MISSING and exits 0; a synthetic foreign riose import reports INCOMPATIBLE and exits 1. A mismatched local solc version also reports INCOMPATIBLE. The sanitized doctor run with the confirmed-network flag reports EXTERNAL_BLOCKED; its local EVM dependency check is OPTIONAL_MISSING. Without the flag, the doctor reports OPTIONAL_MISSING and does not probe registries.
- Two clean CMake build directories passed **39/39 CTest**; five trace files matched byte-for-byte.
- Two detached clean worktrees at source 92ef1b5276096da9f01b5d6218207b9984e5471e (tree bb87b9828d8681d63852cd2ea786dc41a0a35bf3) produced identical wheel and sdist hashes under exact PEP 517 version constraints. With core.autocrlf=true, 1,057 tracked text files checked out as LF. The online package command was blocked by current pypi.org DNS failure; two offline builds from the existing cache matched, while an explicitly empty offline cache correctly stopped because Hatchling 1.32.4 was absent. Builds used uv 0.11.26, Python 3.12.3, and the versions recorded in build-constraints.txt; the wheel imported from a fresh venv site-packages. The constraints pin versions but do not carry distribution hashes; fresh-network byte identity is not claimed. Earlier dirty-snapshot sdist evidence was superseded.
- Integrated mock smoke passed with a new temporary SQLite database, close/reopen, local mock submit, and receipt reconciliation to VERIFIED. REAL_ON_CHAIN=NOT_EXECUTED.
- Solidity compile commands in CI and README now pass the source file required by compile_registry.cjs. Execution remains blocked until npm installs solc.

## Open gates

- Latest git fetch could not resolve github.com; local fork/upstream refs diverge.
- The latest canonical bootstrap failed fetching eth-keys 0.8.0 after three DNS retries; npm ci failed resolving Ganache 7.9.2 with EAI_AGAIN. The online constrained package build also could not resolve pypi.org. Earlier empty-cache attempts confirmed missing wheel and tarball artifacts.
- Ganache, solc compilation, EVM Python tests, and local Solana validator tests were not run. No public network or real funds were used.
- Zephyr/west/SDK, Renode, CadQuery export, Gazebo/ROS, ngspice, openEMS, CSXCAD, and external RF campaigns remain outside the completed gates; FREQUENCIA remains external.
- The build backend and its transitive tool versions are now exact in build-constraints.txt. Empty-cache builds still require registry downloads, and the constraints do not pin per-distribution hashes.

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
HIDDEN_DEPENDENCIES_FOUND: Windows PATH pollution in WSL, external uv prerequisite, default persistent SQLite path, uncached EVM/npm packages, floating PEP 517 tool versions
HIDDEN_DEPENDENCIES_FIXED: locked bootstrap/operations, import-origin enforcement, optional-tool doctor statuses, local Ganache/solc lock checks, constrained PEP 517 tool versions, build input hashing, correct Solidity argv, temporary database smoke
BOOTSTRAP: current source core/dev/Solana offline install PASS; full canonical bootstrap EXTERNAL_BLOCKED fetching eth-keys 0.8.0 after DNS retries
DOCTOR: EXTERNAL_BLOCKED with the confirmed-network flag; EVM dependency check OPTIONAL_MISSING; doctor regression tests 4/4 PASS
PYTHON: latest non-EVM regression 855 passed, 7 skipped; full collection blocked by missing eth_account; Solana mock tests 15/15 PASS
NODE_NPM: lock/version checks PASS; current source npm ci EXTERNAL_BLOCKED fetching Ganache 7.9.2 with EAI_AGAIN
SOLIDITY: locked solc 0.8.37; compile command fixed; execution blocked because node_modules is absent
FIRMWARE_BUILD: fresh source-92ef1b5 CMake/CTest 39/39 in two directories; Zephyr target not configured
OPTIONAL_DEPENDENCIES: classified in dependency matrix and firmware report
LOCAL_BLOCKCHAIN: local-mock integrated smoke PASS; Ganache gate blocked
CACHE_STATUS: PARTIALLY_CACHED
SECOND_PASS: cached second Python venv and CMake build passed; latest clean source suite 855/7; package builds repeated with identical hashes; full EVM pass not achieved
INTEGRATED_SMOKE: PASS with synthetic event and mock receipt; REAL_ON_CHAIN=NOT_EXECUTED
TESTS: bootstrap partial; doctor 4 passed; Solana mock 15 passed; non-EVM Python 855 passed, 7 skipped; full Python blocked at EVM collection; CMake/CTest 39/39 twice; npm/Solidity/EVM blocked; wheel/sdist matched twice from clean source; compileall PASS
RED_TEAM: independent native read-only audit completed; actionable findings fixed; build versions constrained and cache/hash limits disclosed
REAL_ON_CHAIN: NOT_EXECUTED
CLAIMS: cached core regression; repeatable CTest traces and package artifacts under observed cached tools; semantic local mock smoke; no full clean-room/public claims
LIMITATIONS: DNS failures, diverged stale refs, EVM/npm dependencies unavailable, build constraints lack per-distribution hashes, optional external toolchains absent
EVIDENCE_PATH: reproducibility/
GIT_STATUS: clean after evidence commit; original checkout preserved
FACTORY_REVIEW_READY: YES
