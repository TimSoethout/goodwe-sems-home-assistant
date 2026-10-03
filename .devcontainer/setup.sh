#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
core_dir="${HA_CORE_DIR:-"$repo_root/.ha-core"}"
core_ref="$(sed -n 's/^homeassistant==\([^[:space:]#]*\).*$/\1/p' "$repo_root/requirements.test.txt")"
if [[ -z "$core_ref" ]]; then
  echo "No exact homeassistant version found in requirements.test.txt" >&2
  exit 1
fi
ha_python="$core_dir/.venv/bin/python"
config_dir="$core_dir/config"

if [[ ! -d "$core_dir/.git" ]]; then
  git clone --depth 1 --single-branch --branch "$core_ref" \
    https://github.com/home-assistant/core.git "$core_dir"
fi

if [[ -d "$core_dir/.venv" && ! -x "$ha_python" ]]; then
  stale_venv="$core_dir/.venv.incomplete.$(date +%s%N)"
  mv "$core_dir/.venv" "$stale_venv"
  echo "Preserved incomplete Home Assistant environment at $stale_venv" >&2
fi

if [[ ! -x "$ha_python" ]]; then
  (
    cd "$core_dir"
    script/setup
  )
else
  (
    cd "$core_dir"
    bash script/bootstrap
  )
fi

mkdir -p "$config_dir/custom_components"
"$core_dir/.venv/bin/hass" --script ensure_config -c "$config_dir"

configuration="$config_dir/configuration.yaml"
if ! grep -qE '^logger:[[:space:]]*(#.*)?$' "$configuration"; then
  cat >>"$configuration" <<'YAML'

logger:
  default: info
  logs:
    custom_components.sems: debug
YAML
elif grep -qE '^[[:space:]]+custom_components\.sems:' "$configuration"; then
  sed -i -E \
    's/^[[:space:]]*custom_components\.sems:.*/    custom_components.sems: debug/' \
    "$configuration"
elif grep -qE '^  logs:[[:space:]]*(#.*)?$' "$configuration"; then
  sed -i '/^  logs:/a\    custom_components.sems: debug' "$configuration"
else
  sed -i '/^logger:/a\  logs:\n    custom_components.sems: debug' "$configuration"
fi

ln -sfn "$repo_root/custom_components/sems" \
  "$config_dir/custom_components/sems"

hacs_dir="$config_dir/custom_components/hacs"
if [[ -d "$hacs_dir" ]]; then
  if [[ ! -f "$hacs_dir/manifest.json" ]]; then
    echo "HACS exists but is incomplete at $hacs_dir; refusing to replace it." >&2
    exit 1
  fi
else
  (
    cd "$config_dir"
    wget -O - https://get.hacs.xyz | bash
  )
fi

echo "SEMS is linked into $config_dir/custom_components/sems"
