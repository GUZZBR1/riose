# Movement BioSignature dataset foundation

This mini-MVP catalogs bovine accelerometer sources and adapts ActBeCalf CSV
rows to a small JSON Lines contract. It runs independently of the Signal Engine
and behavior classifier. The checked-in adapter fixture is fabricated for
software testing and always remains `SIMULATED`; it contains no animal data.

## Source catalog

`datasets/movement_biosignature/catalog.json` records publisher references,
DOIs, access and license statements, available metadata, uncertainty, and
limitations. `VERIFIED_PRIMARY_SOURCE` means the source record/API or
publisher documentation was inspected. Unknown values are retained as
`UNKNOWN`; catalog metadata is not a claim of ear-tag performance.

| Source | Position / rate / unit | Access and license | Adapter status |
| --- | --- | --- | --- |
| [ActBeCalf](https://zenodo.org/records/13259482), DOI `10.5281/zenodo.13259482` | Neck AX3 / 25 Hz / CSV unit unknown | Open, CC BY 4.0 | Executable adapter and explicit checksum-verified download |
| [Precision Beef](https://zenodo.org/records/4064802), DOI `10.5281/zenodo.4064802` | Collar accelerometer / 10 Hz / mg; halter provides predicted labels | Open, CC BY 4.0 | Catalog only. Label timestamps do not exactly match signal timestamps; label 2 combines eating and drinking. |
| [Japanese Black Beef Cow v2](https://zenodo.org/records/5849025), DOI `10.5281/zenodo.5849025` | Neck / 25 Hz / g | Zenodo description states CC BY-NC-ND 4.0; Zenodo API says CC BY 4.0 | Acquisition disabled because the publisher license statements conflict. |

The ActBeCalf paper reports a 30-calf population and an AX3 at the left neck.
Its official CSV uses `dateTime,calfId,accX,accY,accZ,behaviour,segId`; the
publisher description uses different capitalization. The adapter accepts the
observed CSV header exactly and refuses to infer reordered or missing axes.
The CSV acceleration unit and timestamp timezone are not documented, so the
adapter preserves numeric axes without conversion and retains the source
timestamp exactly. `segId` is a behavior segment, not a verified recording
session. Source labels are retained; canonical behavior stays `UNKNOWN`.

The Japanese dataset is not downloaded because conflicting license metadata
cannot establish what adaptation or redistribution the publisher permits.
Precision Beef's class 2 is `Eating or Drinking`, and labels are predictions
from a second device; the catalog does not simplify that to `EAT`.

## Canonical record and provenance

`CanonicalSample` requires source DOI/reference and file SHA-256, row number,
animal ID, timestamp/timezone status, sensor position, source sample rate,
raw XYZ and unit, original and canonical labels, adapter version, and a shared
`riose.evidence.bridge.EvidenceBridgeRecord`. It never rescales axes or maps
behavior classes. ActBeCalf reports `NECK`, not `EAR`.

For externally sourced measurements, the explicit `MEASURED` conversion
creates a bridge record with the source dataset, source file row, and DOI as
provenance references. The adapter only permits that status when the complete
source file matches the official publisher's MD5 and byte count. This means the external dataset reports a physical
capture; it does not validate RIOSE hardware or transfer performance to an
ear-tag. Unverified source files default to `UNKNOWN`; fixtures need the
explicit `--simulated` flag. Callers using the Python adapter must choose
`evidence_class` explicitly.

Raw files are opened read-only and copied to a temporary snapshot before
parsing, so the digest identifies the bytes actually adapted. The CLI checks
the adapter's per-row snapshot digest against the source digest before publish
to detect input replacement, including replacement-and-restore races. Conversion
writes a separate JSONL artifact and a manifest containing source and output
checksums, adapter version, evidence status, sample count, and examples of
original labels retained as `UNKNOWN`. Existing outputs are never overwritten.
`source_row` is the physical line where the CSV record ends (including when
blank lines or multiline records occur). The source's `segId` is retained as
`source_segment_id`; it is never repurposed as a collection session ID.

## Commands

The test suite is offline. A real file is optional and is never downloaded on
import or during tests.

```sh
python -m pip install -e .
riose-movement-dataset catalog
riose-movement-dataset fetch-actbecalf data/AcTBeCalf.csv
riose-movement-dataset convert-actbecalf data/AcTBeCalf.csv results/actbecalf.jsonl --measured
```

`fetch-actbecalf` uses the official Zenodo API content endpoint, writes only
when the publisher's MD5 matches, and is idempotent when the existing file
matches. A changed publisher file is rejected. The source record's license
permits adaptation and redistribution with attribution, license link, and
change indication. The large real dataset is not included in Git.

Without either evidence flag, conversion is labeled `UNKNOWN`. `--simulated`
is for synthetic/test content. `--measured` requires the full file's official
publisher checksum and published byte size; it does not promote any hardware
evidence.

## Fixture and checksums

`datasets/movement_biosignature/fixtures/actbecalf_synthetic_fixture.csv` is a
three-row synthetic fixture. It is not copied from or representative of
observed animals. The test suite checks its SHA-256, adapter output and
determinism. Its SHA-256 is
`11698c1c9936643a00950f94ff1d4c0a9023a404dd058eb8b939210d40ea5e7b`.
Actual converted files also record a SHA-256 digest and source
row for every sample. Zenodo reports MD5 `59bd00564af64d92489485fa5a8a3960`
for the complete ActBeCalf file (177,608,717 bytes); that publisher checksum
was recorded from the official metadata and was not independently recomputed
because the full dataset was not downloaded for this implementation.

## Limitations

No public source inspected here validates the RIOSE ear-tag. The adapter does
not infer timezone, session boundaries, axis units, or behavior equivalence.
The dataset catalog is a documented snapshot; source metadata and URLs can
change. Downloads fail closed on checksum mismatch. Japanese dataset
acquisition remains disabled until its license conflict is resolved.
