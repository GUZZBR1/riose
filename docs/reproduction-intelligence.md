# Reproduction intelligence (experimental)

## Scope and evidence boundary

This small, offline module creates a descriptive activity summary aligned to a
separately typed reproductive event. It is not a classifier, fertility score,
pregnancy-likelihood model, or veterinary tool. A numeric activity-change ratio
is descriptive only; model score and confidence are deliberately `null`.
The included fixture is synthetic and verifies software contracts only.

The current branch contains no paired, licensed reproductive event and movement
dataset that this project has independently processed. Therefore this release
reports no measured model performance, no confusion matrix, and no predictive
association estimate. The cited paper metrics below are published results, not
RIOSE reproductions.

## Event ontology and labels

`ReproductiveEventType` keeps estrus, insemination, mating, positive/negative
pregnancy examination, calving, pregnancy loss, and unknown as distinct event
types. `EventSource` keeps veterinary examination, hormone test, insemination
record, observed calving, user entry, simulation, model output, behavior signal,
and unknown provenance distinct. Model or behavior outputs cannot be declared
validated ground truth. Events store both occurrence and record timestamps so
retrospective labels remain auditable.

Only activity observations for the same animal and at or before the event
occurrence enter the feature summary; callers must set `observed_at` to the
time the feature was available to analysis. Event labels anchor retrospective windows
and never enter the activity features. The event's record timestamp is emitted
separately from occurrence time, and feature source references are preserved.
Samples after the event are discarded, and sensor-position mixtures are
rejected instead of pooled. Animal split validation rejects overlap across evaluation partitions. The
current implementation does not fit or evaluate a model; split validation is a
guard for any future evaluation code.

The descriptive windows default to the 24 hours before the event and the
preceding 24-hour reference interval. Fewer than two values in either interval,
or an incomplete baseline, yields `INSUFFICIENT_EVIDENCE`. Signed activity
indices are accepted; when the baseline is zero or negative the absolute
activity change is retained but the ratio is omitted. These engineering defaults
are not claims that these windows are scientifically optimal. A reported change
is not a risk probability or a calibrated score.

## Primary sources and dataset claims

