from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from riose.evidence.bridge import EvidenceClass, parse_evidence_bridge
from riose.products.ear_tag.movement_datasets import SensorPosition, adapt_actbecalf_csv
from riose.products.ear_tag.movement_datasets import acquisition
from riose.products.ear_tag.movement_datasets import actbecalf
from riose.products.ear_tag.movement_datasets import __main__ as dataset_cli
from riose.products.ear_tag.movement_datasets.__main__ import main

ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "datasets/movement_biosignature/fixtures/actbecalf_synthetic_fixture.csv"


def _adapt(path: Path = FIXTURE):
    return list(adapt_actbecalf_csv(path, evidence_class=EvidenceClass.SIMULATED))


def _csv(path: Path, *, header: str | None = None, row: str | None = None) -> Path:
    path.write_text(
        (header or "dateTime,calfId,accX,accY,accZ,behaviour,segId") + "\n"
        + (row or "2024-01-01T12:00:00.040,1306,0.1,0.2,0.3,standing,17") + "\n",
        encoding="utf-8",
    )
    return path


def test_fixture_hash_adapter_schema_labels_and_determinism():
    original = FIXTURE.read_bytes()
    expected_sha256 = "11698c1c9936643a00950f94ff1d4c0a9023a404dd058eb8b939210d40ea5e7b"
    assert hashlib.sha256(original).hexdigest() == expected_sha256
    first = _adapt()
    second = _adapt()

    assert len(first) == 3
    assert [sample.to_json() for sample in first] == [sample.to_json() for sample in second]
    assert all(sample.dataset_doi == "10.5281/zenodo.13259482" for sample in first)
    assert all(sample.sensor_position is SensorPosition.NECK for sample in first)
    assert all(sample.sample_rate_hz == 25.0 for sample in first)
    assert all(sample.axis_unit.value == "UNKNOWN" for sample in first)
    assert [sample.original_label for sample in first] == [
        "standing", "oral_manipulation_of_pen", "unseen_behavior"
    ]
    assert all(sample.canonical_label == "UNKNOWN" for sample in first)
    assert all(sample.session_id is None for sample in first)
    assert [sample.source_segment_id for sample in first] == ["segment-1", "segment-1", "segment-2"]
    assert all(sample.evidence_status is EvidenceClass.SIMULATED for sample in first)
    assert all(sample.source_file_sha256 == expected_sha256 for sample in first)
    assert first[0].timestamp_timezone == "UNKNOWN"
    assert FIXTURE.read_bytes() == original


def test_unverified_source_is_unknown_not_promoted_or_mislabeled_as_simulated(tmp_path):
    source = _csv(tmp_path / "unverified.csv")
    [sample] = list(adapt_actbecalf_csv(source, evidence_class=EvidenceClass.UNKNOWN))
    assert sample.evidence_status is EvidenceClass.UNKNOWN


def test_adapter_parses_the_hashed_snapshot_if_raw_path_changes(tmp_path, monkeypatch):
    source = tmp_path / "mutable.csv"
    source.write_text(
        "dateTime,calfId,accX,accY,accZ,behaviour,segId\n"
        "2024-01-01T12:00:00.040,1306,0.1,0.2,0.3,first,17\n"
        "2024-01-01T12:00:00.080,1306,0.4,0.5,0.6,second,18\n",
        encoding="utf-8",
    )
    initial_bytes = source.read_bytes()
    original_open = Path.open

    def replace_before_text_reopen(path, mode="r", *args, **kwargs):
        if path == source and mode == "r":
            source.write_text(
                "dateTime,calfId,accX,accY,accZ,behaviour,segId\n"
                "2024-01-01T12:00:00.040,1306,9,9,9,replaced,99\n"
                "2024-01-01T12:00:00.080,1306,8,8,8,replaced,99\n",
                encoding="utf-8",
            )
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", replace_before_text_reopen)
    samples = list(adapt_actbecalf_csv(source, evidence_class=EvidenceClass.UNKNOWN))
    assert [sample.x for sample in samples] == [0.1, 0.4]
    assert [sample.original_label for sample in samples] == ["first", "second"]
    assert all(sample.source_file_sha256 == hashlib.sha256(initial_bytes).hexdigest()
               for sample in samples)
    assert source.read_text(encoding="utf-8").count("replaced") == 2


