import argparse
import json
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from upload_release_asset import get_release

ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = ROOT / "custom_components" / "sems"
VERSION = json.loads((INTEGRATION / "manifest.json").read_text())["version"]
SEMVER = re.compile(r"\d+\.\d+\.\d+-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*\Z")
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


def tag_exists() -> bool:
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "origin", f"refs/tags/{VERSION}"],
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 2):
        raise SystemExit(f"Could not check tag {VERSION}: {result.stderr.strip()}")
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--target", default="master")
    args = parser.parse_args()

    if not isinstance(VERSION, str) or not SEMVER.fullmatch(VERSION):
        raise SystemExit(f"Unsupported prerelease version {VERSION}")
    notes = release_notes()

    if args.check:
        if tag_exists():
            raise SystemExit(f"Tag {VERSION} already exists")
        if get_release(VERSION, allow_missing=True) is not None:
            raise SystemExit(f"Release {VERSION} already exists")
        print(
            f"Validated prerelease {VERSION} ({len(notes.splitlines())} notes lines)."
        )
        return

    if tag_exists():
        raise SystemExit(f"Tag {VERSION} already exists")
    if get_release(VERSION, allow_missing=True) is not None:
        raise SystemExit(f"Release {VERSION} already exists")

    with TemporaryDirectory() as temp_dir:
        notes_path = Path(temp_dir) / "release-notes.md"
        notes_path.write_text(notes, encoding="utf-8")
        subprocess.run(
            [
                "gh",
                "release",
                "create",
                VERSION,
                "--prerelease",
                "--title",
                VERSION,
                "--notes-file",
                str(notes_path),
                "--target",
                args.target,
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
