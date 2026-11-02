import os
import subprocess
from pathlib import Path

result = subprocess.run(
    [
        "mypy",
        "custom_components/",
        "--strict",
        "--ignore-missing-imports",
        "--python-version",
        "3.14",
    ],
    capture_output=True,
    text=True,
    check=False,
)

summary = ["## Home Assistant quality-scale advisory checks", ""]
if result.returncode == 0:
    summary.append("- **Platinum: strict-typing:** PASS (`mypy --strict`).")
else:
    summary.extend(
        [
            "- **Platinum: strict-typing:** Issues found by the advisory `mypy --strict` probe.",
            "",
            "```text",
            *f"{result.stdout}{result.stderr}".splitlines()[:30],
            "```",
        ]
    )
    print(
        "::warning title=Platinum strict typing::mypy --strict reported issues; see the job summary."
    )

with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as summary_file:
    summary_file.write("\n".join(summary) + "\n")
