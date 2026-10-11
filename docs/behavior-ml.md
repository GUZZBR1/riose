# Offline behavior classification research

RIOSE's signal engine can produce deterministic movement features from XYZ
samples. The optional behavior research module consumes already-windowed,
finite numeric feature maps and labels; it does not read raw sensors, download
datasets, run during tracking, or write to persistence. Core owns any future
prediction storage integration.

## Inputs and unit handling

Each training window supplies an animal ID, session ID, behavior label,
ordered feature map, evidence status, dataset/source/license metadata, and an
explicit feature schema. The only accepted schemas are the synthetic software
fixture and the registered RIOSE signal-engine output. The schema records a
stable ID, version, extractor, unit for each feature, and a definition for each
feature. Training and grouped evaluation reject unregistered or mixed schemas;
inference requires the same schema as the model. The descriptor does not prove
that an external caller actually produced values with the registered
extractor, and it cannot certify that caller-provided feature values are free
from target or future-information leakage. It is a schema consistency check,
not a trusted ingestion boundary. External measured-data runs must only use
feature maps produced by a trusted signal-engine ingestion path; caller-supplied
maps must be treated as unverified. This limitation is copied into each model
artifact's evidence interpretation. The pipeline also requires one sensor
position, sample rate, and signal-engine window configuration per training run.
For registered signal features, windows retain duration, sample and stride
counts, overlap, jitter tolerance, source rate, and resampling provenance;
inference must provide the same configuration. Labels and other metadata are
kept outside the feature map. Shareable reports include animal counts and
aggregate per-animal metrics, not raw animal identifiers.
The behavior classifier does not convert sensor values. The signal engine
converts supported acceleration units to canonical g and emits the registered
15-feature schema. Its required sample rate is retained as model provenance.
Unknown source units are rejected by the signal engine rather than inferred.

The included REST, WALK, and GRAZE window generator exists only to exercise
software behavior. Its feature names use `native`, its evidence is SIMULATED,
and its labels are not observations about real animals. These are the only
labels asserted by the bundled test fixture. External callers provide their own
labels; RIOSE does not claim that any behavior can be distinguished reliably.

## Evaluation and provenance

The holdout split keeps all sessions and windows from one animal together in a
deterministic 60/20/20 train, validation, and test split. Candidate selection
uses validation macro-F1 over the train/validation label set; the held-out test
set is evaluated once and does not affect candidate selection. The grouped
cross-validation helper holds out animals with
GroupKFold. It fits feature scaling and chooses eligible labels from each fold's
training animals only, then reports the model beside a majority-class baseline.
Small cohorts or class-poor folds can be insufficient to evaluate; the metrics
are engineering outputs, not a quality threshold.

Saved model artifacts retain dataset source and license declarations, feature
order and version, the homogeneous sample-rate and sensor-position condition,
evidence status, model version, and separate digests for train,
train-plus-validation, holdout, and all evaluation windows. Per-split metadata
records animal counts but does not expose animal identifiers. SHA-256 window
and source digests are unsalted; they can confirm membership when a candidate
input is already known, so artifacts must follow the source dataset's sharing
policy. A source digest
provided with `source_provenance_attested` is caller-attested metadata; this
pipeline does not open the source file or verify that digest. A model score is
not a calibrated confidence. Prediction contracts keep model and input
provenance attached and define a persistence seam without requiring a database.
Source evidence statuses remain in model provenance. Each model output is
marked `EXPERIMENTAL`; source data marked `VALIDATED` does not validate the
classifier or its prediction.
UTC prediction creation time must be at or after the UTC input-window end. For
source-relative windows, callers must establish the causal relation to the UTC
creation clock outside this contract.

## Scope and limitations

This is research/experimental infrastructure, not field validation. It makes no
animal-health or veterinary diagnosis claim and does not establish on-ear-tag
performance. Synthetic tests establish data-contract, determinism, grouping,
and metric-calculation behavior only; they do not establish classifier quality.

ActBeCalf integration is deferred pending license review. The source repository's
audit found the Zenodo record's License field empty, and an existing fork-side
acquisition docstring incorrectly described it as CC BY. This contribution
therefore includes no ActBeCalf adapter, downloaded samples, derived samples, or
model weights. Tests use only a small deterministic synthetic fixture generated
in code.

The module has no blockchain dependency or publication path.
