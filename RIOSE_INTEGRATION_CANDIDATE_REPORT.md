# RIOSE Integration Candidate — Gate Beta

**Status: PASS_WITH_LIMITATIONS**
**Branch:** integration/riose-candidate
**Worktree:** /home/gusta/projetos/RIOSE/riose-integration-candidate
**Frozen upstream base:** 5b17771f0f86b0bb0cdb526485e8e2f50e78fdea
**Candidate code head before audit artifacts:** 479c818 (full SHA recorded in provenance)
**Audit date:** 2026-10-05, America/Sao_Paulo

## 1. Identities and refs

The repository remotes are origin=https://github.com/santleme/riose.git and fork=https://github.com/GUZZBR1/riose.git. Local refs resolve to upstream base 5b17771f0f86b0bb0cdb526485e8e2f50e78fdea and GUZZ reference 72ad69551b54eb069bb1c5f863dfff4066786965. Safe fetches of origin/main and fork/main were attempted and failed because DNS could not resolve github.com; remote freshness is therefore unverified. All pinned source commits were available locally.

The pre-existing dirty checkout at /home/gusta/projetos/RIOSE/riose was not used for edits. Its untracked preservation files were left untouched. The isolated candidate worktree was created clean at the frozen base.

## 2. SHAs

| Role | SHA |
|---|---|
| Frozen upstream base | 5b17771f0f86b0bb0cdb526485e8e2f50e78fdea |
| GUZZ reference | 72ad69551b54eb069bb1c5f863dfff4066786965 |
| Core MVP branch head | 84ae34f2f8e54aabed3ac1be70338023d981d566 |
| Core source code commit | 9772e3a (full SHA in provenance JSON) |
| Embedded MVP branch head | 10a7b3215c3f87b3893cbfcc790c58cb5cdccd72 |
| Embedded source code commit | 163143d (full SHA in provenance JSON) |
| Intelligence MVP branch head | 7581f1188f0801543ce38a1496eb955c7aac4e9d |
| Intelligence source integration commit | 222deb2 (full SHA in provenance JSON) |

## 3. Assembly strategy

The candidate began at the frozen upstream base. The Core implementation, Embedded code commit, and selected Intelligence paths were reconciled and committed separately. No source MVP branch was merged wholesale. Core owns packaging, event identity, observation API, and SQLite persistence. The Intelligence prediction interface consumes a Core-owned persistence boundary. Embedded changes are isolated to the LIS2DW12 conversion, host regression, and cross-domain contract documentation.

| Component | Source | Target | Policy | Files | Dependencies | Collision risk | Required tests |
|---|---|---|---|---|---|---|---|
| Core & Product | 9772e3a; branch head 84ae34f | Candidate from 5b17771 | Promote reviewed Core changes; Core owns package, identity, event and persistence contracts | Evidence bridge, observations API/SQLite, event identity, movement catalog/adapter, tests, packaging | Existing base dependencies; none added by this candidate | Medium: duplicate movement/evidence additions overlap Intelligence | Core API, persistence, identity/event, dataset, wheel, CLI, full pytest |
| Embedded & Physical-Digital | 163143d; branch head 10a7b32 | Same candidate | Promote LIS2DW12 conversion and regression; preserve upstream SX1262, Renode, Gazebo and MVP3 | Firmware conversion/build wiring, C regression, embedded contract | Host C toolchain; Zephyr/Renode/Gazebo optional tools | Low file overlap; verify cross-domain units, tags and clocks | CTest, Python suite, Zephyr attempt, simulator availability checks |
| Intelligence & Research | 222deb2; branch head 7581f11 | Same candidate | Promote PRODUCT_OPTIONAL and REUSABLE_CONTRACT only | Prediction interface, simulation contract/adapter and tests; unchanged source packet/matrix retained | Existing Python dependencies; no ML, Sionna, ns-3 or FREQUENCIA dependency | Medium semantic overlap: persistence identity and temporal event contracts | Prediction, simulation adapter/contract, temporal identity and dependency audit |
| Cross-contract reconciliation | All three source commits | Same candidate | Manual reconciliation; no blind merge | Core identity/events/persistence with embedded units/time and simulation request/packet identity | No added runtime dependencies | Semantic overlap across independent MVPs | Contract tests, CTest, full suite, red-team |

## 4. Promoted changes

- Core: additive observation persistence/API; event identity and versioning compatibility; provenance/evidence bridge; movement dataset catalog/acquisition/contract and CLI; focused regression tests.
- Embedded: shared configured LIS2DW12 conversion helper and scale regression; documented firmware/simulator unit, axis, identity, and time boundaries.
- Intelligence: typed BehaviorPrediction/BehaviorPredictionStore seam; reusable Simulation Contract v1, temporal identity, and opt-in simulation adapter with focused tests. These do not add a predictor, backend runner, or campaign machinery.

