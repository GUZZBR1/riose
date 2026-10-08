#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' 'INCOMPATIBLE: install uv 0.11.7 or newer, then rerun ./scripts/bootstrap.sh.' >&2
  exit 2
fi

uv sync --locked --extra dev --extra solana --extra evm
printf '%s\n' 'Bootstrap complete. Run ./scripts/doctor.sh, then the validation commands in reproducibility/README.md.'
