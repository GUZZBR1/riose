#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' 'INCOMPATIBLE: uv is required; install uv 0.11.7 or newer.' >&2
  exit 2
fi

exec uv run --locked --no-sync python scripts/reproducibility.py doctor "$@"
