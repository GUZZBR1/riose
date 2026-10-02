#!/usr/bin/env bash
# Source this in WSL to activate the user-local MVP2 toolchain environment.
# This does not install packages or modify the system Python.

RIOSE_ZEPHYR_SETUP="${RIOSE_ZEPHYR_SETUP:-$HOME/.local/opt/riose-zephyr-env.sh}"
RIOSE_MVP2_PYTHON_ENV="${RIOSE_MVP2_PYTHON_ENV:-$HOME/.local/opt/riose-mvp2-venv}"
RIOSE_MVP2_CAD_ENV="${RIOSE_MVP2_CAD_ENV:-$HOME/.local/share/mamba/envs/riose-mvp2-cad}"
RIOSE_MVP2_OPENEMS_PREFIX="${RIOSE_MVP2_OPENEMS_PREFIX:-$HOME/.local/opt/openEMS-0.37.0-rc3}"
RIOSE_MVP2_ZEPHYR_WORKSPACE="${RIOSE_MVP2_ZEPHYR_WORKSPACE:-$HOME/zephyrproject}"

for required in \
  "$RIOSE_ZEPHYR_SETUP" \
  "$RIOSE_MVP2_PYTHON_ENV/bin/activate" \
  "$RIOSE_MVP2_CAD_ENV/lib" \
  "$RIOSE_MVP2_OPENEMS_PREFIX/bin/openEMS" \
  "$RIOSE_MVP2_ZEPHYR_WORKSPACE/.venv/bin/west"; do
  if [[ ! -e "$required" ]]; then
    echo "MVP2 toolchain component is missing: $required" >&2
    return 1 2>/dev/null || exit 1
  fi
done

# The Zephyr helper sets ZEPHYR_BASE, SDK path and compiler tools.
source "$RIOSE_ZEPHYR_SETUP"
source "$RIOSE_MVP2_PYTHON_ENV/bin/activate"

export OPENEMS_INSTALL_PATH="$RIOSE_MVP2_OPENEMS_PREFIX"
export CSXCAD_INSTALL_PATH="$RIOSE_MVP2_OPENEMS_PREFIX"
export LD_LIBRARY_PATH="$RIOSE_MVP2_OPENEMS_PREFIX/lib:$RIOSE_MVP2_CAD_ENV/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="$RIOSE_MVP2_PYTHON_ENV/bin:$RIOSE_MVP2_OPENEMS_PREFIX/bin:$RIOSE_MVP2_ZEPHYR_WORKSPACE/.venv/bin:$HOME/.local/opt/zephyr-sdk-0.16.8/sysroots/x86_64-pokysdk-linux/usr/bin:$HOME/.local/bin:$PATH"