## 5. Excluded changes

Behavior ML/model and training pipeline, BioSignature runtime, Health anomaly runtime, Reproduction, Localization V2 solver/campaigns, RF and Network campaign runners, Simulation Lab runner/campaign machinery, publication/blockchain, and FREQUENCIA source/history were not promoted. Experimental and research code remains on its source branches. External dataset bytes were not copied; catalog and synthetic parser fixtures are explicitly identified as metadata/fixtures.

## 6. Collisions and resolution

Core and Intelligence overlap on the movement catalog/adapter, evidence bridge, fixtures, and their tests. The Core versions were selected once as Core is the authority and these files have overlapping additions in the source branches. The Intelligence prediction seam and simulation contract/adapter do not duplicate Core persistence. Core versus Embedded had no changed-path overlap. Embedded versus Intelligence had no changed-path overlap. Cross-domain semantics were reviewed for tag/animal identity, timestamps, units, and evidence classifications.

## 7. Cross-contract reconciliation

Status: PASS for the code-level contracts exercised by tests. Core's event and identity serialization remains authoritative; the embedded contract documents tag identity and sensor axes/units; simulation temporal identity retains explicit request, packet, sequence, and event timing. There is no inferred equality between firmware uptime, simulator time, and event timestamps.

## 8. Dependency graph

Status: PASS. uv lock --check --offline resolved 48 packages; uv sync --offline --extra dev installed the candidate and development environment from cache; uv build --offline produced sdist and wheel. The candidate adds no runtime dependencies relative to the frozen upstream pyproject. Sionna, openEMS, ns-3, FREQUENCIA, and Intelligence model dependencies are not added. Existing upstream dependencies remain unchanged. The checked-in uv.lock was not modified.

## 9. Identity and events

Status: PASS in automated tests. Core event canonicalization, v1 digest compatibility, schema version handling, and invalid-input rejection are retained. Intelligence predictions require animal_id and tag_id plus model/input hashes; they do not redefine event identity. Historical golden hashes remain untouched in the candidate diff.

## 10. Persistence

Status: PASS for one persistence architecture. Core owns the additive SQLite observation table and API. BehaviorPredictionStore is only an interface seam; it does not add a prediction table, database, route, or duplicate migration. Prediction persistence still requires a future Core-owned additive schema/API decision.

## 11. Movement

Status: PRODUCT_OPTIONAL. Dataset parsing/transformation and the prediction provenance seam can exist without a trained model. No Behavior ML import or model dependency was added. Existing upstream NumPy/SciPy/scikit-learn dependencies were already present in the frozen base and were not changed by this assembly.

## 12. Embedded

Status: PASS for host build and tests. Firmware keeps the upstream SX1262 and simulator interfaces. The LIS2DW12 helper follows the configured high-performance 14-bit conversion and has an explicit signed-scale regression. No sensor calibration or physical measurement is claimed.

## 13. Simulation boundaries

Simulation Contract and adapter are reusable, opt-in interfaces. They do not import or vendor research campaign runners. Simulated results remain distinct from measured hardware, RF reception, or field evidence. Renode and Gazebo execution were unavailable; static contract review and host Python/C tests were performed.

## 14. Scientific claims

The registry in RIOSE_SCIENTIFIC_CLAIM_REGISTRY.json uses only the permitted evidence classes. Software integration is marked verification_status=TESTED, with software/model evidence class SIMULATED. RF/network/localization remain SIMULATED; Behavior remains research-supported or simulated; BioSignature and Health remain experimental/unverified; Reproduction remains research; physical hardware and field validation remain UNVERIFIED. No claim says openEMS is validated or simulated evidence is physical evidence.

## 15. Zephyr

ENVIRONMENT_BLOCKED. The documented target is west build -b native_sim/native/64 -d /tmp/riose-candidate-zephyr hardware/firmware/zephyr. Attempting it returned west: command not found; ZEPHYR_BASE is unset. The host C build and CTest do pass. No Zephyr success is inferred.

## 16. Renode and Gazebo

Renode: ENVIRONMENT_BLOCKED. make hardware-renode-test reports RENODE_AVAILABLE=false and RENODE_TEST_AVAILABLE=false and skips the smoke tests. Gazebo: ENVIRONMENT_BLOCKED; neither gz nor gazebo is on PATH. Existing simulator/MVP3 files are unchanged, and the Python suite passes, but live simulator execution is unverified.

## 17. Tests

