#!/usr/bin/env bash
set -euo pipefail

summary_file="${GITHUB_STEP_SUMMARY:-/dev/null}"
mypy_output=$(mktemp)
passed=false
trap 'rm -f "$mypy_output"' EXIT
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ -n "${VIRTUAL_ENV:-}" && "${VIRTUAL_ENV}" != "$repo_root/.venv" && -x "${VIRTUAL_ENV}/bin/mypy" ]]; then
  mypy=("${VIRTUAL_ENV}/bin/mypy")
elif command -v uv >/dev/null 2>&1; then
  mypy=(uv run --no-project --python 3.14 --with-requirements "$repo_root/requirements.lint.txt" mypy)
elif [[ -x "$repo_root/.venv/bin/mypy" ]]; then
  mypy=("$repo_root/.venv/bin/mypy")
elif command -v mypy >/dev/null 2>&1; then
  mypy=("$(command -v mypy)")
else
  printf '%s\n' "mypy was not found; activate the test environment or install mypy." >&2
  exit 127
fi

if "${mypy[@]}" custom_components/ --strict --python-version 3.14 >"$mypy_output" 2>&1; then
  passed=true
  printf '## Home Assistant quality-scale checks\n\n- **Platinum: strict-typing:** PASS (`mypy --strict`).\n\n' >> "$summary_file"
else
  {
    printf '## Home Assistant quality-scale checks\n\n'
    printf '%s\n\n```text\n' '- **Platinum: strict-typing:** Issues found by `mypy --strict`.'
    sed -n '1,30p' "$mypy_output"
    printf '```\n\n'
  } >> "$summary_file"
  printf '%s\n' '::warning title=Platinum strict typing::mypy --strict reported issues; see the job summary.'
  if [[ "$summary_file" == /dev/null ]]; then
    cat "$mypy_output" >&2
  fi
fi

jq -n --argjson passed "$passed" '{available: true, passed: $passed}' > quality-scale-strict-typing.json

if [[ "$passed" != true ]]; then
  printf '%s\n' \
    "Home Assistant strict-typing check failed; see quality-scale-strict-typing.json." \
    >&2
  exit 1
fi

printf '%s\n' "Home Assistant strict-typing check passed."
