# Issue #28 — Movement + RF Context (experimental mini-MVP)

## Contract and boundaries

`RFObservation`, `Estimate`, `Anchor`, and `EvidenceStatus` are reused from
`livestock_tracking.domain.contracts`. Movement data has its own
`MovementObservation` contract because movement and RF are independent sources.
The `from_rf_hooks` adapter reuses the existing `imu_accel_norm_g` and
`behavior_state` fields while retaining their provenance and evidence status;
it does not gate those hooks on packet receipt or interpret raw g as an
activity score. A movement classifier or fixture must supply its own normalized
`activity_level` before the simple movement baseline can classify immobility.
No RF stack, localizer, tag identity, persistence, network adapter, or zone
semantics were added.

The context consumer is `assess_movement_rf_context`. It accepts an opaque
`tag_id`, query timestamp, optional movement sample, existing RF observations,
and optional existing localization estimate. It emits source-level statuses,
the untouched source records, quality, evidence status, provenance, baseline
outputs, and a combined state. Coordinates never generate a behavior label.
Identity matching uses exact opaque `tag_id` equality because the canonical
`RFObservation` carries no `animal_id`; no inferred mapping is introduced.

## Alignment and quality

The default tolerance is **5 seconds**, configurable with
`alignment_tolerance_s`. Each source must be within that window of the query;
when both are present, the movement/RF pair must also be within the same
window. The nearest RF epoch is selected only after filtering by exact tag ID.
No clock correction is guessed: movement `clock_id` must equal the supplied
`rf_clock_id` when RF data exists. Missing/non-finite timestamps are rejected.
Out-of-order RF samples are handled deterministically by epoch time; identical
same-anchor duplicates collapse, conflicting same-anchor duplicates invalidate
that epoch. Samples outside tolerance remain visible as source data but are
marked stale and are not fused.

RF statuses distinguish `OBSERVED`, `LOW_QUALITY`, `PACKET_LOSS`,
`NO_OBSERVATION`, `STALE`, and `INVALID`. RF quality is the received-packet
fraction for the selected epoch; the configurable minimum defaults to 0.5.
Localization status is assessed separately using the existing estimate's
quality and an independent quality threshold. Movement quality also has its
own threshold, so a stricter RF rule does not silently change movement status.
A poor estimate remains visible as `LOW_QUALITY`; it cannot become an exact
location or alter a movement label. Anchor identity is validated when the
caller supplies its configured `allowed_anchor_ids` inventory.

Movement status distinguishes `OBSERVED`, `LOW_QUALITY`, `MISSING`, `STALE`,
and `INVALID`. Missing activity is never converted to zero. The simple
movement-only rule calls low observed activity (`<= 0.1` by default)
`APPARENTLY_IMMOBILE`; unknown or low-quality movement abstains. `REST` labels
remain source claims and are not ground truth.

## Evidence policy

Every source retains its own `EvidenceStatus`. The derived status takes the
least empirical status among inputs, with priority `FUTURE`, `SIMULATED`,
`ASSUMED`, `EXPERIMENTAL`, then `VALIDATED`. Therefore a simulated input cannot
be promoted to validated by fusion. Synthetic fixture ground truth stays
synthetic; this code makes no field-validation claim.

## Controlled baseline comparison

The test fixture evaluates four labeled binary cases for the issue's narrow
question: distinguish apparently immobile with contemporaneous observability
from insufficient observability. Metric: exact correct classifications divided
by four. Baselines abstaining or returning the wrong class count as incorrect.

| Fixture case | Expected | Movement only | RF only | Combined |
|---|---|---|---|---|
| Low activity + recent usable RF | Immobile | Immobile | Behavior unknown | Immobile |
| Both sources absent | Insufficient | Unknown | Insufficient | Both missing |
| Low activity + contemporaneous packets | Immobile | Immobile | Behavior unknown | Immobile |
| Low activity + stale RF | Insufficient | Immobile (false positive) | Insufficient | RF observability lost |

| Method | Correct / 4 | Accuracy on this fixture |
|---|---:|---:|
| Movement only | 2 / 4 | 50% |
| RF only | 2 / 4 | 50% |
| Combined | 4 / 4 | 100% |

The observed gain is **fixture-scoped only** (4/4 vs 2/4 on these four
deterministic cases). This is not an independent holdout evaluation, field
accuracy, animal-behavior validation, or a product recommendation. Results
must not be generalized beyond these cases.

## Limitations

- The current canonical RF contract has one timestamp and tag identity per
  anchor observation, no clock identifier, and no anchor inventory attached
  to an observation. The consumer takes the RF clock identity and optional
  allowed-anchor inventory from its caller.
- RF-only can assess packet observability; it cannot infer immobility.
- Position quality is reported but not fused into the behavior decision.
- Fixture labels and estimates are simulated; there is no physical ground truth
  or field validation in this change.
- No zone classification is performed.
- Not tested: concurrent live sensors, synchronized hardware clock calibration,
  or field performance.

## Verification

Focused tests cover available/missing source combinations, packet loss, stale
and low-quality data, temporal boundary and mismatch, incompatible clocks,
duplicates, out-of-order input, cross-tag protection, optional anchor checks,
localization quality, unknown movement, provenance/evidence preservation,
baseline comparison, determinism, and offline use.
