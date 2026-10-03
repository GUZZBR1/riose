# Experimental behavior-deviation screen

## Scope and output contract

This offline experiment asks whether a behavior summary differs materially
from the same animal's recent history. Its only positive output is
`INVESTIGATE`, with behavior reason codes such as `ACTIVITY_DEVIATION` and
`RUMINATION_DEVIATION`. `NO_SIGNIFICANT_BEHAVIORAL_DEVIATION` describes only
the measured window; it does not mean healthy and does not rule out disease.
`INSUFFICIENT_DATA` is used for missing current observations, cold starts, or
inadequate per-metric coverage. No clinical diagnosis, treatment, urgency, or
disease probability is produced.

The API records animal ID, observation time, sensor position, measured
summaries, baseline interval/count, robust score, threshold, reason codes,
input evidence statuses, derived evidence status, and limitations. Activity
and step metrics are caller-defined non-negative units; rumination is minutes
per 24-hour interval. Consistent definitions are required across observations.
Missing values remain missing; they are never converted to zero.

## Method

For an observation at time `T`, the analyzer uses at most the last seven
strictly earlier observations for the same animal and exact sensor position.
It never reads observations after `T`. Each feature needs seven non-missing
baseline values and is compared with its own baseline median. The robust scale is `max(1.4826 × MAD, floor)` where
the scale floors are engineering safeguards: 1 activity unit, 5 rumination
minutes, and 5 steps. The reported score is the maximum absolute robust
z-score over features with at least seven valid baseline values. A score at or
above 3.5 yields `INVESTIGATE`. The defaults are experimental engineering
choices, not literature-derived clinical cutoffs; callers can set the minimum
baseline size and threshold explicitly.

There is no model training, health label, train/test split, or threshold tuning
in this MVP. Each animal is its own baseline. Another animal, a different
sensor position, or future rows cannot contribute. A missing metric is omitted
from scoring; if no metric has adequate coverage, the result is inconclusive.
An all-missing current row therefore yields `INSUFFICIENT_DATA`, not a health
alert or normal result. The API does not estimate packet-loss rates or
diagnose hardware failure; sensor failure must be handled by the upstream
quality layer and represented here as missing coverage.

## Evidence catalogue

Evidence classes below distinguish published associations from this software
experiment. Findings do not imply causality or transfer directly to another
population, device, management system, or sensor location.

