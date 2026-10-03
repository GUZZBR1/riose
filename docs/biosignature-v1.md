# Movement BioSignature V1

BioSignature is an offline, non-diagnostic comparison of one animal's current fixed-duration behavior profile with that animal's earlier profiles in the same time stratum and behavior-model/taxonomy versions. It reports behavioral deviation only; it does not estimate disease, estrus, pregnancy, or cause.

## Inputs and individual baseline

Each BehaviorWindow has the existing animal_id, timestamp, comparable stratum (for example all-day, day, or night), a complete named map of behavior proportions in [0, 1], coverage, confidence, model and taxonomy versions, and the existing EvidenceStatus. A measured absence is represented by proportion 0; None means unmeasured. Windows with insufficient quality or missing features do not get a score. This V1 consumes daily/profile windows, not raw RF events, and does not persist them; callers may adapt local histories or fixtures without depending on the parallel Behavior Persistence issue.

For feature j, animal a, stratum s, model m, taxonomy q and time t, the baseline is computed only from the last W quality-valid, accepted windows strictly before t:

- c_j = median(x_ij)
- MAD_j = median(|x_ij - c_j|)
- scale_j = max(1.4826 * MAD_j, scale_floor)
- z_j(t) = (x_j(t) - c_j) / scale_j
- score(t) = max_j |z_j(t)|

The default threshold is 3.5; scale_floor=0.02 is a regularizer for stable or quantized proportions, not a biologically validated variability estimate. A feature is outside baseline at |z_j| >= threshold. The result includes signed per-feature scores and the baseline median/MAD/scale so the comparison can be audited and reproduced. Threshold, minimum coverage/confidence, minimum history and window sizes are configurable, not fitted on the evaluated series.

The defaults require 7 accepted windows, at least 0.8 coverage, and confidence at least 0.5; these are operational software defaults, not claims that seven days are biologically sufficient. Callers should choose windows/strata that compare like periods. Seasonal or management changes are not inferred.

## Lifecycle, causal updates, and states

- INSUFFICIENT_HISTORY / WARMING_UP: fewer than the configured minimum accepted prior windows. No score and no normality claim.
- INSUFFICIENT_HISTORY / LOW_COVERAGE, LOW_CONFIDENCE or MISSING_FEATURE: the current profile cannot support a comparison. Missing is not rest, normal, or an anomaly. Invalid windows break a consecutive-deviation run.
- INSUFFICIENT_HISTORY / MODEL_VERSION_MISMATCH: prior model/taxonomy history is discarded and the new version warms up independently.
- NORMAL: no configured feature crosses the threshold; this means only within the available individual reference for this comparable stratum.
- DEVIATION: at least one feature crosses the threshold for one window.
- STRONG_DEVIATION: the deviation persists for the configured consecutive windows (default 2). At rebase_after consecutive windows (default 7), the result carries BASELINE_REBASED_AFTER_PERSISTENT_SHIFT and the new regime becomes the reference for later evaluations. Every transition remains in the caller's output history; this is an adaptation rule, not evidence that a persistent change is harmless.

Only a NORMAL window is immediately appended to baseline. Deviating windows are held out so an isolated extreme cannot erase itself. A sustained shift is admitted only after the explicit delayed rebase rule. This allows a long-lived routine change to stop generating stale-reference alerts, while the result stream preserves when it began. For gradual changes that never cross the threshold, the moving reference can adapt; this method is not a change-point or clinical detector.

Evaluation requires one chronological sequence per animal and stratum. Duplicate and out-of-order timestamps are rejected. Model/taxonomy changes reset history. A caller must form separate time-stratum sequences when day/night or other periods are not comparable. No data from later timestamps is read to score an earlier one. Results include animal, timestamp, stratum, baseline extent/count, feature scores/reference values, method/version, quality, model/taxonomy and provenance. Any simulated member/current input keeps result evidence SIMULATED.

The default maximum inter-window gap is 259200 seconds (three days for daily windows). A larger gap clears the baseline and starts warm-up from the current quality-valid profile. Configure it to match the actual interval duration.

## Synthetic scenarios and limits

The test module tests/livestock_tracking/test_biosignature.py and fixture tests/livestock_tracking/fixtures/biosignature_scenarios.csv contain deterministic stable, step-up, step-down, gradual, cold-start, low-coverage, missing-class, version-change and individual-isolation scenarios. They demonstrate software behavior only. The threshold and scale floor are not farm-validated; sensor placement shifts, class-taxonomy drift, correlated/compositional features, low-frequency behaviors, behavior-label error and season/management changes can still produce misleading scores. No field dataset or clinical validation is included. Persistence is intentionally left behind a caller-owned history interface until the canonical behavior history is integrated.
