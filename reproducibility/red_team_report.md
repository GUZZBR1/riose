# SC-3 red-team report

## Scope and verdict

The adversarial review used the new SC-3 checkout and its own environment. It did not use sibling worktree contents, global Ganache/Solc installs, old databases, public chains, or prebuilt CMake output as evidence. Verdict: **PARTIAL**. The core Python/host firmware route has repeatable evidence; the EVM dependency route and live remote freshness remain blocked.

An independent native subagent review could not launch because the account rejected the role-mapped gpt-5.x models. The following checklist was therefore performed by the primary agent and is not an independent review.

## Findings

| Finding | Evidence | Resolution / status |
| --- | --- | --- |
| Bootstrap had an unlocked pip fallback | Original `setup.sh` used `pip install -e '.[dev]'` when uv was absent | Removed fallback. `setup.sh` now delegates to `scripts/bootstrap.sh`, which requires uv and uses `uv sync --locked`. |
| Operational uv commands could resolve or update without enforcing the lock | Existing Makefile, demo, and MVP3 scripts used plain `uv run`/`uv sync` | Added `--locked` to executable project commands and the CI test steps. Historical reports remain unchanged. |
| Local EVM dependencies were not installed by core CI | Workflow installed Python/Solana extras but did not restore the npm lock | CI now pins Node through `.nvmrc`, installs `npm ci`, installs the Python EVM extra, and compiles the local registry. |
| Node/npm versions were implicit | `contracts/package.json` had no engine/package-manager declaration | Added Node 22.22.2 `.nvmrc`, Node engine constraint, and npm 10.9.7 package-manager pin; lock root engines match. |
| Inherited WSL PATH included Windows executables | Initial PATH exposed `/mnt/c/.../docker`; it had no usable Linux version in the sanitized environment | All reproducibility commands used an explicit Linux PATH. Doctor records executable origins/versions; Docker is not required. |
| uv is outside the checkout | `uv` resolves to `/home/gusta/.local/bin/uv` | Explicit prerequisite; doctor checks >=0.11.7; CI pins 0.11.7. No other global Python packages were used. |
| No sibling imports or repository symlinks | Targeted source/config scan found no sibling checkout paths; source scan found no symlinks outside generated `.venv` interpreter links | No sibling dependency found in the SC-3 checkout. Imports in doctor resolve from this checkout and its `.venv`. |
| Default demo database can preserve prior state | CLI documents `data/cattle_rf.sqlite3` as its demo default | Tests use temporary databases; the integrated smoke creates a fresh temp DB, closes/reopens, then validates the persisted queue. |
| Cache-only install can appear complete while optional gates are missing | Empty cache lacks watchfiles; global cache installs core/dev/Solana but lacks EVM cytoolz/ckzg; npm cache lacks Ganache | Statuses are separated in cache/bootstrap reports. No skipped EVM gate is labelled as passed. |
| Network route is unavailable | Git fetch returned “Could not resolve host: github.com”; npm ci returned `EAI_AGAIN`; uv retries failed DNS | `REMOTE_FRESHNESS=UNVERIFIED`; full EVM install remains `EXTERNAL_BLOCKED`. |

## Reproduction evidence

- `uv.lock` check passes; offline cached install of core/dev/Solana passes in two fresh virtualenvs. Each run of the remaining suite: **851 passed, 7 skipped**. The unfiltered collection fails on direct `eth_account` imports in two EVM modules because the EVM extra could not install (`cytoolz==1.1.0` and `ckzg==2.1.8` absent).
- Two fresh CMake build directories each passed **39/39 CTest** cases. Five generated firmware trace files have matching SHA-256.
- Two offline wheel/sdist builds have matching SHA-256. Wheel import from a newly created temporary virtualenv resolved from `site-packages`, not this checkout.
- The existing application path passed a local mock publication smoke through Event V1, SQLite, Commitment V1, queue restart, mock submit, and receipt reconciliation. It does not start Ganache or contact a public network.

## Remaining falsification targets

The red team could not test npm registry installation, Solidity compiler execution, Ganache runtime, full Python regression including EVM modules, Zephyr/native_sim, Renode, CadQuery exports, or live Gazebo/ROS and external RF tools. Those remain explicit missing gates, not successful reproduction claims.
