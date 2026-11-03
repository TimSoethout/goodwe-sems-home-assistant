#!/usr/bin/env bash
set -euo pipefail

summary_file="${GITHUB_STEP_SUMMARY:?}"
report_path=coverage.json
bronze_available=false
bronze_covered=0
bronze_total=0
silver_available=false
module_count=0
below_count=0

{
  printf '## Home Assistant quality-scale checks\n\n'
  if [[ ! -f "$report_path" ]]; then
    printf '%s\n' \
      '- **Bronze: config-flow-test-coverage:** Coverage report unavailable.' \
      '- **Silver: test-coverage:** Coverage report unavailable.'
  else
    config_stats=$(jq -r '
      [.files | to_entries[]
       | select(.key | startswith("custom_components/sems/") and endswith("config_flow.py"))
       | .value.summary]
      | first // empty
      | if . == null then empty else "\(.covered_lines)\t\(.num_statements)" end
    ' "$report_path")

    if [[ -z "$config_stats" ]]; then
      printf '%s\n' '- **Bronze: config-flow-test-coverage:** `config_flow.py` not found in coverage.'
    else
      bronze_available=true
      IFS=$'\t' read -r covered total <<< "$config_stats"
      bronze_covered=$covered
      bronze_total=$total
      if (( total > 0 )); then
        percent=$(awk -v covered="$covered" -v total="$total" 'BEGIN { printf "%.2f", covered * 100 / total }')
      else
        percent=0.00
      fi
      if (( total > 0 && covered == total )); then
        result=PASS
      else
        result='BELOW 100%'
        printf '::warning file=custom_components/sems/config_flow.py::Bronze config-flow line coverage is %s%%; 100%% is required.\n' "$percent"
      fi
      printf '%s\n' \
        "- **Bronze: config-flow-test-coverage (line coverage only):** ${result} (${covered}/${total}, ${percent}%). Flow scenarios still need review."
    fi

    module_rows=$(jq -r '
      .files | to_entries[]
      | select(.key | startswith("custom_components/sems/"))
      | [.key, .value.summary.percent_covered, .value.summary.num_statements]
      | @tsv
    ' "$report_path")
    if [[ -z "$module_rows" ]]; then
      printf '%s\n' '- **Silver: test-coverage:** No integration modules found in coverage.'
    else
      mapfile -t modules <<< "$module_rows"
      silver_available=true
      module_count=${#modules[@]}
      details=''
      for row in "${modules[@]}"; do
        IFS=$'\t' read -r path percent statements <<< "$row"
        if (( statements == 0 )) || awk -v percent="$percent" 'BEGIN { exit !(percent <= 95) }'; then
          below_count=$((below_count + 1))
          details+="${details:+, }\`${path}\` (${percent}%)"
          printf '::warning file=%s::Silver test coverage is %s%%; it must exceed 95%%.\n' "$path" "$percent"
        fi
      done
      if (( below_count > 0 )); then
        printf '%s\n' "- **Silver: test-coverage:** ${below_count} module(s) do not exceed 95%: ${details}."
      else
        printf '%s\n' "- **Silver: test-coverage:** PASS; all ${#modules[@]} integration modules exceed 95%."
      fi
    fi
  fi
  printf '\n%s\n\n' '- **Gold:** Requires human review; no automated tier verdict is claimed.'
} >> "$summary_file"

jq -n \
  --argjson bronze_available "$bronze_available" \
  --argjson bronze_covered "$bronze_covered" \
  --argjson bronze_total "$bronze_total" \
  --argjson silver_available "$silver_available" \
  --argjson module_count "$module_count" \
  --argjson below_count "$below_count" \
  '{
    bronze: {
      available: $bronze_available,
      covered: $bronze_covered,
      total: $bronze_total
    },
    silver: {
      available: $silver_available,
      modules: $module_count,
      below: $below_count
    }
  }' > quality-scale-coverage.json
