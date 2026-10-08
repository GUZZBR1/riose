# SC-3 reproducibility report

## Governed verdict

reported_status: PASS_REPRODUCIBLE_WITH_LIMITATIONS
governed_status: PASS_WITH_FOLLOWUPS
mission_complete: YES (all required software gates)
clean_room_status: PASS_FOR_REQUIRED_SOFTWARE_GATES
remote_freshness: VERIFIED

The original mission scope and Definition of Done were recovered from its attached brief. All required local software gates pass at implementation baseline 081f6a55a5d4e66724809d02ca3ec89313ba1ad1. Dependency versions, lockfiles, implementation code, upstream, and the original dirty checkout were preserved. The live branch remotes diverge; no merge, integration, or publication was requested or performed.

## Evidence

- Network: WSL DNS through the configured Tailscale resolver returned SERVFAIL. Windows host access to GitHub, official npm, and official PyPI worked. A temporary allowlisted HTTPS bridge enabled canonical fresh downloads and was removed after recovery. Verified refs: fork/main b2ddf11098ecd87b954bf97af26f8ecb8862b58a and origin/main c85c5f9bacf8065ceae95d45f173ad18418e5fda (diverged, 84 vs 1 unique commits).
- Python: uv lock --check --offline resolved 68 locked packages. A fresh isolated cache and environment installed core/dev/Solana/EVM extras, including exact cytoolz 1.1.0, ckzg 2.1.8, and eth-account 0.14.0. Full regression: 888 passed, 7 skipped, 1 warning. Focused local Ganache EVM suite: 2 passed.
- Node/Solidity: Fresh npm ci cache install added 343 packages; exact Ganache 7.9.2 and solc 0.8.37 are present. Solidity compile passed using 0.8.37+commit.f401782d.Emscripten.clang, with 9 ABI entries and 678-byte bytecode. npm reported 38 audit findings (1 low, 8 moderate, 24 high, 5 critical); no upgrade or lock change was made.
- CMake/CTest: Two clean builds each passed 39/39 tests; five trace hashes matched.
- Local mock smoke: Passed with a fresh temporary SQLite database, close/reopen, local mock submission and receipt reconciliation to VERIFIED. REAL_ON_CHAIN=NOT_EXECUTED.
- Clean package builds: Two clean builds with separately empty build caches matched: wheel SHA-256 4131a58586a4bcaafce2e8d7af9a2078a698d29c01fc8c202aaf9d66d0a575db; sdist SHA-256 3e1af1e2538c9e7c86c851fa8643c1512c11928c76035fac17c9916d44875f2c. Artifacts are bound to implementation baseline 081f6a5 to avoid self-referential evidence.
- Doctor: Exit 0; required software READY, with OPTIONAL_MISSING only for optional unconfigured engineering toolchains. Stale CRLF checkout materialization was restored from Git; tracked bytes match the clean reference checkout.
- Preservation: Original dirty checkout and upstream references were left untouched. No public chain or real funds were used.

## Follow-ups and limits

1. Repair direct WSL DNS resolution for future direct registry use; this run recovered through official endpoints using a temporary bridge.
2. build-constraints.txt fixes tool versions but does not pin per-distribution hashes. Fresh-cache build artifact identity was verified.
3. npm reported 38 audit findings; remediation requires a separate dependency/security decision and lock changes.
4. Zephyr/west/SDK, Renode, CadQuery export, Gazebo/ROS, ngspice, openEMS/CSXCAD, and external RF campaigns were not configured or run.
5. Public-chain validation was not run and was not part of the required software gates.

No integration, merge, or publication action was authorized.

## CODEX_TO_FACTORY_PACKET

MISSION: SC-3 Reproducible Environment & Clean-Room Build
REPOSITORY: GUZZBR1/riose
BASE_SHA: 081f6a55a5d4e66724809d02ca3ec89313ba1ad1
FINAL_SHA: supplied in delivery message; evidence commit contains this packet
BRANCH: software-closure/sc3-reproducible-environment
TREE: supplied in delivery message
REMOTE_FRESHNESS: VERIFIED (fork/main b2ddf11098ecd87b954bf97af26f8ecb8862b58a; origin/main c85c5f9bacf8065ceae95d45f173ad18418e5fda; diverged)
REPORTED_STATUS: PASS_REPRODUCIBLE_WITH_LIMITATIONS
GOVERNED_STATUS: PASS_WITH_FOLLOWUPS
MISSION_COMPLETE: YES (required software gates)
CLEAN_ROOM_STATUS: PASS_FOR_REQUIRED_SOFTWARE_GATES
REPRODUCIBILITY_LEVEL: FRESH_CACHE_SOFTWARE_REPRODUCTION; package artifacts matched independent clean builds
DEPENDENCY_MATRIX: reproducibility/dependency_matrix.json
BOOTSTRAP: canonical locked bootstrap PASS including exact EVM extras; no lock/version changes
DOCTOR: exit 0; required dependencies READY; optional engineering toolchains classified OPTIONAL_MISSING
PYTHON: 888 passed, 7 skipped, 1 warning; focused local EVM suite 2 passed
NODE_NPM: npm ci PASS; 343 packages; Ganache 7.9.2 and solc 0.8.37
SOLIDITY: solc compile PASS; ABI 9 entries, bytecode 678 bytes
FIRMWARE_BUILD: CMake/CTest 39/39 twice; five trace hashes match; Zephyr target not configured
OPTIONAL_DEPENDENCIES: listed in reproducibility/limitations.json and dependency matrix
LOCAL_BLOCKCHAIN: local Ganache tests PASS; integrated local mock PASS
CACHE_STATUS: fresh isolated Python and npm caches populated and installs passed; two separate empty build caches yielded matching artifacts
SECOND_PASS: PASS for required local software gates
INTEGRATED_SMOKE: PASS with temporary SQLite, local-mock submit and VERIFIED receipt; REAL_ON_CHAIN=NOT_EXECUTED
TESTS: full Python 888 passed/7 skipped; EVM 2 passed; CTest 39/39 twice; npm ci; Solidity compile; mock smoke; uv lock check; doctor
RED_TEAM: prior independent audit evidence retained; disclosed npm audit and distribution-hash follow-ups
REAL_ON_CHAIN: NOT_EXECUTED
LIMITATIONS: direct WSL DNS follow-up; no per-distribution build hashes; 38 npm audit findings; optional toolchains absent; public chain not run
EVIDENCE_PATH: reproducibility/
GIT_STATUS: expected clean after evidence commit; original dirty checkout preserved
FACTORY_REVIEW_READY: YES
