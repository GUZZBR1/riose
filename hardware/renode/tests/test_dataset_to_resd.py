import importlib.util
import json
import struct
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "dataset_to_resd.py"
SPEC = importlib.util.spec_from_file_location("dataset_to_resd", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def _write_fake_csv2resd(converter):
    converter.parent.mkdir(parents=True, exist_ok=True)
    converter.write_text(
        "import csv, pathlib, struct, sys\n"
        "args=sys.argv[1:]\n"
        "source=pathlib.Path(args[args.index('--input')+1])\n"
        "rate=float(args[args.index('--frequency')+1])\n"
        "with source.open() as stream:\n"
        " rows=list(csv.reader(stream))\n"
        "samples=b''.join(struct.pack('<iii', *map(int,row)) for row in rows[1:])\n"
        "block=struct.pack('<BHHQ',2,2,0,24+len(samples))+struct.pack('<QQ',0,int(1e9/rate))+struct.pack('<Q',0)+samples\n"
        "pathlib.Path(args[-1]).write_bytes(b'RESD\\x01\\x00\\x00\\x00'+block)\n",
        encoding="utf-8",
    )


def test_conversion_maps_simulated_g_axes_to_renode_microg(tmp_path):
    from hardware.models.lis2dw12.generate_datasets import generate_datasets

    datasets = tmp_path / "datasets"
    generate_datasets(datasets, sample_rate_hz=12.5, samples=4, seed=3)
    renode = tmp_path / "renode"
    converter = renode / "tools" / "csv2resd" / "csv2resd.py"
    _write_fake_csv2resd(converter)
    output = tmp_path / "walk.resd"

    metadata = module.convert_dataset(datasets / "manifest.json", "STATIC", output, renode)

    data = output.read_bytes()
    _, _, _, block_size = struct.unpack_from("<BHHQ", data, 8)
    start_time, period = struct.unpack_from("<QQ", data, 21)
    first = struct.unpack_from("<iii", data, 45)
    assert block_size == len(data) - 21
    assert start_time == 0
    assert period == 80_000_000
    assert len(data[45:]) // 12 == 4
    assert abs(first[2] - 1_000_000) <= 2_000
    assert metadata["profile"] == "STATIC"
    assert metadata["seed"] == 3
    assert metadata["status"] == metadata["provenance"] == "SIMULATED"
    assert len(metadata["dataset_sha256"]) == len(metadata["resd_sha256"]) == 64
    assert len(metadata["profile_hash"]) == 64
    assert metadata["profile_id"].startswith("static-seed3-")
    assert json.loads(output.with_suffix(".resd.json").read_text())["profile_id"] == metadata["profile_id"]


def test_conversion_rejects_non_simulated_provenance(tmp_path):
    manifest = {"provenance": "MEASURED", "datasets": []}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="SIMULATED"):
        module.convert_dataset(path, "WALK", tmp_path / "out.resd", tmp_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda manifest: manifest["datasets"][0].update(axes=["x", "z", "y"]), "axes"),
        (lambda manifest: manifest["datasets"][0].update(unit="m/s2"), "g"),
        (lambda manifest: manifest["datasets"][0].update(sample_rate_hz=0), "sample_rate"),
        (lambda manifest: manifest["datasets"][0].update(duration_s=999), "duration"),
    ],
)
def test_conversion_rejects_invalid_dataset_contract(tmp_path, mutation, message):
    from hardware.models.lis2dw12.generate_datasets import generate_datasets

    datasets = tmp_path / "datasets"
    generate_datasets(datasets, sample_rate_hz=25, samples=4, seed=3)
    manifest_path = datasets / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    mutation(manifest)
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match=message):
        module.convert_dataset(manifest_path, "STATIC", tmp_path / "bad.resd", tmp_path)


def test_conversion_rejects_malformed_timestamps(tmp_path):
    from hardware.models.lis2dw12.generate_datasets import generate_datasets

    datasets = tmp_path / "datasets"
    generate_datasets(datasets, sample_rate_hz=25, samples=4, seed=3)
    source = datasets / "static.csv"
    source.write_text(source.read_text().replace("0.040000000", "0.041000000", 1))

    with pytest.raises(ValueError, match="timestamp_s"):
        module.convert_dataset(datasets / "manifest.json", "STATIC", tmp_path / "bad.resd", tmp_path)


def test_conversion_rejects_unsupported_profile(tmp_path):
    from hardware.models.lis2dw12.generate_datasets import generate_datasets

    datasets = tmp_path / "datasets"
    generate_datasets(datasets, samples=4, seed=3)
    with pytest.raises(ValueError, match="missing or ambiguous"):
        module.convert_dataset(datasets / "manifest.json", "GHOST", tmp_path / "bad.resd", tmp_path)


def test_conversion_rejects_missing_csv(tmp_path):
    from hardware.models.lis2dw12.generate_datasets import generate_datasets

    datasets = tmp_path / "datasets"
    generate_datasets(datasets, samples=4, seed=3)
    (datasets / "static.csv").unlink()
    with pytest.raises(FileNotFoundError):
        module.convert_dataset(datasets / "manifest.json", "STATIC", tmp_path / "missing.resd", tmp_path)


