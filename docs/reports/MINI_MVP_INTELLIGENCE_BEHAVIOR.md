# Mini-MVP 4 — Intelligence & Animal Behavior

**Verdict: PASS_WITH_LIMITATIONS**
**Branch:** `mini-mvp/intelligence-behavior`
**Canonical base:** `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`.
**Clean reproduction snapshot:** `a6d3b49397344a60cdd1618d8f94e7e0ba95a2f8` (detached worktree, clean).
**Canonical product tree:** `bb9713f64467d498c4547bbe9bc1e32f5617dadf`

## Result

An offline, repeatable movement-to-behavior evaluation pipeline was added around the current signal, intelligence and SQLite Core contracts. A full replay processed 2,467,162 samples from 30 calves into 29,908 non-overlapping 3-second windows. The selected Logistic Regression model was chosen on validation macro-F1, then evaluated once on six held-out calves. No same-animal train/validation/test overlap was found. Five time-overlap pairs were detected between annotation runs, all within the training animal group; none crossed partitions. Test windows were not used for model selection or fitting.

The model is **RESEARCH**, not product-ready. Held-out accuracy was 0.5336, balanced accuracy 0.1991 and macro-F1 0.1885, versus majority baseline 0.5279 / 0.0588 / 0.0406. It improved macro metrics over the baseline but remained poor across many behavior classes. Seven of 17 evaluated classes had F1=0; `lying` made up 3,444/6,524 test windows and dominated accuracy. Calf-level accuracy ranged from 0.129 to 0.944, showing substantial animal variation.

Five-fold GroupKFold by animal, with fold-local label support and scaling, gave mean accuracy 0.5393 (population SD 0.0693), balanced accuracy 0.2272 (SD 0.0025), and macro-F1 0.2126 (SD 0.0080). Worst fold scores were 0.4301 / 0.2249 / 0.2003. This CV is a separate cross-validation experiment across the same 30-animal dataset, not an additional untouched independent holdout.

## Dataset and provenance

