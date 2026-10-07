# RIOSE Pre-Blockchain Baseline

## Publication candidate

- Repository: `GUZZBR1/riose` (`fork` remote).
- Base reviewed: `b2de3a9a58f911e24dc9a8395717f520542282b3` (`fork/main`).
- Initial local `main`: `e57b235a452c6e8d258d1708d5fd53ce56cecfb3`.
- Cached `origin/main` (`santleme/riose`): `5b17771f0f86b0bb0cdb526485e8e2f50e78fdea`, an ancestor of `fork/main`; the fork is 58 commits ahead.
- Integration branch: `integration/pre-blockchain-baseline`, created from the reviewed `fork/main` tree. See `PRE_BLOCKCHAIN_INTEGRATION_PROVENANCE.json` for exact commits and evidence.
- Baseline commit merged to `main`: `2beb7a5dd5681cbc7b5fc308f5e3a12301b85686` (PR #37).
- Tag trace closure merged to `main`: `e32235b86d1e6f0042f6490b223bdf155bc2827f` (PR #39).

The target branch is the fork, not the upstream remote. The GitHub repository page showed `fork/main` at the reviewed base and zero open PRs before integration. Git CLI push/fetch was unavailable because `github.com` did not resolve and the local CLI token was invalid; the authenticated GitHub connector published the integration branch and follow-up PRs. The core workflow at the reviewed base had failed because its dependency install omitted the already-declared optional `solana` test extra. The integration fixes that command. PR workflow runs 81, 85, and 89 passed both `cad-export` and `core` jobs; run 89 verified the tag-trace follow-up.

## Integrated in this candidate

- Simulation Lab H.2 stable request identity is carried across event, gateway, clock, estimation, and scoring joins; gateway events fail closed on mismatched identities/statuses. This avoids FIFO `event_index` attribution. The implementation was adapted from commits `75dc468`, `9ae9ee1`, `a3c5f50`, and `2e5d5d9`; the broad beta-final cherry-pick was rejected due to delete/rename conflicts. The FREQUENCIA adapter must also preserve serialized event identity at `TxStart` (upstream commit `0190048023269da695c84d0ff5e1cf3c6ed502d7`); the RIOSE side alone does not provide that behavior.
- Compact H.2 simulated closure evidence and retained failed-attempt records are in `docs/research/beta-final/temporal-identity-closure.md` and its `runs/` subdirectory. The historical H.1 event counts remain explicitly unverified.
- The dynamic localization V2 estimator, deterministic fault campaign, regression tests, compact reports, and 6,720-case result artifact are included. Findings are adverse as well as positive: wrong calibration was falsely accepted in 50/50 trials, and a 10 ns jitter scenario was falsely accepted in 11/18 trials. This is analytic 2D LOS simulation with post-estimation truth joins, not measured or field evidence.
- The final bounded RF realism closure report/evidence and final network contention/capacity report/envelope are retained under `docs/research/`. These are simulated evidence, not deployment claims. The network report excludes invalid 1-second event associations and explicitly disclaims generic capacity, application delivery, and outage claims.
- `.github/workflows/mvp2-core.yml` installs the declared `solana` extra for tests so Solana optional-package tests are included in the project suite.

## Inventory classification

- **ALREADY_IN_MAIN:** The reviewed fork tip is based on the published integration and contains the core product, event/evidence contracts, SQLite persistence, API, Simulation Lab foundations, hardware simulation, intelligence, and Mini-MVP work. Issue branches 1–3, 21–28, movement/tag research, and Mini-MVP persistence, firmware/digital-twin, and simulation/localization refs are ancestors of the target. They do not need branch merges. Other issue refs are recorded individually in `PRE_BLOCKCHAIN_BRANCH_INVENTORY.json`.
- **READY_TO_INTEGRATE:** H.2 stable event identity, the dynamic localization fault campaign, and the tag sensor trace/axis closure were absent at the target tree and are included selectively here. The tag slice bounds dataset conversion to the LIS2DW12 physical range, exercises STATIC/WALK/RUN plus a golden axis probe, and offers an explicit `--skip-antenna` path. Its evidence remains simulated. The RF and network closure evidence is included as auditable research artifacts; their older campaign code is not copied because it uses the superseded `event_index` identity path.
- **SUPERSEDED / DUPLICATE:** Earlier issue and Mini-MVP branches whose commits are already ancestors or whose implementation is superseded by the integrated tree. The RF campaign baseline `research/rf-realism-campaign` is superseded by `research/rf-realism-gap-closure`. `research/network-scale-capacity` is superseded by `research/network-contention-capacity-closure`.
- **PARTIALLY_USEFUL / NOT READY:** The tag antenna pilot remains `PARTIAL_SIMULATED`: solver energy met its limit before excitation completion, S11 validation failed, and no RF metrics or mesh-refinement evidence are accepted. Issue 10's dirty antenna worktree has a stale README and no accepted RF metrics. Issue 9's dirty CAD test edit is superseded by optional-CadQuery handling in the target test. These source worktrees were not modified.
- **EXTERNAL_BLOCKED:** Renode is unavailable on this host; the platform test target skipped. Physical hardware and field calibration are absent. The reported openEMS availability differed between worktrees and was not independently reconciled; in any case the retained pilot result is rejected. H.2 also depends on FREQUENCIA's external `TxStart` event-ID patch. These limits do not invalidate the simulated/code baseline, but constrain those claims.
- **BLOCKCHAIN / OUT OF SCOPE:** The reviewed target already contains Web3/Solana publication and commitment files from earlier work. They predate this integration and were not edited, extended, or removed. The dirty `blockchain-hackathon-demo`, Mini-MVP blockchain, and issue-03 commitment worktrees/branches were excluded. This publication candidate must not be represented as a blockchain-free checkout; it is a pre-blockchain consolidation of eligible work on the existing target tree.

Repository discovery found 51 local branches, 46 remote-tracking refs, and 66 worktree registrations. Several registrations point to unavailable stale WSL paths and were left alone. The root worktree's existing untracked preservation manifests and `riose-issue26/` directory were left untouched. The separate multichain worktree remains clean at the reviewed target SHA. No PRs were open in the public repository when checked. The branch-by-branch decisions and ref SHAs are recorded in the provenance JSON and supporting Git history.

`PRE_BLOCKCHAIN_BRANCH_INVENTORY.json` records all 97 local and cached remote refs with SHA, ancestry, ahead/behind counts, classification, and all 66 worktree registrations. Dirty worktree findings were:

- Root checkout: untracked preservation manifests, collision matrix, and `riose-issue26/` (preserved).
- `riose-blockchain-hackathon-demo`: modified blockchain demo docs, Solana publication adapter/domain/CLI/verifier, tests, and untracked demo simulation/tests/research evidence (excluded as blockchain).
- `riose-tag-simulation-closure`: modified Renode board config and scripts/tests, digital twin CLI/runner/test; untracked tag closure report/evidence and LIS2DW12 fixtures. The focused code/evidence slice is now in this candidate after 55 passing tests; the original worktree remains untouched.
- `riose-wt-issue-09`: modified mechanical model test plus untracked `.omx/` state (test edit already superseded; state preserved).
- `riose-wt-issue-10`: modified README, antenna/mechanical model/tests/spec/toolchain docs; untracked antenna geometry/metrics/openEMS/sweeps/tests and integration map (partial, preserved).
- `riose-wt-issue-01`, `riose-wt-issue-02`, `riose-wt-issue-03-commitment-v1`, and `riose-wt-issue-07`: dirty identity, evidence-bridge, commitment, and `.omx/` state respectively. The first two overlap integrated or blocked contract work; commitment is blockchain; `.omx/` is local state. All were preserved.
- Other reachable clean worktrees were left as found. Registered worktrees whose Git metadata points to missing locations were not pruned or deleted.

## Verification and limitations

- `uv sync --locked --offline --extra dev --extra solana` — passed.
- `uv run --offline --extra dev --extra solana pytest -q` — 794 passed, 7 skipped; one existing Starlette/httpx deprecation warning.
- `ctest --test-dir /tmp/riose-pre-blockchain-baseline-hardware-tests --output-on-failure` — 39/39 passed.
- Focused identity + dynamic-localization regressions — 69 and 24 passed respectively before the full suite.
- Tag digital-twin + RESD converter focused tests — 55 passed.
- Renode check — skipped because Renode tools are unavailable on this host; no physical firmware flash was run.
- No physical firmware flash, RF field measurement, or new Sionna/ns-3 campaign was run in this integration.
- `git diff --check`, Python compilation, JSON validation, and a high-signal private-key/token marker scan passed; no matching markers were found. `gitleaks` and `trufflehog` were unavailable.

The external FREQUENCIA request-identity patch is required for real ns-3 adapter lineage. Until that dependency is published and verified, H.2's included RIOSE code should be treated as tested contract/validator support paired with the archived simulation evidence, not as a newly rerun adapter result. Existing Web3 files and any local-only partial work remain separately classified above.

## Publication state

PR #37 published the baseline, PR #38 corrected its publication record, and PR #39 published the tag sensor trace closure. All three PR runs passed their required CI jobs. GitHub confirmed the baseline and tag-trace commits on `main` and key files were fetched successfully. The local Git CLI could not fetch due DNS/authentication failure, so remote ref and file checks were performed through the authenticated GitHub connector. The completion report records the final verified `main` SHA after the documentation status update.
