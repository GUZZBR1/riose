#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
build_dir="${TMPDIR:-/tmp}/riose-mvp3-renode-build"
renode_conf="${TMPDIR:-/tmp}/riose-mvp3-renode.conf"

if [[ -n "${RIOSE_ZEPHYR_ELF:-}" && -f "$RIOSE_ZEPHYR_ELF" ]]; then
  printf '%s\n' "$RIOSE_ZEPHYR_ELF"
  exit 0
fi

# Renode uses an STM32L071 surrogate without the physical board's RTC/STOP
# behavior. Disable PM and keep enough stack/heap for the app. Keep generated
# configuration/build output in /tmp.
if [[ -z "${ZEPHYR_BASE:-}" ]]; then
  zephyr_setup="${RIOSE_ZEPHYR_SETUP:-$HOME/.local/opt/riose-zephyr-env.sh}"
  if [[ -f "$zephyr_setup" ]]; then
    # Zephyr alone is sufficient; do not require unrelated CAD/EM dependencies.
    # shellcheck disable=SC1090
    source "$zephyr_setup"
  else
    # Legacy setup remains a fallback for workspaces without the focused setup.
    # shellcheck disable=SC1091
    source "$repo_root/hardware/activate-mvp2-toolchain.sh"
  fi
fi
if ! command -v west >/dev/null 2>&1; then
  echo "west is required to build the Renode firmware image." >&2
  exit 2
fi
cat >"$renode_conf" <<'EOF'
CONFIG_MAIN_STACK_SIZE=2048
CONFIG_HEAP_MEM_POOL_SIZE=1024
CONFIG_PM=n
EOF
west build -b nucleo_l031k6 -d "$build_dir" "$repo_root/hardware/firmware/zephyr" \
  -- -DEXTRA_CONF_FILE="$renode_conf" >&2
elf="$build_dir/zephyr/zephyr.elf"
[[ -f "$elf" ]] || { echo "Zephyr build completed without ELF: $elf" >&2; exit 2; }
printf '%s\n' "$elf"
