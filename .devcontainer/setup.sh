#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
core_dir="${HA_CORE_DIR:-"$repo_root/.ha-core"}"
core_ref="$(<"$repo_root/.devcontainer/ha-core.ref")"
ha_python="/home/vscode/.local/ha-venv/bin/python"

if [[ ! -d "$core_dir/.git" ]]; then
  git clone --depth 1 --single-branch --branch "$core_ref" \
    https://github.com/home-assistant/core.git "$core_dir"
fi

if [[ ! -x "$ha_python" ]]; then
  (
    cd "$core_dir"
    script/setup
  )
fi

"$ha_python" -m pip install --disable-pip-version-check \
  -r "$repo_root/requirements.test.txt" \
  mypy \
  ruff

mkdir -p "$core_dir/config/custom_components"
ln -sfn "$repo_root/custom_components/sems" \
  "$core_dir/config/custom_components/sems"

echo "SEMS is linked into $core_dir/config/custom_components/sems"