def test_external_measurement_uses_shared_evidence_bridge_and_is_not_ear_validation(tmp_path, monkeypatch):
    source = _csv(tmp_path / "sample.csv")
    content = source.read_bytes()
    monkeypatch.setattr(actbecalf, "ACTBECALF_PUBLISHER_MD5", hashlib.md5(content).hexdigest())
    monkeypatch.setattr(actbecalf, "ACTBECALF_PUBLISHER_SIZE", len(content))
    [sample] = list(adapt_actbecalf_csv(source, evidence_class=EvidenceClass.MEASURED))

    assert sample.evidence_status is EvidenceClass.MEASURED
    serialized = sample.to_dict()["evidence"]
    parsed = parse_evidence_bridge(json.dumps(serialized, sort_keys=True, separators=(",", ":")))
    assert parsed.evidence_class is EvidenceClass.MEASURED
    assert parsed.measurement_provenance.capture_ref == "sample.csv#row=2"
    assert parsed.source_context["sensor_position"] == "NECK"
    assert sample.sensor_position is not SensorPosition.EAR


def test_unverified_csv_cannot_be_asserted_as_measured(tmp_path):
    source = _csv(tmp_path / "synthetic.csv")
    with pytest.raises(ValueError, match="official publisher checksum and size"):
        list(adapt_actbecalf_csv(source, evidence_class=EvidenceClass.MEASURED))


@pytest.mark.parametrize("row, message", [
    ("2024-01-01T12:00:00.040,1306,,0.2,0.3,standing,17", "numeric"),
    ("2024-01-01T12:00:00.040,1306,nan,0.2,0.3,standing,17", "finite"),
    (",1306,0.1,0.2,0.3,standing,17", "dateTime"),
    ("not-a-time,1306,0.1,0.2,0.3,standing,17", "invalid ActBeCalf dateTime"),
    ("2024-01-01,1306,0.1,0.2,0.3,standing,17", "invalid ActBeCalf dateTime"),
    ("2024-01-01T12:00:00.040,,0.1,0.2,0.3,standing,17", "calfId"),
    ("2024-01-01T12:00:00.040,1306,0.1,0.2,0.3,,17", "behaviour"),
    ("2024-01-01T12:00:00.040,1306,0.1,0.2,0.3,standing,", "segId"),
])
def test_invalid_rows_fail_closed(tmp_path, row, message):
    source = _csv(tmp_path / "bad.csv", row=row)
    with pytest.raises(ValueError, match=message):
        list(adapt_actbecalf_csv(source, evidence_class=EvidenceClass.SIMULATED))


def test_unknown_or_swapped_xyz_header_is_rejected(tmp_path):
    source = _csv(tmp_path / "swapped.csv",
                  header="dateTime,calfId,accY,accX,accZ,behaviour,segId")
    with pytest.raises(ValueError, match="header"):
        list(adapt_actbecalf_csv(source, evidence_class=EvidenceClass.SIMULATED))


def test_extra_or_missing_csv_fields_are_rejected(tmp_path):
    source = _csv(tmp_path / "extra.csv", row="2024-01-01T12:00:00.040,1306,0.1,0.2,0.3,standing,17,extra")
    with pytest.raises(ValueError, match="malformed"):
        list(adapt_actbecalf_csv(source, evidence_class=EvidenceClass.SIMULATED))
    source = _csv(tmp_path / "missing.csv", row="2024-01-01T12:00:00.040,1306,0.1,0.2,0.3,standing")
    with pytest.raises(ValueError, match="malformed"):
        list(adapt_actbecalf_csv(source, evidence_class=EvidenceClass.SIMULATED))


