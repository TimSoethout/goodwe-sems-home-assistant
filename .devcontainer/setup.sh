#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
core_dir="${HA_CORE_DIR:-"$repo_root/.ha-core"}"
core_ref="$(python3 "$repo_root/scripts/homeassistant_version.py")"
if [[ -z "$core_ref" ]]; then
  echo "No Home Assistant version found in hacs.json" >&2
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

go2rtc_const="$core_dir/homeassistant/components/go2rtc/const.py"
go2rtc_version="$(
  sed -n 's/^RECOMMENDED_VERSION = "\([^"]*\)".*/\1/p' "$go2rtc_const" | head -n 1
)"
if [[ -z "$go2rtc_version" ]]; then
  echo "Could not determine the go2rtc version from Home Assistant Core" >&2
  exit 1
fi
case "$(dpkg --print-architecture)" in
  amd64) go2rtc_arch=amd64 ;;
  arm64) go2rtc_arch=arm64 ;;
  *)
    echo "Unsupported architecture: $(dpkg --print-architecture)" >&2
    exit 1
    ;;
esac
if ! [[ -x /usr/local/bin/go2rtc ]] ||
  [[ "$(/usr/local/bin/go2rtc --version 2>&1 || true)" != *"$go2rtc_version"* ]]; then
  wget -q -O /usr/local/bin/go2rtc \
    "https://github.com/AlexxIT/go2rtc/releases/download/v${go2rtc_version}/go2rtc_linux_${go2rtc_arch}"
  chmod 0755 /usr/local/bin/go2rtc
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

# Home Assistant 2026.11+ provides HACS through the built-in Marketplace.

echo "SEMS is linked into $config_dir/custom_components/sems"
echo "HA-MCP will be installed through the built-in Marketplace"