def test_conversion_rejects_wrong_axis_count(tmp_path):
    from hardware.models.lis2dw12.generate_datasets import generate_datasets

    datasets = tmp_path / "datasets"
    generate_datasets(datasets, samples=4, seed=3)
    source = datasets / "static.csv"
    source.write_text(source.read_text().replace("x_g,y_g,z_g", "x_g,y_g"))
    with pytest.raises(ValueError, match="unexpected CSV columns"):
        module.convert_dataset(datasets / "manifest.json", "STATIC", tmp_path / "bad.resd", tmp_path)


def test_conversion_rejects_empty_stream(tmp_path):
    from hardware.models.lis2dw12.generate_datasets import generate_datasets

    datasets = tmp_path / "datasets"
    manifest = generate_datasets(datasets, samples=4, seed=3)
    manifest["datasets"][0].update(samples=0, duration_s=0)
    (datasets / "manifest.json").write_text(json.dumps(manifest))
    (datasets / "static.csv").write_text("timestamp_s,x_g,y_g,z_g\n")
    with pytest.raises(ValueError, match="at least one acceleration sample"):
        module.convert_dataset(datasets / "manifest.json", "STATIC", tmp_path / "empty.resd", tmp_path)


def test_conversion_rejects_acceleration_outside_sensor_range(tmp_path):
    from hardware.models.lis2dw12.generate_datasets import generate_datasets

    datasets = tmp_path / "datasets"
    generate_datasets(datasets, samples=4, seed=3)
    source = datasets / "static.csv"
    rows = source.read_text().splitlines()
    fields = rows[1].split(",")
    fields[3] = "16.000001000"
    rows[1] = ",".join(fields)
    source.write_text("\n".join(rows) + "\n")
    renode = tmp_path / "renode"
    _write_fake_csv2resd(renode / "tools" / "csv2resd" / "csv2resd.py")
    with pytest.raises(ValueError, match="±16 g physical range"):
        module.convert_dataset(datasets / "manifest.json", "STATIC", tmp_path / "range.resd", renode)


def test_conversion_rejects_corrupted_renode_resd(tmp_path):
    from hardware.models.lis2dw12.generate_datasets import generate_datasets

    datasets = tmp_path / "datasets"
    generate_datasets(datasets, samples=4, seed=3)
    converter = tmp_path / "renode" / "tools" / "csv2resd" / "csv2resd.py"
    converter.parent.mkdir(parents=True, exist_ok=True)
    converter.write_text("import pathlib,sys\npathlib.Path(sys.argv[-1]).write_bytes(b'broken')\n")
    output = tmp_path / "corrupt.resd"
    with pytest.raises(ValueError, match="valid RESD v1"):
        module.convert_dataset(datasets / "manifest.json", "STATIC", output, tmp_path / "renode")
    assert not output.exists()
    assert not output.with_suffix(".resd.json").exists()


def test_failed_conversion_removes_stale_resd_and_metadata(tmp_path):
    from hardware.models.lis2dw12.generate_datasets import generate_datasets

    datasets = tmp_path / "datasets"
    generate_datasets(datasets, samples=4, seed=3)
    manifest_path = datasets / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["datasets"][0]["duration_s"] = 999
    manifest_path.write_text(json.dumps(manifest))
    output = tmp_path / "stale.resd"
    sidecar = tmp_path / "stale.resd.json"
    output.write_bytes(b"RESD old output")
    sidecar.write_text('{"profile":"old"}')

    with pytest.raises(ValueError, match="duration"):
        module.convert_dataset(manifest_path, "STATIC", output, tmp_path)

    assert not output.exists()
    assert not sidecar.exists()


def test_profile_identity_is_stable_for_same_seed_and_changes_for_new_seed(tmp_path):
    from hardware.models.lis2dw12.generate_datasets import generate_datasets

    datasets = tmp_path / "datasets"
    generate_datasets(datasets, samples=4, seed=11)
    renode = tmp_path / "renode"
    converter = renode / "tools" / "csv2resd" / "csv2resd.py"
    _write_fake_csv2resd(converter)
    first = module.convert_dataset(datasets / "manifest.json", "WALK", tmp_path / "first.resd", renode)
    same_seed = module.convert_dataset(datasets / "manifest.json", "WALK", tmp_path / "same.resd", renode)
    generate_datasets(datasets, samples=4, seed=12)
    other_seed = module.convert_dataset(datasets / "manifest.json", "WALK", tmp_path / "other.resd", renode)

    assert first["profile_hash"] == same_seed["profile_hash"]
    assert first["profile_id"] == same_seed["profile_id"]
    assert (tmp_path / "first.resd").read_bytes() == (tmp_path / "same.resd").read_bytes()
    assert first["profile_hash"] != other_seed["profile_hash"]
    assert first["profile_id"] != other_seed["profile_id"]