| Source and population | Sensor / sampling | Independent health reference | Result and limitation |
|---|---|---|---|
| Gusterer et al. (2020), *Sensor technology to support herd health monitoring: Using rumination duration and activity measures as unspecific variables for the early detection of dairy cows with health deviations*, [DOI 10.1016/j.theriogenology.2020.07.028](https://doi.org/10.1016/j.theriogenology.2020.07.028). 312 multiparous Holstein-Friesian cows from one Slovakian dairy farm, observed from 14 d pre-partum to 8 d in milk; 156 had no recorded disorder, 65 had one, and 91 had multiple disorders in the first 8 d in milk. | SMARTBOW ear-tag 3D accelerometer; daily activity and rumination summaries. Raw sampling and classifier details are device-specific. | Farm clinical health records / examinations; the outcome was health deviation, not one universal disease label. | Authors describe the measures as unspecific and report group associations around diagnosis. Confidence in the cohort association: **moderate**; this is observational, in one farm and transition period, with multiple disorders and commercial algorithms. Manufacturer-employed coauthors limit independence. This is ear-position literature, not validation of RIOSE hardware or this threshold. |
| Stangaferro et al. (2016), *Use of rumination and activity monitoring for the identification of dairy cows with health disorders: Part I. Metabolic and digestive disorders*, [DOI 10.3168/jds.2016-10907](https://doi.org/10.3168/jds.2016-10907). 1,121 enrolled Holsteins (1,080 analyzed) on a dairy farm; 54 ketosis, 41 displaced-abomasum, and 9 indigestion events among 104 combined metabolic/digestive cases. Monitoring covered at least 21 d before through 80 d after calving. | Neck-mounted HR tag; rumination and activity recorded in 2-hour periods and summarized daily; device generated a proprietary health index. | Farm-personnel clinical diagnoses using specified criteria; ketosis also used urine ketones and expected milk-production change. Some case definitions include appetite/production signs that may overlap with behavior, weakening independence. | Reported sensitivity: 91% for ketosis (54 events), 98% for displaced abomasum (41), 89% for indigestion (9); specificity/precision are not reported in the abstract. The alert window included days after diagnosis (−5 to +2), so sensitivity is not prospective performance at a single cutoff. Confidence in group association: **moderate**; low-to-very-low confidence for transport to other sensors or farms. Neck position is not ear validation. |
| Gardaloud et al. (2022), *Early Detection of Respiratory Diseases in Calves by Use of an Ear-Attached Accelerometer*, [DOI 10.3390/ani12091093](https://doi.org/10.3390/ani12091093). 508 weaned dairy calves on one Slovakian farm; 41 diseased calves and 69 matched controls in the model comparison. | SMARTBOW 10 Hz accelerometer on the left ear; classified behavior aggregated to minutes/hour; at least 40 of 60 minutes required for a valid hour; records evaluated from 7 d before to 1 d after diagnosis. | Daily veterinarian calf scoring, clinical exam, fever and clinical signs; BRD required score and fever criteria on two consecutive days. | Activity/lying differences were observed; best reported out-of-sample AUC was 0.83, sensitivity 71.4%, specificity 95.2%. Confidence in this cohort's association: **limited**; the diseased sample was small, controls outnumbered cases, the device's proprietary behavior algorithms were used, and larger studies were requested. The out-of-sample split was not reproduced or established as animal-independent in this work; those metrics are literature results only, not RIOSE performance. |
| Rial et al. (2023), *Metritis and clinical mastitis events in lactating dairy cows were associated with altered patterns of rumination, physical activity, and lying behavior monitored by an ear-attached sensor*, [DOI 10.3168/jds.2022-23157](https://doi.org/10.3168/jds.2022-23157). 616 no-disorder, 69 metritis-only, 36 mastitis-only, 25 metritis-plus, and 15 mastitis-plus lactating Holsteins (761 total), monitored daily during the first 21 d in milk. | Ear-attached accelerometer; daily rumination, physical activity, and lying summaries; changes analyzed around clinical diagnosis. | Clinical diagnoses with explicit inclusion criteria; severe cases and co-occurring disorders separately grouped. | Several group differences were observed before/around diagnoses, generally larger for multiple disorders. Confidence in the group associations: **moderate**; observational associations do not identify a condition in an individual. No RIOSE sensor or algorithm validation is implied. Open access under CC BY. |
| Antanaitis et al. (2024), *Alterations in Rumination, Eating, Drinking and Locomotion Behavior in Dairy Cows Affected by Subclinical Ketosis and Subclinical Acidosis*, [DOI 10.3390/ani14030384](https://doi.org/10.3390/ani14030384). 320 German Holsteins selected from one Lithuanian farm, measured 5–30 d after calving (112 subclinical ketosis, 102 subclinical acidosis, 106 controls). | RumiWatch noseband pressure sensor plus pedometer; behavior summarized in min/h and movement measures. Sampling frequency is not specified in the reviewed methods. | Veterinarian examination, milk fat/protein ratio, blood beta-hydroxybutyrate; subclinical acidosis used rumen motility, milk ratio and fecal signs. | Group differences included rumination/eating/locomotion. The authors explicitly studied short-term association, not early diagnosis. Confidence in association: **limited**; one farm, narrow postpartum window, defined groups and management. Data are stated as included in the article; open access CC BY. Noseband/pedometer are not ear-tag validation. |
| Thorup et al. (2015), *Lameness detection via leg-mounted accelerometers on dairy cows on four commercial farms*, [DOI 10.1017/S1751731115000890](https://doi.org/10.1017/S1751731115000890). 348 Holsteins across four farms, including repeated lactations. | Hind-leg accelerometers; daily lying, standing, walking, steps and motion summaries; features summarized over the week before locomotion scoring. Sampling frequency is not specified in the reviewed abstract. | Human locomotion score, assessed about 2.4 times per lactation on average. | Confidence in a sensor-position-specific association: **moderate**. The position is the hind leg, not ear; the inspection cadence and management context limit event timing and transfer. |

These are qualitative confidence descriptions for the reported study association,
not a formal evidence-grading scale. Confidence that any result transfers to
RIOSE hardware, target herds, or an individual diagnosis is **very low / not
established** for every source.

Stress and pain are not treated as detectable endpoints here. No independent,
target-compatible labeled dataset or validated threshold was established for
them in this review. Disease-specific use for ketosis, acidosis, mastitis,
metritis, respiratory disease, digestive disease, or lameness is likewise
**DEFERRED**: the cited studies motivate an investigation signal only; they do
not make this rule-based score a condition detector.

### Dataset assessment

The open [Precision Beef behavior dataset (Zenodo 10.5281/zenodo.4064802)](https://doi.org/10.5281/zenodo.4064802) is attributed to Pavlovic et al. and collaborators and listed as [CC BY by OpenAIRE](https://explore.openaire.eu/search/dataset?pid=10.5281%2Fzenodo.4064802). It covers 18 cattle over three farm trials, with collar 3-axis acceleration at 10 Hz and Rumiwatch halter pressure/classification at 10 Hz. Its labels are `Eating`, `Rumination`, and `Other`, not independent clinical diagnoses. The files total about 8.2 GB. It is suitable for behavior/sensor work under its license, not health-anomaly efficacy; this MVP does not download or train on it.

No eligible, legally accessible health-labeled dataset was integrated. Dataset ground truth is therefore **UNKNOWN for this implementation**; no treatment event or low-activity proxy is presented as a diagnosis. Clinical status in the cited studies came from separate veterinary or farm assessments. Their study definitions and populations are summarized above rather than imported as this tool's labels.

## Claims and evaluation boundaries

**SCIENTIFIC_EVIDENCE:** Specific cohorts report associations between activity/rumination/lying changes and independently recorded health events. **DATASET_EVIDENCE:** The open Precision Beef dataset supports only its behavior labels. **ENGINEERING_INFERENCE:** A within-animal median/MAD screen can flag unusual measured values without asserting why they changed. **RIOSE_HYPOTHESIS:** That a RIOSE ear-tag installation can produce sufficiently stable behavior summaries for this comparison. **REQUIRES_RIOSE_FIELD_VALIDATION:** sensor accuracy at the ear, data coverage, operating thresholds, alert burden, clinical utility, and sensitivity/specificity in target herds.

No health-labeled evaluation is available, so precision, recall/sensitivity,
specificity, F1, AUPRC, confusion matrix, false-positive rate, false-negative
rate, and clinical alert rate are **NOT TESTED / INSUFFICIENT_EVIDENCE**.
Accuracy would be misleading without an appropriate event prevalence and
animal/time-aware holdout. The cohort event fractions above are not assumed to
represent farm prevalence. Synthetic scenarios test software behavior only;
they provide no estimate of clinical performance.

Potential non-health explanations include heat, management, transport,
feeding changes, estrus/reproduction, calving, stress, housing, age, recovery,
and device placement/failure. The current scoring does not adjust for
environment, management, time of day, season, parity, lactation stage, or
reproductive state. A stable screen can miss disease (false
negative); unusual behavior can prompt investigation without a clinical
cause (false positive). No specific condition, including lameness, mastitis,
respiratory disease, ketosis, metritis, digestive disease, or pain, is detected
by this code. Literature on collar, neck, halter, or leg sensors is not
ear-tag validation. Even the cited ear-tag studies use different hardware and
algorithms and do not validate RIOSE.

## Synthetic software checks and offline use

Run `uv run --locked python -m riose.products.ear_tag.health_anomaly.demo` from
the repository root to print a deterministic simulated investigation result.
It requires no network, external dataset, or cloud service after dependencies
are installed and marks inputs/results as `SIMULATED`. Run focused tests with
`uv run --locked --extra dev python -m pytest tests/ear_tag/test_health_anomaly.py`.

Covered cases include stable baseline, abrupt decrease/increase, temporary
deviation and recovery, cold start, all-missing and partial observations,
sensor-position isolation, animal isolation, future-row leakage, invalid
scores, threshold boundary, evidence provenance, and synthetic preservation.
Rare-event and class-imbalance metrics are not estimable without independent
health labels. The demo has no health ground truth, so it reports no
performance metrics.

## Red Team review

| Adversarial case | Software behavior / evidence |
|---|---|
| Naturally low- or high-activity animal | Compared with its own baseline; covered by synthetic tests. |
| Abrupt drop or rise | Can yield `INVESTIGATE` plus a behavior code only; never a disease label. |
| Missing current data, packet loss, or sensor failure | All-missing observation or absent target yields `INSUFFICIENT_DATA`; no movement or health inference is made. |
| Another animal contributes baseline | Animal IDs are filtered before baseline selection; tested. |
| Different sensor location contributes baseline | Exact position match required; tested. |
| Future observation contributes to score | Rows after evaluation time are excluded; tested. |
| Treatment or diagnosis leaks into features | No clinical or treatment input exists in this API; ground truth is not used by the scoring path. |
| Rare classes or imbalance concealed by accuracy | No model or accuracy claim is emitted; metrics are explicitly not testable without independent health labels. |
| Simulated alert presented as field evidence | Synthetic input/output preserve `SIMULATED`; demo labels itself; tested. |
| Collar, neck, or leg evidence presented as ear-tag validation | Position is retained in results; docs explicitly reject transfer as validation. |
| Threshold optimized against holdout | No training or threshold tuning exists. Configurable cutoff is an unvalidated engineering parameter, not a tuned clinical operating point. |
| Environmental or reproductive change treated as disease | Context is not observed by this analyzer; output is only an investigation signal and cannot distinguish causes. |
| No alert taken as proof of health | Output wording explicitly says a negative deviation screen does not rule out disease. |
