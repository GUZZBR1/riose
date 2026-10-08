# SC-3 red-team report

## Scope and verdict

A primary-agent checklist and an independent read-only native subagent audit examined the isolated SC-3 checkout against the mission brief. The independent review did not use sibling worktree contents. Verdict: **PARTIAL**. The cached core/dev/Solana route and host firmware/model tests have repeatable evidence; fresh Python EVM/npm acquisition, Solidity/Ganache execution, and remote freshness remain blocked.

## Findings and dispositions

| Finding | Evidence | Resolution / status |
| --- | --- | --- |
| Bootstrap had an unlocked pip fallback | Original setup.sh used pip install when uv was absent | Removed fallback; setup.sh delegates to scripts/bootstrap.sh, which requires uv and uses uv sync --locked. |
| Operational uv commands did not consistently enforce the lock | Makefile, demo, MVP3 scripts, and CI used plain uv run/uv sync | Added --locked to operational project commands and CI. |
| Local EVM dependencies were absent from core CI | Workflow did not restore the npm lock or Python EVM extra | CI installs pinned Node/npm, runs npm ci, installs Python EVM dependencies, and compiles the contract. |
| Solidity compile invocation omitted required source argument | Independent review compared process.argv[2] read with the CI/docs commands | Added contracts/src/RioseCommitmentRegistry.sol to the CI and canonical README command. Runtime compile remains externally blocked. |
| Doctor could mark absent optional tools incompatible | Node/npm exact-version checks and CMake version logic did not distinguish absence | Missing tools now report OPTIONAL_MISSING; four regression tests cover optional tools, provenance, EVM version checks, and build-input hashing. A real minimal-PATH CLI run exits 0 with OPTIONAL_MISSING. |
| Doctor could accept riose from a foreign checkout | Import provenance did not mark unexpected application origin as incompatible | Wrong or missing application origin now reports INCOMPATIBLE; regression test passes, and a synthetic foreign-source CLI run exits 1. |
| Doctor did not compare installed local EVM versions with the lock | Package files were checked only for existence | Ganache and solc package versions, plus actual solc compiler version, are compared with package-lock.json. |
| First-run Solana and dependency-matrix evidence was stale | Run 1 said extras were absent and matrix described old install failures | Corrected: solders installed in both cached venvs; no local validator was configured. Matrix now separates runtime, dev, Solana, and EVM dependencies. |
| Earlier sdist comparison used untracked evidence | Prior output source was a dirty working tree with uncommitted evidence | Superseded. Rebuilt twice from two clean detached worktrees at source 92ef1b5276096da9f01b5d6218207b9984e5471e; tree bb87b9828d8681d63852cd2ea786dc41a0a35bf3; matching hashes are recorded. |
| PEP 517 build versions floated | pyproject.toml did not constrain Hatchling or transitive build tools | Pinned Hatchling and the observed toolchain in build-constraints.txt; two isolated clean builds matched. Empty cache still requires registry access, and the constraints do not include distribution hashes. |
| Canonical instructions omitted evidence commands | README lacked smoke, manifest, compileall, and package-build steps | Added commands that write generated evidence/artifacts outside the checkout. |
| Network route is unavailable | Latest fork/upstream GitHub fetches, npm ci, Python bootstrap, and online package build failed DNS | REMOTE_FRESHNESS=UNVERIFIED; EVM installation remains EXTERNAL_BLOCKED. |
| Text files could receive CRLF on Windows-configured clones | A fresh checkout with core.autocrlf=true showed CRLF in setup.sh and other inputs, changing shebangs and package source bytes | Added a global text=auto eol=lf rule; fresh 92ef1b5 checkout kept all 1,057 tracked text files on LF; bash -n passes and doctor.sh ran through its shebang. |
| WSL PATH included Windows executables | Initial PATH exposed a Windows Docker executable unusable on sanitized Linux PATH | Linux-only environment was used for validation; Docker is not required. |
| uv is outside the checkout | uv resolves to /home/gusta/.local/bin/uv | Explicit prerequisite; doctor checks >=0.11.7; CI pins 0.11.7. |
| Demo database can retain prior state | CLI default database is data/cattle_rf.sqlite3 | Tests use temporary DBs; integrated smoke creates a new SQLite DB, closes/reopens it, and validates persisted state. |

## Reproduction evidence

- uv.lock check passes. Cached core/dev/Solana dependencies installed in two fresh virtual environments. Latest non-EVM suite: **855 passed, 7 skipped**; the full suite fails collection in two EVM modules importing unavailable eth_account.
- Four doctor regression tests pass: optional-tool absence, foreign checkout import, locked solc compiler mismatch, and build-constraints manifest hashing. The separate Solana mock suite passed 15/15.
- Two clean host CMake build directories each passed **39/39 CTest** cases. Five trace files matched SHA-256.
- Two clean detached worktrees at source 92ef1b5 built byte-identical wheel and sdist in two clean worktrees using uv 0.11.26, Python 3.12.3, and the exact versions in build-constraints.txt. Wheel import resolved from a fresh venv site-packages.
- Integrated smoke passed Event V1, SQLite persistence/reopen, Commitment V1, local mock submission, and receipt reconciliation. No public chain was contacted.

## Remaining falsification targets

The audit could not run npm ci, Solidity compile, Ganache runtime, full Python EVM tests, local Solana validator tests, Zephyr/native_sim, Renode, CadQuery exports, Gazebo/ROS, or external RF tools. Registry DNS prevents completing the fresh dependency gates. The PEP 517 versions are constrained; per-distribution hashes and empty-cache downloads remain external. These are explicit open gates, not PASS claims.
