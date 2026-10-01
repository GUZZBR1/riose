#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if command -v uv >/dev/null 2>&1; then
  exec uv run cattle-rf demo --host 127.0.0.1 --port 8000
fi
. .venv/bin/activate
exec cattle-rf demo --host 127.0.0.1 --port 8000
