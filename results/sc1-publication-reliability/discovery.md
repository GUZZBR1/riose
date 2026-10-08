# SC-1 Repository Discovery

## Scope and source of truth

- Product repository: `GUZZBR1/riose` (fork). Upstream: `santleme/riose`.
- Current local canonical fork ref available for this mission: `fork/main` at `b2ddf11098ecd87b954bf97af26f8ecb8862b58a`.
- Base tree: `2ee3930e5ae6b96cef6134840151c17f7c85f0e4`.
- The source checkout `riose/` is on `codex/issue-10-antenna-convergence` at `e57b235a452c6e8d258d1708d5fd53ce56cecfb3`, 14 commits behind its locally recorded `origin/main`; it has four untracked entries. It was left untouched.
- The fork main ref is 2 commits ahead of the local `multichain/main-reconciliation` ref at `6367bd5d9b512b7da164bb095e3dc2ec1b9ef05f`. Other relevant local source refs include `multichain/final-integration` (`a45908b6eecb347fb5e2f6bf1e111f10885a4647`), `mini-mvp/blockchain-publication` (`0c482054a7a0b37c9c2d59a3d97641a0c57837d7`), and `validation/mvp4-offline-multichain` (`4e38b5a83d65ff30f7069dd0078c7fe93c1a6446`). These were inspected as historical/context refs and not modified.
- The mission branch was created as `software-closure/sc1-publication-reliability` from `fork/main` in `/home/gusta/projetos/RIOSE/riose-sc1-publication-reliability`.

## Remote freshness and PR discovery

`git fetch --all --prune` was attempted from both the main clone and the separate fork clone. Both failed with `Could not resolve host: github.com`. The GitHub CLI PR query also failed with `error connecting to api.github.com`. Therefore `REMOTE_FRESHNESS=UNVERIFIED`; locally cached refs are the evidence boundary. No upstream ref or remote repository was written.

## Checkout and worktree inventory

The workspace contains many separate RIOSE checkouts. The complete local Git worktree listing and branch/tag/ref snapshots are retained under `discovery/`. Key publication/multichain checkouts and their initial cleanliness are:

| Checkout | Branch / ref | Initial status |
|---|---|---|
| `riose/` | `codex/issue-10-antenna-convergence`, `e57b235` | Dirty: 4 untracked entries; preserved |
| `riose-simulation-lab-guzzbr1/` | `research/simulation-lab`, `bcc49af` | Clean |
| `riose-mini-mvp-blockchain-publication/` | `mini-mvp/blockchain-publication`, `0c48205` | Clean |
| `riose-multichain-mvp1-clean/` | detached, `fedc1bb` | Clean |
| `riose-multichain-mvp2-clean/` | detached, `977be7b` | Clean |
| `riose-multichain-mvp3-clean/` | detached, `60bbb7f` | Clean |
| `riose-multichain-mvp4-base-clean/` | detached, `df9d281` | Clean |
| `riose-multichain-mvp4-arbitrum/` | `multichain/mvp4-arbitrum`, `65a7035` | Clean |
| `riose-multichain-final-integration/` | `multichain/final-integration`, `a45908b` | Clean |
| `riose-multichain-main-reconciliation/` | `multichain/main-reconciliation`, `6367bd5` | Clean |
| `riose-validation-mvp4-offline-multichain/` | detached worktree ref, `4e38b5a` | Clean; git reports stale/prunable path metadata |
| `riose-validation-mvp5-real-on-chain/` | `validation/mvp5-real-on-chain`, `df4ef33` | Clean |
| `riose-validation-mvp6/` | `validation/mvp6-final-gate`, `cac2b38` | Clean |

Many unrelated issue/research worktrees also exist, including dirty preserved worktrees. Their detailed paths/statuses are retained in `discovery/worktrees.txt`; no cleanup, reset, deletion, rebase, or branch rewrite was performed.

## Local ancestry

- `fork/main` resolves to the fork’s locally cached branch tip noted above.
- The fork tip’s merge base with the cached upstream `origin/main` is `5b17771f0f86b0bb0cdb526485e8e2f50e78fdea`.
- Cached upstream `origin/main` is `c85c5f9bacf8065ceae95d45f173ad18418e5fda` in the primary clone.
- These values describe local refs only; remote state could have moved since their last fetch.

## Scope boundary

`frequencia` is external and is not the RIOSE fork; it is not part of this publication reliability change. No public transaction, funded signer, upstream write, automatic merge, or push was performed.
