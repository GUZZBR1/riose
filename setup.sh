#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if command -v uv >/dev/null 2>&1; then
  uv sync --extra dev
else
  python3 -m venv .venv
  . .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -e '.[dev]'
fi
printf '%s\n' 'Setup concluído. Execute ./run_demo.sh para iniciar o demo local.'