Dataset: AcTBeCalf, public measured dataset, source [Zenodo record 13259482](https://zenodo.org/records/13259482), version 1.0. The source file is 177,608,717 bytes; publisher MD5 `59bd00564af64d92489485fa5a8a3960`; downloaded local SHA-256 `1aec91cc9454919e865be204d503899a89ebdba3ca5f81ee2cb22942f456f26d`. The official record describes 30 calves, a neck AX3 collar, 25 Hz and an ethogram with 23 behavior classes. The Rights/License field was empty when checked, so license is recorded as `UNVERIFIED_ZENODO_RIGHTS_FIELD_EMPTY`; no license permission is inferred.

The exported CSV contains 2,467,162 rows, 30 calf IDs, 4,016 annotation segments, 50 distinct raw label strings, and 24 observed gaps above 60 ms in the audited source order. The source provides no session IDs; `segId` is treated as annotation segment, not session. Axis units and timestamp timezone are unknown. Raw label strings are retained and namespaced; observed variants are not silently mapped into the publisher's 23-class ontology. The source file, model and large replay artifacts remain in the external local cache and were not added to this repository.

## Pipeline and evidence

- Movement input: publisher CSV parsed and checked against size and publisher MD5; local SHA-256 recorded. Non-finite/invalid rows are rejected. Unknown axis units remain unknown in feature names and metadata.
- Windows/features: 3-second windows at nominal 25 Hz, zero overlap; windows end at annotation boundaries and gaps above 60 ms. Incomplete tails are discarded. Fifteen deterministic time/frequency features carry schema version `riose.signal/1.0.0+unknown-axis-native-v1`.
- Labels/split: source labels are selected using training-animal support only; low-support labels map to a namespaced `other_unselected` bucket without claiming ontology equivalence. Seed 23 split: 18 train animals / 18,274 windows; 6 validation / 5,110; 6 test / 6,524.
- Selection: majority, Logistic Regression, decision tree and Extra Trees compared on validation macro-F1; StandardScaler is fit on training only for selection and refit on train+validation for final fit. The test partition is not used to select, fit, or update the model.
- Output: portable model JSON plus prediction records with source-relative time basis, animal, source row/window references, model/feature versions, dataset provenance and uncalibrated `model_score`. Calibrated confidence remains null.
- Persistence: predictions are written and read back through the existing Core `Store` SQLite adapter's `behavior_predictions` table. No duplicate animal registration or second database architecture was introduced. This validates a local integration boundary, not multiprocess/concurrency safety.
- Downstream: BioSignature reports `INSUFFICIENT_HISTORY`; health is `NOT_EVALUABLE` without clinical outcome labels; reproduction is `INSUFFICIENT_EVIDENCE` without reproductive ground truth. These are not diagnostic or reproductive claims.

Feature-window artifact SHA-256: `0895c67ede95354739d5c76e639c3cbe90ed09f5d4f636162c879667f3dad954` (29,908 rows). Full evaluation, run configuration, acquisition manifest, portable model and SQLite prediction store were saved under the external cache path `.../actbecalf/mini-mvp4-e2e-final/`; the clean replay is saved under `.../actbecalf/mini-mvp4-clean-repro/`. Clean replay model JSON SHA-256: `a81ab309b458553a45f315220468fc129a8ccb2abade88d460127ea376b2979f`.

## Verification

Python regression suite: **656 passed, 7 skipped**, one Starlette/httpx deprecation warning; canonical baseline was 617 passed / 7 skipped. `compileall` completed successfully. `git diff --check` completed successfully. Focused tests previously passed 58/58. Full and clean replay status was `EXTERNAL_MEASURED_DATA_MODEL_EVALUATION`. Clean replay exactly reproduced feature SHA, model artifact SHA, split, model selection, holdout metrics, grouped-CV metrics and leakage audit. Run-config files differ for output path/runtime metadata. The replay snapshot fingerprints CLI `aced9750407ce272c584b1cbcd3cead76751d8738bdb24e7e663428564b0c461`, signal engine `e5be68207cb1e1fd76deaeb2c7a0571e685f24c8ccc35412e409974d9496a020`, SQLite store `4c99a4607b9243f666d5a50b98a8143737fc971db11e018471da9f28ec4779ee`, grouped CV `ddff9d8f9916db94212944471723127243014b49d0a2281f2277d1afe0f92621`, pipeline `1843b094aa9e8b95dcf54bff7b2f8093c4fb1f75525441a0a3bb6db0b4469846`, and intelligence domain `de3451651a7339a00a9c95fe3e4e2fb7540c7ac469f3fd9b76206aa837addedb`. After replay, the only source adjustment was restoring the pre-existing behavior-history query limit from 10,000 to 1,000; it does not affect the behavior replay. The final SQLite store source SHA-256 is `078cc50e44feaa0d4f706a2cbf32c7dd2740de63596db82852fa9743ece25064`. The full suite was rerun after this adjustment.

Independent red-team review found and drove fixes for replay idempotency timestamps, malformed model-tree validation, majority tie behavior, single-class grouped-CV folds, test-only class leakage, and logistic-regression coefficient dimensions. Focused tests cover these cases. No animal/scaler/test-selection leakage, SQL injection, or duplicate persistence architecture issue was identified. Field performance was not evaluated.

## Workspace Reconciliation

- `REMOTE_NAME`: `fork`
- `REMOTE_URL`: `https://github.com/GUZZBR1/riose.git`
- `REMOTE_MAIN_SHA`: fetch unavailable (DNS failure); last local remote-tracking SHA `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`
- `EXPECTED_CHECKPOINT`: `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`
- `PRE_RECONCILIATION_HEAD`: `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`
- `ORIGINAL_BASE`: `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`
- `MERGE_BASE`: `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed` (with last locally available `fork/main`)
- `DIRTY_STATE_BEFORE`: mission edits present; no unrelated edits were observed
- `RECOVERY_REF`: `refs/recovery/mini-mvp-intelligence-behavior/pre-reconcile` (exact pre-reconciliation state, commit `b05ade1b02ffd23eb5d65d485156d0a7139e3fee`); `refs/recovery/mini-mvp-intelligence-behavior/pre-clean-repro` preserves the implementation snapshot for clean reproduction (`a6d3b49397344a60cdd1618d8f94e7e0ba95a2f8`)
- `RECONCILIATION_CLASS`: `E — WORKTREE_STATE_UNCERTAIN` because a live remote fetch could not verify the current remote head
- `RECONCILIATION_ACTION`: retained mission work on the isolated worktree, verified local ancestry against the expected checkpoint and local tracking ref; no rebase/reset/merge
- `POST_RECONCILIATION_BASE`: `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed`
- `POST_RECONCILIATION_HEAD`: `3b5aaa634a800d1cb9f2d0060cf53c8ffe6901ed` (mission source is uncommitted)
- `CANONICAL_CAPABILITIES_REUSED`: current signal contracts; intelligence prediction domain contract; Core SQLite `Store`; current product and movement dataset infrastructure
- `LOCAL_CHANGES_SUPERSEDED`: none identified; historical model implementation was selectively adapted and independently evaluated
- `CONFLICTS_RESOLVED`: no Git conflicts; unknown axis units and source time were explicitly preserved rather than guessed
- `TESTS_AFTER_RECONCILIATION`: focused suite 58 passed; full Python suite 656 passed / 7 skipped; compileall and diff check passed

The fetch failure leaves remote advancement unverified. No main modification, push, PR or merge occurred. No historical evidence was rewritten.

## Promotion and limitations

Movement parsing/features and prediction boundary are reusable optional product capabilities, subject to measured RIOSE inputs and documented units/time semantics. Behavior ML remains research. Persistence integration reuses Core but this run does not test concurrency. BioSignature stays experimental, Health anomaly stays research, and Reproduction remains research. Public measured data does not establish RIOSE lab or field validation. Dataset rights, unknown physical units/timezone, sparse/uneven animal coverage, label imbalance and weak minority-class performance remain limitations.

**Push:** NO · **PR:** NO · **Main modified:** NO · **Factory review ready:** YES, as a research baseline with limitations.
