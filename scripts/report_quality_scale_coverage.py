import json
import os
from pathlib import Path

summary = ["## Home Assistant quality-scale advisory checks", ""]
report_path = Path("coverage.json")
if not report_path.exists():
    summary.extend(
        [
            "- **Bronze: config-flow-test-coverage:** Coverage report unavailable.",
            "- **Silver: test-coverage:** Coverage report unavailable.",
        ]
    )
else:
    files = json.loads(report_path.read_text())["files"]
    modules = {
        path: data["summary"]
        for path, data in files.items()
        if path.replace("\\", "/").startswith("custom_components/sems/")
    }
    config_flow = next(
        (data for path, data in modules.items() if Path(path).name == "config_flow.py"),
        None,
    )
    if config_flow is None:
        summary.append(
            "- **Bronze: config-flow-test-coverage:** `config_flow.py` not found in coverage."
        )
    else:
        covered = config_flow["covered_lines"]
        total = config_flow["num_statements"]
        percent = covered / total * 100 if total else 100.0
        summary.append(
            f"- **Bronze: config-flow-test-coverage (line coverage only):** "
            f"{'PASS' if total and covered == total else 'BELOW 100%'} "
            f"({covered}/{total}, {percent:.2f}%). Flow scenarios still need review."
        )
        if total and covered != total:
            print(
                f"::warning file=custom_components/sems/config_flow.py::"
                f"Bronze config-flow line coverage is {percent:.2f}%; 100% is required."
            )

    if not modules:
        summary.append(
            "- **Silver: test-coverage:** No integration modules found in coverage."
        )
    else:
        below_threshold = {
            path: data
            for path, data in modules.items()
            if data["num_statements"] == 0 or data["percent_covered"] <= 95
        }
        if below_threshold:
            details = ", ".join(
                f"`{path}` ({data['percent_covered']:.2f}%)"
                for path, data in sorted(below_threshold.items())
            )
            summary.append(
                f"- **Silver: test-coverage:** {len(below_threshold)} module(s) "
                f"do not exceed 95%: {details}."
            )
            for path, data in sorted(below_threshold.items()):
                print(
                    f"::warning file={path}::Silver test coverage is "
                    f"{data['percent_covered']:.2f}%; it must exceed 95%."
                )
        else:
            summary.append(
                f"- **Silver: test-coverage:** PASS; all {len(modules)} "
                "integration modules exceed 95%."
            )

summary.extend(
    [
        "- **Gold:** Requires human review; no automated tier verdict is claimed.",
        "",
    ]
)
Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text("\n".join(summary))
