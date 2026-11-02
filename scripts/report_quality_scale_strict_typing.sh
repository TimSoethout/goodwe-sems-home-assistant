#!/usr/bin/env bash
set -euo pipefail

summary_file="${GITHUB_STEP_SUMMARY:?}"
mypy_output=$(mktemp)
passed=false
trap 'rm -f "$mypy_output"' EXIT

if mypy custom_components/ --strict --ignore-missing-imports --python-version 3.14 >"$mypy_output" 2>&1; then
  passed=true
  printf '## Home Assistant quality-scale advisory checks\n\n- **Platinum: strict-typing:** PASS (`mypy --strict`).\n\n' >> "$summary_file"
else
  {
    printf '## Home Assistant quality-scale advisory checks\n\n'
    printf '%s\n\n```text\n' '- **Platinum: strict-typing:** Issues found by the advisory `mypy --strict` probe.'
    sed -n '1,30p' "$mypy_output"
    printf '```\n\n'
  } >> "$summary_file"
  printf '%s\n' '::warning title=Platinum strict typing::mypy --strict reported issues; see the job summary.'
fi

jq -n --argjson passed "$passed" '{available: true, passed: $passed}' > quality-scale-strict-typing.json