| Target / question | Primary source and dataset | Population, sensor, timing, labels / ground truth | Evidence class, confidence, quantitative verification and limits |
|---|---|---|---|
| Estrus and general activity | Lardy et al., *Understanding anomalies in animal behaviour: data on cow activity in relation to health and welfare*, 2022, [DOI 10.1016/j.anopes.2022.100004](https://doi.org/10.1016/j.anopes.2022.100004). Public dataset: [INRAE data DOI 10.15454/52J8YS](https://doi.org/10.15454/52J8YS). | Four farm datasets: 28, 28, 30, and 300 cows; first two experimental-farm datasets and latter two commercial farms; periods six months, two months, 40 days, and one year. Neck-collar radio tags with barn RTLS position every second; activities inferred from location, then summarized hourly. Caretakers recorded estrus, calving, health, management, and disturbance events. | `DATASET_EVIDENCE` / `SCIENTIFIC_EVIDENCE`; confidence high for source metadata, low for RIOSE transfer. Dataset is publicly accessible under Etalab Open License 2.0; archival download is about 163 MiB, so not vendored. Position-derived activity is not an accelerometer; caretaker records are not hormone-confirmed labels in the data paper. No RIOSE quantitative verification performed. |
| Estrus and multiple conditions | Lardy et al., *Discriminating pathological, reproductive or stress conditions in cows using machine learning on sensor-based activity data*, 2023, [DOI 10.1016/j.compag.2022.107556](https://doi.org/10.1016/j.compag.2022.107556); data: [INRAE DOI 10.15454/52J8YS](https://doi.org/10.15454/52J8YS). | Five datasets, about 120,000 cow-days; 28–300 Holsteins per dataset; 1–12 months; hourly activity from location systems or accelerometers; caretakers recorded event types including estrus and calving. | `SCIENTIFIC_EVIDENCE`; moderate confidence that the paper reports the findings, low transfer confidence. Authors report 57–86% probability of detecting at least one 24-hour series around disease, estrus, or calving and 46–89% false alarms. This is mixed multi-condition, not estrus-only. Evaluation used repeated random 70/30 splits; the abstract does not establish animal-disjoint validation. Source checked, not reproduced by RIOSE. |
| Estrus signal | Hockey et al., *Detecting heat events in dairy cows using accelerometers and unsupervised learning*, 2017, [DOI 10.1016/j.compag.2016.12.009](https://doi.org/10.1016/j.compag.2016.12.009). | Pasture-based dairy cows; collar accelerometer activity, clustered time windows; heat-event labels compared with records using milk progesterone, calving date, and patches as described in the paper. | `SCIENTIFIC_EVIDENCE`; low confidence for transferability. Abstract reports 82–100% accuracy and 100% sensitivity for its method. Source figures checked against abstract only, not independently reproduced. Raw dataset availability/license not established. Collar evidence does not validate an ear tag. |
| Calving | Rutten et al., *Sensor data on cow activity, rumination, and ear temperature improve prediction of the start of calving in dairy cows*, 2017, [DOI 10.1016/j.compag.2016.11.009](https://doi.org/10.1016/j.compag.2016.11.009). | 400 cows at one Dutch dairy farm over one year; synthesized ear-tag hourly activity, rumination, feeding, and temperature; 417 starts recorded by camera, 114 linked to sensor data. | `SCIENTIFIC_EVIDENCE`; low confidence for transferability. Authors report model sensitivity 36.4% at 1% false-positive rate and low sensitivity for a specific hour. Model includes expected calving date and multiple signals, not activity alone. Source-reported only; not reproduced. |
| Calving / ear-tag transfer | Borchers et al., *An ear-attached accelerometer as an on-farm device to predict the onset of calving in dairy cows*, 2019, [DOI 10.1016/j.biosystemseng.2019.06.011](https://doi.org/10.1016/j.biosystemseng.2019.06.011). | Right-ear tri-axial accelerometer attached four weeks before expected calving; 894 calving datasets eligible; algorithm uses individual/group activity, lying, and rumination; horizons through 72 hours before calf expulsion. | `SCIENTIFIC_EVIDENCE`; low confidence for RIOSE transferability. Source reports best balanced accuracy 74% and sensitivity 54% at one hour. Authors call for multi-system validation. Ear location alone does not validate RIOSE hardware, population, protocol, or model. Source-reported only; not reproduced. |
| Pregnancy loss caution | Chen & Ferreira, *Evaluation of walking activity data during pregnancy as an indicator of pregnancy loss in dairy cattle*, 2023, [DOI 10.3168/jdsc.2022-0304](https://doi.org/10.3168/jdsc.2022-0304). | Retrospective records from a 250-cow herd, 2018–2021; leg-based pedometer daily steps; pregnancy records include insemination, ultrasound diagnoses, calving, and abortion. The paper reports 537 pregnancies and 118 activity peaks. | `SCIENTIFIC_EVIDENCE`; moderate confidence in the caution for this pedometer setting. Authors observed peaks during confirmed pregnancies and conclude peaks should not be interpreted as pregnancy losses. This rebuts a simple activity-spike rule; it is not a general loss detector study. Source-reported only; not reproduced. |
| Pregnancy loss modeling | Lin et al., *Transformer neural network to predict and interpret pregnancy loss from activity data in Holstein dairy cows*, 2023, [DOI 10.1016/j.compag.2023.107638](https://doi.org/10.1016/j.compag.2023.107638). | 185 Holsteins at one New York commercial farm, Mar 2020–Mar 2021; Allflex neck-mounted 3-axis accelerometer tag, activity every two hours; veterinary transrectal ultrasound used for pregnancy/loss confirmation. | `SCIENTIFIC_EVIDENCE`; low confidence for transferability. Paper reports best 14-day, 90%-overlap setting and 5-fold CV metrics. Overlapping windows make evaluation sensitive to split design; abstract does not establish external validation. Neck sensor is not RIOSE ear-tag capture; data access/license not verified. Source metrics not independently reproduced; RIOSE defers inference. |
| Pregnancy status / loss | No suitable public, RIOSE-accessible movement dataset with independently verified status and complete provenance was established for this implementation. | Pregnancy needs explicit examination/test labels, timing, and separate positive/negative outcomes; movement cannot supply these labels. | `INSUFFICIENT_EVIDENCE`; confidence not applicable; quantitative verification unavailable. No pregnancy-likelihood or pregnancy-loss signal is implemented. `REQUIRES_RIOSE_FIELD_VALIDATION` applies to future RIOSE sensor claims. |

### Public dataset feasibility check

INRAE dataset 3 is the most relevant small candidate for estrus: 30 cows at
three commercial farms for 40–41 days, 26,224 hourly records (10.4% missing),
with daily milk progesterone and an estrus label defined by a progesterone drop
for at least three consecutive days. The public record marks files as public
and specifies Etalab Open License 2.0. The tab file was downloaded to temporary
storage and inspected; it has 30 animal IDs, an hourly `ACTIVITY_LEVEL` column,
and 624 rows marked `oestrus=1`. Its activity index is a weighted sum of time
spent eating, resting, and in alleys, rather than raw movement. The dataset
documentation does not establish a timezone or unambiguously explain whether
each row's hour timestamp marks the start or availability time of that hourly
aggregate. RIOSE therefore does not use it to claim a temporal feature result
or performance metric. No dataset content is committed.

### Claim classification

- **Scientific evidence:** the cited studies support that certain activity or
  behavior measurements were associated with particular event labels in their
  studied farms, sensors, and protocols.
- **Dataset evidence:** INRAE records expose hourly activity and recorded event
  types from four farms. It is a viable candidate for future adapter work, but
  its license and file-level schema must be checked before any integration.
- **Engineering inference:** occurrence/record timestamps, same-animal feature
  filtering, explicit sensor position, and separate event types reduce common
  software leakage and provenance errors; they do not establish biology.
- **RIOSE hypothesis:** event-aligned behavior changes may be worth studying
  after an appropriate dataset, target protocol, and confounder plan are
  available.
- **Requires RIOSE field validation:** all biological claims on RIOSE capture,
  especially movement from its ear-tag hardware and any pregnancy target.

## Confounders, metrics, and deferred work

Activity and location can vary with feeding, milking, housing, weather/heat
stress, lactation, health, handling, breed, parity, and sensor placement. The
available studies use different populations, sensors, event protocols, and
sampling intervals. Correlation does not establish causation. Literature
accuracy, sensitivity, specificity, F1, AUC, or lead-time figures are not
comparable without matching target definitions, denominators, splits, and
alert thresholds. No thresholds are optimized here.

Estrus, pregnancy status, pregnancy loss, and calving are kept separate.
Pregnancy confirmation/negative events can be recorded as source data but are
not model targets. Pregnancy likelihood and pregnancy loss are deferred due to
missing project-validated ground truth and an unverified, licensable joined
dataset. The current reports have no sensitivity, specificity, precision,
recall, AUC, false-positive/negative, lead-time, class-imbalance, or external
validation results because the local fixture is synthetic and no scientific
evaluation dataset was run.

## Offline demonstration

Run `python -m riose.products.livestock_tracking.reproduction_demo` from the
repository root. It emits one deterministic synthetic estrus-aligned summary,
retains `SIMULATED`, includes the sensor position, and leaves score/confidence
null. It needs no cloud service, RPC, or downloaded dataset.
