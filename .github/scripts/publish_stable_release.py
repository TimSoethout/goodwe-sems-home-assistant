import json
import os
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = ROOT / "custom_components" / "sems"
VERSION = json.loads((INTEGRATION / "manifest.json").read_text())["version"]
SEMVER = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z")
RELEASE_HEADING = re.compile(r"^## (\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?) - ")


def release_notes() -> str:
    lines = (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8").splitlines()
    matches = [
        index
        for index, line in enumerate(lines)
        if (match := RELEASE_HEADING.match(line)) and match.group(1) == VERSION
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"Expected one release-notes section for {VERSION}, found {len(matches)}"
        )

    start = matches[0]
    end = next(
        (i for i in range(start + 1, len(lines)) if RELEASE_HEADING.match(lines[i])),
        len(lines),
    )
    section = "\n".join(lines[start:end]).strip()
    if not section:
        raise SystemExit(f"Release notes for {VERSION} are empty")
    return section + "\n"


def existing_release() -> dict | None:
    result = subprocess.run(
        ["gh", "release", "view", VERSION, "--json", "isDraft,isPrerelease,assets"],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        return None

    release = json.loads(result.stdout)
    if release["isDraft"] or release["isPrerelease"]:
        raise SystemExit(f"Release {VERSION} is not a published stable release")
    return release


def tag_exists() -> bool:
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "origin", f"refs/tags/{VERSION}"],
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 2):
        raise SystemExit(f"Could not check tag {VERSION}: {result.stderr.strip()}")
    return result.returncode == 0


def create_zip() -> Path:
    archive = INTEGRATION / "sems.zip"
    archive.unlink(missing_ok=True)
    subprocess.run(["zip", "sems.zip", "-r", "./"], cwd=INTEGRATION, check=True)
    return archive


def main() -> None:
    if not isinstance(VERSION, str) or not SEMVER.fullmatch(VERSION):
        raise SystemExit(f"Unsupported release version: {VERSION}")
    if "-" in VERSION:
        print(f"Skipping prerelease version {VERSION}.")
        return

    notes = release_notes()
    if sys.argv[1:] == ["--check"]:
        print(
            f"Validated stable release {VERSION} ({len(notes.splitlines())} notes lines)."
        )
        return
    if sys.argv[1:]:
        raise SystemExit("Usage: publish_stable_release.py [--check]")

    release = existing_release()
    if release:
        if any(asset["name"] == "sems.zip" for asset in release["assets"]):
            print(f"Release {VERSION} already exists with sems.zip; skipping.")
            return
        print(f"Release {VERSION} exists; attaching the missing sems.zip.")
        subprocess.run(
            ["gh", "release", "upload", VERSION, str(create_zip())], check=True
        )
        return

    if tag_exists():
        raise SystemExit(
            f"Tag {VERSION} already exists without a GitHub Release; refusing to reuse it."
        )

    with TemporaryDirectory() as temp_dir:
        notes_path = Path(temp_dir) / "release-notes.md"
        notes_path.write_text(notes, encoding="utf-8")
        subprocess.run(
            [
                "gh",
                "release",
                "create",
                VERSION,
                "--title",
                VERSION,
                "--notes-file",
                str(notes_path),
                "--target",
                os.environ["GITHUB_SHA"],
                "--latest",
                str(create_zip()),
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
