import json
import subprocess
import sys
from pathlib import Path

INTEGRATION = Path(__file__).resolve().parents[2] / "custom_components" / "sems"


def get_release(tag: str, *, allow_missing: bool = False) -> dict | None:
    result = subprocess.run(
        ["gh", "release", "view", tag, "--json", "isDraft,isPrerelease,assets"],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        if allow_missing:
            return None
        raise SystemExit(result.stderr.strip() or f"Could not inspect release {tag}")
    return json.loads(result.stdout)


def upload_release_asset(
    tag: str, *, stable: bool = False, release: dict | None = None
) -> None:
    release = release if release is not None else get_release(tag)
    if release is None:
        raise SystemExit(f"Could not inspect release {tag}")
    if release["isDraft"]:
        raise SystemExit(f"Release {tag} is still a draft")
    if stable and release["isPrerelease"]:
        raise SystemExit(f"Release {tag} is marked as a prerelease")
    if any(asset["name"] == "sems.zip" for asset in release["assets"]):
        print(f"Release {tag} already has sems.zip; skipping.")
        return

    archive = INTEGRATION / "sems.zip"
    archive.unlink(missing_ok=True)
    subprocess.run(["zip", "sems.zip", "-r", "./"], cwd=INTEGRATION, check=True)
    subprocess.run(["gh", "release", "upload", tag, str(archive)], check=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: upload_release_asset.py <release-tag>")
    upload_release_asset(sys.argv[1])
