# Movement behavior ML software MVP

This local package is an offline software baseline for window-level movement
features. It does not implement accelerometer signal processing or infer
behavior from the existing RF datasets.

## Data and evidence boundary

The main branch catalogs external sources, but it does not bundle their real
recordings. ActBeCalf is listed as an open CC BY 4.0 neck AX3 source at 25 Hz;
its 177 MB source file is optional and was not downloaded for this issue. The
only checked-in ActBeCalf sample is a three-row synthetic fixture tagged
`SIMULATED`, with unknown axis unit/timezone, no recording session, and all
canonical labels `UNKNOWN`. Precision Beef is catalog-only and has predicted
labels from another sensor; Japanese Black Beef Cow acquisition is disabled
because its license declarations conflict. None is a defensible real training
set here.

The existing RF observation export is `SIMULATED`, includes `behavior_state`
among its observation fields, and represents localization simulation; using
that field as a movement model input would leak the answer. The LIS2DW12
movement CSVs are generated simulator data without animal/session identity for
animal-held-out behavior evaluation. Neither those sources nor the Dataset
Foundation adapter or Signal Engine are dependencies of this package.

The committed fixture and model artifact use three software-only classes:
`REST`, `WALK`, and `GRAZE`. `RUMINATE`, `EAT`, `UNKNOWN`, disease, and clinical
states are not claimed as detectable. Fixture features are deterministic
synthetic summaries (`accel_mean_g`, `accel_std_g`, `accel_rms_g`); the sensor
position is explicitly `UNKNOWN_SYNTHETIC` and the sample rate is unknown. In
particular, the digital twin's synthetic 12.5 Hz rate is not imposed on other
data. Fixture provenance says the repository has no license declaration; no
third-party dataset is bundled.

Every result and artifact records evidence status, dataset ID/source/license,
sensor position, sample rate (including explicit `null` when unknown), and a
SHA-256 of the exact training records. `SIMULATED` results validate only the
software pipeline; they are not scientific or ear-tag validation.

## Run locally

```sh
uv run python -m riose.products.livestock_tracking.behavior_ml fixture \
  --output datasets/behavior_ml/fixture.json
uv run python -m riose.products.livestock_tracking.behavior_ml train \
  --input datasets/behavior_ml/fixture.json \
  --artifact models/behavior/behavior-baseline-v1.json --seed 23
uv run python -m riose.products.livestock_tracking.behavior_ml predict \
  --artifact models/behavior/behavior-baseline-v1.json \
  --features /path/to/ordered-feature-object.json \
  --sensor-position UNKNOWN_SYNTHETIC
```

For a known sample rate, pass `--sample-rate-hz`; the inference adapter checks
it against artifact provenance. Unknown rates remain null and cannot silently
be interpreted as the digital twin's rate. Feature keys must match the exact
feature contract and order; metadata such as animal ID, dataset ID, session,
timestamp, and labels are never accepted as model inputs.

## Evaluation and artifact

The splitter assigns whole animals to deterministic 60/20/20 train,
validation, and test groups. Since all sessions from an animal stay in that
animal's group, session overlap is also prevented. Duplicate window IDs and
inconsistent session-to-animal assignments fail validation. Candidate
selection compares a majority-class baseline, Logistic Regression, a shallow
Decision Tree, and Extra Trees using validation macro-F1. A simpler model wins
ties. The holdout is scored once after selection; it is not used for candidate
selection or preprocessing. Per-class precision/recall/F1/support, confusion
matrix, accuracy, balanced accuracy, and per-animal metrics are stored.

The JSON artifact contains the portable model parameters/tree arrays, feature
order/version, preprocessing parameters, classes, seed/configuration,
dependency versions, split animal identities, metrics, provenance, evidence
status, and schema/model version. Training reuses the repository's declared
NumPy and scikit-learn dependencies. Artifact loading and prediction use only
Python's standard library (verified without importing either training
dependency); they do not deserialize executable pickle content or require a
remote service. Returned `model_score` is a model score, not a calibrated
probability or certainty.

## REUSE / EXTEND / CREATE / DO NOT TOUCH

- **REUSE:** declared NumPy and scikit-learn dependencies; livestock tracking
  product boundary; `EvidenceStatus`; and explicit simulated-evidence
  conventions.
- **EXTEND:** none. Existing observation exports are incompatible with
  movement-window input and expose a behavior label among observation fields.
- **CREATE:** isolated `behavior_ml` package, JSON window adapter, fixture,
  animal-aware experiment, portable JSON model artifact, CLI, tests, and this
  evidence documentation.
- **DO NOT TOUCH:** RF observation contracts, dataset writer, behavior
  persistence/API implementation, digital twin, hardware firmware, and other
  issue branches. This model MVP does not require the behavior persistence
  contracts or code from issue #24.
- **REPLACE:** none.

## Red team and limits

An apparently excellent random-window score could result from the same animal,
session, duplicate window, animal/dataset identifier, timestamp, or behavior
label appearing on both sides or in the feature vector. Whole-animal grouping,
duplicate identity checks, fixed feature names, training-only candidate
preprocessing, validation-only model selection, and the one-time holdout score
address those paths. Test-time values are excluded from the trained parameters;
the adversarial test perturbs holdout features and asserts model and
preprocessing do not change.

The artifact is a research/software prototype. Sensor-position and sample-rate
provenance checks do not establish domain transfer; training only supports the
metadata actually represented. No health diagnosis is produced, no external
dataset result is claimed, and nothing establishes ear-tag performance.

The committed 144-window fixture run selected Logistic Regression. Its
animal-held-out test has 24 windows from two unseen synthetic animals (8 per
class): accuracy, balanced accuracy, and macro-F1 are all 1.0; the
majority-class baseline has accuracy and balanced accuracy 0.333 and macro-F1
0.167. These deliberately separable synthetic summaries demonstrate that the
software metrics and serialization work; they are not behavior-performance
evidence. The artifact also contains all four validation candidate scores and
per-class, per-animal, and per-dataset results.

## Future edge budget (ENGINEERING_ESTIMATE)

The committed Logistic Regression artifact is about 8 KiB and uses three
scalar features. In a local CPython run, 1,000 loaded-artifact inference calls
took about 0.013 seconds total (about 0.013 ms/call); this short workstation
micro-measurement excludes interpreter startup and is not STM32 latency. The
JSON model arrays and feature vector need only a few KiB; resident memory is
dominated by the Python runtime and scikit-learn during training. A shallow
tree or fixed 40-tree Extra Trees candidate has higher inference work. These
are `ENGINEERING_ESTIMATE`s, not measured STM32 RAM/flash/latency. TinyML or
firmware deployment is not included.
