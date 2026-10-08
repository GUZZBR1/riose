# Reproducible local validation

This is the canonical route from a clean RIOSE checkout to the locked Python application, local EVM dependencies, and host firmware/model validation. It targets Ubuntu 24.04 or WSL Ubuntu 24.04. It does not require Docker, public RPC access, credentials, or physical hardware.

## Prerequisites

- Git and Python 3.12 (`.python-version`); the project accepts Python 3.12 and newer, while CI pins 3.12.
- uv 0.11.7 or newer. CI pins 0.11.7; `uv.lock` fixes Python package versions.
- Node.js 22.22.2 (`.nvmrc`) and npm 10.9.7 for the local EVM gate. `contracts/package-lock.json` fixes Ganache and solc dependencies.
- CMake 3.16 or newer and a C compiler for the host firmware/model gate.
- Hatchling 1.32.4 and its observed build toolchain are pinned in `build-constraints.txt`. `uv build --build-constraints` applies those constraints to PEP 517 isolation without mixing build tools into the application environment.
- Network access to Python and npm registries on the first uncached install. A successful install from an existing cache is a cached reproduction, not fresh-network reproduction.

## Clean checkout to local validation

```sh
git clone https://github.com/GUZZBR1/riose.git
cd riose
git status --short --branch
./scripts/bootstrap.sh
evidence_dir="$(mktemp -d "${TMPDIR:-/tmp}/riose-validation.XXXXXX")"
./scripts/doctor.sh --output "$evidence_dir/doctor_report.json"
npm ci --prefix contracts
uv run --locked pytest -q
node contracts/test/compile_registry.cjs contracts/src/RioseCommitmentRegistry.sol
build_dir="$(mktemp -d "${TMPDIR:-/tmp}/riose-cmake.XXXXXX")"
cmake -S hardware/tests -B "$build_dir"
cmake --build "$build_dir" --parallel
ctest --test-dir "$build_dir" --output-on-failure
uv run --locked --no-sync python -m compileall -q src scripts
uv run --locked --no-sync python scripts/integrated_smoke.py --output "$evidence_dir/integrated_smoke.json"
uv run --locked --no-sync python scripts/reproducibility.py manifest --output "$evidence_dir/environment_manifest.json"
mkdir -p "$evidence_dir/packages"
uv build --build-constraints build-constraints.txt --offline --out-dir "$evidence_dir/packages"
```

`setup.sh` remains a compatibility wrapper for the one canonical bootstrap. Bootstrap installs lockfile-resolved Python runtime/dev/Solana/EVM dependencies; `npm ci` installs the separate locked local EVM toolchain. The documented package build uses PEP 517 isolation with exact version constraints for Hatchling and its build toolchain. The doctor checks Python and npm lock consistency, import provenance, required files, local Ganache/solc versions when installed, and optional tool availability. It never probes a public chain or prints secret values.

Use a new empty cache directory to distinguish a fresh attempt from a cached one. For example, set `UV_CACHE_DIR` to an empty temporary directory and pass `--cache` to npm. If registry access is unavailable and a required artifact is absent, record `EXTERNAL_NETWORK_BLOCKER`; do not retry against a global cache and label it fresh.

## Optional capabilities and limits

| Capability | Classification | Local result boundary |
| --- | --- | --- |
| Python app, tests, SQLite persistence | Required for software validation | `uv.lock` and temp-database tests; no old database is required |
| Ganache and solc | Required for the local EVM gate | Local test chains only; no public transaction |
| CMake and host C compiler | Required for host firmware/model CTest | Simulated host build, not target firmware or device validation |
| Zephyr SDK, west, native_sim | Optional feature / specific firmware gate | Requires the separately pinned Zephyr toolchain in `hardware/toolchain.json` |
| Renode | Optional by design | Surrogate platform smoke only |
| CadQuery | Required for the CAD export gate only | Separate `requirements-cad.txt`; not part of the core app install |
| Gazebo / ROS | Optional integrated simulation capability | Requires the documented external ROS/Gazebo installation |
| ngspice, openEMS, CSXCAD | Optional engineering simulations | Pinned target versions are recorded in `hardware/toolchain.json`; availability is machine-specific |
| FREQUENCIA | External project | RIOSE keeps only an integration boundary; SC-3 does not run an RF campaign or vendor it |
| Docker | Optional by design | No container is needed for the documented route |

Simulation inputs with seeds can be semantically reproducible; random local subject references and timestamps mean all evidence is not bitwise reproducible. A local/mock receipt is not public-chain validation. See the JSON evidence in this directory for the specific run and limitations.