def test_malformed_quoting_and_encoding_fail_closed(tmp_path):
    source = tmp_path / "quotes.csv"
    source.write_text(
        "dateTime,calfId,accX,accY,accZ,behaviour,segId\n"
        '"2024-01-01T12:00:00.040,1306,0.1,0.2,0.3,standing,17\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="malformed ActBeCalf CSV"):
        list(adapt_actbecalf_csv(source, evidence_class=EvidenceClass.SIMULATED))
    source.write_bytes(b"dateTime,calfId,accX,accY,accZ,behaviour,segId\n\xff")
    with pytest.raises(UnicodeDecodeError):
        list(adapt_actbecalf_csv(source, evidence_class=EvidenceClass.SIMULATED))


def test_timezone_and_out_of_order_rows_are_preserved_without_sorting(tmp_path):
    source = tmp_path / "ordering.csv"
    source.write_text(
        "dateTime,calfId,accX,accY,accZ,behaviour,segId\n"
        "2024-01-01T12:00:01+02:00,1306,1,2,3,standing,17\n"
        "2024-01-01T12:00:00+02:00,1306,4,5,6,standing,17\n",
        encoding="utf-8",
    )
    samples = list(adapt_actbecalf_csv(source, evidence_class=EvidenceClass.SIMULATED))
    assert [sample.timestamp for sample in samples] == [
        "2024-01-01T12:00:01+02:00", "2024-01-01T12:00:00+02:00"
    ]
    assert [sample.source_row for sample in samples] == [2, 3]
    assert all(sample.timestamp_timezone == "OFFSET" for sample in samples)


def test_physical_lines_source_segment_and_original_strings_are_preserved(tmp_path):
    source = tmp_path / "physical-lines.csv"
    source.write_text(
        "dateTime,calfId,accX,accY,accZ,behaviour,segId\n"
        '" 2024-01-01T12:00:00+00:00 ",1306,1,2,3," standing ", segment-a \n'
        "\n"
        "2024-01-01T12:00:01+00:00,1306,4,5,6,walking,segment-b\n",
        encoding="utf-8",
    )
    samples = list(adapt_actbecalf_csv(source, evidence_class=EvidenceClass.SIMULATED))
    assert [sample.source_row for sample in samples] == [2, 4]
    assert samples[0].original_label == " standing "
    assert samples[0].timestamp == " 2024-01-01T12:00:00+00:00 "
    assert samples[0].source_segment_id == " segment-a "


def test_contract_rejects_invalid_units_types_rates_and_timezone():
    [sample] = _adapt()[:1]
    with pytest.raises(ValueError, match="sample_rate_hz"):
        replace(sample, sample_rate_hz=0)
    with pytest.raises(ValueError, match="sample_rate_hz"):
        replace(sample, sample_rate_hz="25")
    with pytest.raises(ValueError, match="sample_rate_hz"):
        replace(sample, sample_rate_hz=float("nan"))
    with pytest.raises(ValueError, match="sample_rate_hz"):
        replace(sample, sample_rate_hz=None)
    with pytest.raises(ValueError, match="axis unit"):
        replace(sample, axis_unit="g")
    with pytest.raises(ValueError, match="dataset_doi"):
        replace(sample, dataset_doi="")
    with pytest.raises(ValueError, match="source_url"):
        replace(sample, source_url="")
    with pytest.raises(ValueError, match="timestamp_timezone"):
        replace(sample, timestamp_timezone="UTC")
    with pytest.raises(ValueError, match="cannot contain control"):
        replace(sample, animal_id="animal\nprivate")
    with pytest.raises(ValueError, match="cannot contain control"):
        replace(sample, source_segment_id="segment\n17")


def test_missing_source_and_unacceptable_evidence_fail_explicitly(tmp_path):
    with pytest.raises(FileNotFoundError):
        list(adapt_actbecalf_csv(tmp_path / "missing.csv", evidence_class=EvidenceClass.SIMULATED))
    with pytest.raises(ValueError, match="SIMULATED, MEASURED, or UNKNOWN"):
        list(adapt_actbecalf_csv(FIXTURE, evidence_class=EvidenceClass.DECLARED))


def test_cli_conversion_writes_separate_simulated_output_manifest_and_refuses_overwrite(tmp_path, capsys):
    raw = tmp_path / "raw.csv"
    raw.write_bytes(FIXTURE.read_bytes())
    raw_before = raw.read_bytes()
    output = tmp_path / "processed.jsonl"
    assert main(["convert-actbecalf", str(raw), str(output), "--simulated"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["sample_count"] == 3
    assert raw.read_bytes() == raw_before
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    manifest = json.loads(Path(str(output) + ".manifest.json").read_text(encoding="utf-8"))
    assert all(record["evidence_status"] == "SIMULATED" for record in records)
    assert manifest["source_sha256"] == hashlib.sha256(raw_before).hexdigest()
    assert manifest["adapter_version"] == "1.0.0"
    assert manifest["sample_count"] == 3
    with pytest.raises(SystemExit):
        main(["convert-actbecalf", str(raw), str(output), "--simulated"])
    with pytest.raises(SystemExit):
        main(["convert-actbecalf", str(raw), str(raw)])


def test_measured_cli_rejects_non_publisher_file(tmp_path):
    output = tmp_path / "derived.jsonl"
    with pytest.raises(SystemExit):
        main(["convert-actbecalf", str(FIXTURE), str(output), "--measured"])
    assert not output.exists()
    assert not Path(str(output) + ".manifest.json").exists()


def test_cli_defaults_unverified_source_to_unknown(tmp_path, capsys):
    output = tmp_path / "unverified.jsonl"
    assert main(["convert-actbecalf", str(FIXTURE), str(output)]) == 0
    capsys.readouterr()
    assert all(json.loads(line)["evidence_status"] == "UNKNOWN"
               for line in output.read_text(encoding="utf-8").splitlines())


def test_cli_rejects_source_aba_change_even_if_raw_is_restored(tmp_path, monkeypatch):
    source = tmp_path / "raw.csv"
    _csv(source, row="2024-01-01T12:00:00.040,1306,1,2,3,standing,17")
    original = source.read_bytes()
    output = tmp_path / "derived.jsonl"
    adapter = dataset_cli.adapt_actbecalf_csv

    def mutate_during_adaptation(path, *, evidence_class):
        _csv(source, row="2024-01-01T12:00:00.040,1306,9,8,7,changed,99")
        try:
            yield from adapter(path, evidence_class=evidence_class)
        finally:
            source.write_bytes(original)

    monkeypatch.setattr(dataset_cli, "adapt_actbecalf_csv", mutate_during_adaptation)
    with pytest.raises(ValueError, match="adapter snapshot checksum differs"):
        main(["convert-actbecalf", str(source), str(output)])
    assert source.read_bytes() == original
    assert not output.exists()
    assert not Path(str(output) + ".manifest.json").exists()
    assert not list(tmp_path.glob(".derived.jsonl.*"))


def test_cli_golden_fixture_jsonl_and_conversion_manifest(tmp_path, capsys):
    output = tmp_path / "actbecalf_synthetic_fixture.jsonl"
    assert main(["convert-actbecalf", str(FIXTURE), str(output), "--simulated"]) == 0
    capsys.readouterr()
    golden_root = FIXTURE.parent
    assert output.read_bytes() == (golden_root / output.name).read_bytes()
    manifest = Path(str(output) + ".manifest.json")
    assert manifest.read_bytes() == (golden_root / (output.name + ".manifest.json")).read_bytes()
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == \
        "4a7b6f5c973ae657f91d52bb098159c06cd58a04176d632a29250c8d648db4e1"
    manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_value["canonical_unknown_count"] == 3
    assert manifest_value["canonical_unknown_original_label_examples"] == [
        "standing", "oral_manipulation_of_pen", "unseen_behavior"
    ]
    assert manifest_value["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert manifest_value["output_sha256"] == "a330c13d82f366fb0a4b12d094f9d61a0d5b188d1e5701361f733bdf9fe82910"


def test_catalog_records_license_conflict_and_source_restrictions(tmp_path, monkeypatch):
    catalog = json.loads((ROOT / "datasets/movement_biosignature/catalog.json").read_text(encoding="utf-8"))
    sources = {source["id"]: source for source in catalog["datasets"]}
    assert sources["actbecalf"]["automated_download"] is True
    assert sources["actbecalf"]["publisher_license"] == "CC BY 4.0"
    assert sources["precision-beef"]["automated_download"] is False
    japanese = sources["japanese-black-beef-cow-v2"]
    assert japanese["publisher_license"] == "CONFLICTED"
    assert japanese["automated_download"] is False
    assert {entry["license"] for entry in japanese["license_declarations"]} == {
        "CC BY-NC-ND 4.0", "CC BY 4.0"
    }
    for dataset_id in ("japanese-black-beef-cow-v2", "precision-beef", "unknown-copy"):
        monkeypatch.setattr(acquisition, "download_actbecalf",
                            lambda *_args, **_kwargs: pytest.fail("restricted dataset must never be downloaded"))
        destination = tmp_path / f"{dataset_id}.csv"
        with pytest.raises(ValueError, match="automated acquisition is not enabled"):
            acquisition.download_dataset(dataset_id, destination)
        assert not destination.exists()


class _Response:
    def __init__(self, data: bytes):
        self._stream = __import__("io").BytesIO(data)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self._stream.close()

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def test_download_checksum_failure_preserves_destination_and_cleans_temp(tmp_path, monkeypatch):
    content = b"known publisher file"
    target = tmp_path / "raw.csv"
    monkeypatch.setattr(acquisition, "ACTBECALF_PUBLISHER_MD5", hashlib.md5(content).hexdigest())
    monkeypatch.setattr(acquisition, "ACTBECALF_PUBLISHER_SIZE", len(content))
    result = acquisition.download_actbecalf(target, opener=lambda *_args, **_kwargs: _Response(content))
    assert result["status"] == "DOWNLOADED"
    assert target.read_bytes() == content
    assert acquisition.download_actbecalf(target, opener=lambda *_args, **_kwargs: pytest.fail("must not redownload"))["status"] == "ALREADY_PRESENT"
    assert list(tmp_path.iterdir()) == [target]

    monkeypatch.setattr(acquisition, "ACTBECALF_PUBLISHER_MD5", "0" * 32)
    other = tmp_path / "changed.csv"
    with pytest.raises(ValueError, match="checksum"):
        acquisition.download_actbecalf(other, opener=lambda *_args, **_kwargs: _Response(content))
    assert not other.exists()
    assert list(tmp_path.iterdir()) == [target]


def test_download_refuses_to_replace_unknown_existing_file(tmp_path, monkeypatch):
    target = tmp_path / "raw.csv"
    target.write_text("unverified data", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        acquisition.download_actbecalf(target, opener=lambda *_args, **_kwargs: pytest.fail("must not download"))
    assert target.read_text(encoding="utf-8") == "unverified data"