Exact candidate results are recorded in RIOSE_INTEGRATION_TEST_MATRIX.json. Summary: compileall passed; focused new Python contract tests passed 131; full Python suite passed 617 with 7 skipped and one Starlette/httpx deprecation warning; hardware CTest passed 39/39; firmware host build passed 11/11; lock check, offline sync, sdist/wheel build, and declared entrypoint smoke checks passed. An initial system-Python collection lacked FastAPI; the declared environment resolved offline and the complete suite then passed. This is NOT_A_PRODUCT_DEFECT. No lint/type-check target is configured in pyproject; compileall and the complete tests were run.

## 18. Provenance

RIOSE_INTEGRATION_PROVENANCE.json maps every promoted source path group to its full source SHA and exact target commit. The report, test matrix, provenance file, and claim registry are audit outputs produced by assembly, not promoted MVP features.

## 19. Evidence integrity

PASS. git diff from the frozen base reports no changes under results/, hardware/renode/, or hardware/gazebo/. No historical evidence files were rewritten. Existing preservation refs were not addressed by any operation; 1,801 refs/preservation refs currently resolve. Historical results remain historical and were not rerun or relabeled.

## 20. Red-team

An independent read-only review completed. Result: PASS with environment limitations. It confirmed upstream MVP3/CLI/site/localization, movement's lack of ML imports, no new heavy or FREQUENCIA runtime dependency, single-owner persistence, LIS2DW12 conversion coverage, and no historical results diff. It flagged that the copied Intelligence packet and promotion matrix contain source-branch identities and source integration counts; these are retained unchanged as source evidence, and their fields describe the Intelligence MVP, not this candidate. Candidate identity, commits, and selected per-source file groups are recorded in this report and RIOSE_INTEGRATION_PROVENANCE.json. It also observed that upstream heavyweight runtime dependencies remain in the frozen base; this assembly does not increase that dependency set. The review found no code-level integration blocker. Native exploration agents could not start because the configured explorer model was unsupported for this account; the independent review ran read-only against the assembled candidate.

## 21. Known limitations

- Remote branch freshness is unknown because GitHub DNS failed.
- The copied Intelligence packet and promotion matrix preserve source-MVP branch/commit metadata verbatim; they are source evidence, not candidate identity documents.
- Zephyr, Renode, and Gazebo runtime gates are unavailable in this environment.
- No physical sensor, radio, field, biological, or veterinary validation is claimed.
- The Intelligence persistence protocol has no Core implementation yet.
- ActBeCalf source bytes were not acquired; only the synthetic adapter fixture was tested.
- A pre-existing upstream CLI behavior causes riose mvp3 --help to display the dispatcher's generic help; riose.cli is byte-identical to upstream and this assembly did not change it.

## 22. Exact commits

Candidate commits, in order:

1. b28fa8601cdb4e13b5d9f0fb1e173e0bfa9be6b3 — Preserve approved Core contracts on the frozen product base.
2. b0c160ecbf72ceeb5582a0c005c41fea0979498d — Correct LIS2DW12 units across firmware and simulator boundaries.
3. 479c818c81ffb007e7ee71d9ed960d0afabec78a — Promote optional intelligence and simulation contracts.
4. The final evidence/report commit is this report's containing commit, at the candidate branch HEAD shown in the final handoff.

Full SHAs are listed in the provenance JSON and final git history.

## 23. Final diff

The base-to-candidate code diff contains additive Core/Embedded/selected Intelligence files and modifications to upstream identity/API/persistence/package entrypoints. No tracked files were deleted. All upstream product and MVP3 paths remain present. Core-to-candidate differences are the selected Embedded/Intelligence additions and the Core MVP's source-only report, which was not copied into the product candidate. Embedded-to-candidate differences are selected Core/Intelligence additions and its source-only report. Intelligence-to-candidate differences include selected Core/Embedded additions while omitting its unapproved research implementation and campaigns; its packet and promotion matrix are retained as unchanged source evidence. GUZZ-reference-to-candidate differences intentionally preserve the upstream product rather than absorbing GUZZ main. Duplicate files are included once. The 1,801 preservation refs were not modified.

## 24. Recommendation for Chat 8

Review the candidate as PASS_WITH_LIMITATIONS and decide whether unavailable Zephyr/Renode/Gazebo runtime gates and remote freshness are acceptable or should be rerun in a provisioned environment. The candidate is not the final mega-integration authority; Chat 8 retains that decision.

**Push:** NO
**PR:** NO
**Upstream main modified:** NO
**GUZZ main modified:** NO
**Preservation refs modified:** NO
**Historical evidence rewritten:** NO
**Chat 8 ready:** YES, for final authority review with listed limitations.
