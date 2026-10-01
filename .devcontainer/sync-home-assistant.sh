#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
core_dir="${HA_CORE_DIR:-"$repo_root/.ha-core"}"
version="$(sed -n 's/^homeassistant==\([^[:space:]#]*\).*$/\1/p' "$repo_root/requirements.test.txt")"

if [[ -z "$version" ]]; then
  echo "No exact homeassistant version found in requirements.test.txt" >&2
  exit 1
fi

if [[ ! -d "$core_dir/.git" ]]; then
  echo "Home Assistant Core checkout not found at $core_dir" >&2
  echo "Run .devcontainer/setup.sh first." >&2
  exit 1
fi

git -C "$core_dir" fetch --tags origin
git -C "$core_dir" checkout --detach "$version"
rm -rf "$core_dir/.venv"
bash "$repo_root/.devcontainer/setup.sh"
