"""Tests for the offline decisions made by the release scripts."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".github" / "scripts"
ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


UPLOAD = load_script("upload_release_asset")
PUBLISH = load_script("publish_stable_release")
PRERELEASE = load_script("publish_prerelease")


@pytest.fixture
def enable_custom_integrations():
    yield


def test_strict_typing_report_checks_installed_imports(
    tmp_path: Path,
) -> None:
    args_file = tmp_path / "mypy.args"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    mypy = bin_dir / "mypy"
    mypy.write_text(
        f"""#!/bin/sh
printf '%s\\n' "$@" > {args_file}
""",
        encoding="utf-8",
    )
    mypy.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["VIRTUAL_ENV"] = str(bin_dir.parent)
    env["GITHUB_STEP_SUMMARY"] = str(tmp_path / "summary.md")
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "report_quality_scale_strict_typing.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert args_file.read_text(encoding="utf-8").splitlines() == [
        "custom_components/",
        "--strict",
        "--python-version",
        "3.14",
    ]


def test_release_notes_require_exactly_one_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "RELEASE_NOTES.md").write_text(
        "## 1.2.3 - 2026-01-01\n\n- Fixed.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(PUBLISH, "ROOT", tmp_path)
    monkeypatch.setattr(PUBLISH, "VERSION", "1.2.3")

    assert PUBLISH.release_notes() == "## 1.2.3 - 2026-01-01\n\n- Fixed.\n"

    (tmp_path / "RELEASE_NOTES.md").write_text(
        "## 1.2.3 - 2026-01-01\n\n- Duplicate one.\n"
        "## 1.2.3 - 2026-01-02\n\n- Duplicate two.\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match=r"found 2"):
        PUBLISH.release_notes()


def test_prerelease_notes_include_subsections_and_stop_at_next_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "RELEASE_NOTES.md").write_text(
        "## 1.2.3-beta.1 - 2026-01-01\n\n"
        "## Improve reliability\n\n"
        "- Fixed the bug.\n\n"
        "### Compatibility\n\n"
        "- No migration.\n\n"
        "## 1.2.2 - 2025-12-31\n\n"
        "- Previous release.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(PRERELEASE, "ROOT", tmp_path)
    monkeypatch.setattr(PRERELEASE, "VERSION", "1.2.3-beta.1")

    assert PRERELEASE.release_notes() == (
        "## 1.2.3-beta.1 - 2026-01-01\n\n"
        "## Improve reliability\n\n"
        "- Fixed the bug.\n\n"
        "### Compatibility\n\n"
        "- No migration.\n"
    )


def test_prerelease_publish_rejects_stable_and_existing_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(PRERELEASE, "VERSION", "1.2.3")
    monkeypatch.setattr(sys, "argv", ["publish_prerelease.py"])
    with pytest.raises(SystemExit, match=r"Unsupported prerelease version"):
        PRERELEASE.main()

    monkeypatch.setattr(PRERELEASE, "VERSION", "1.2.3-beta.1")
    monkeypatch.setattr(PRERELEASE, "tag_exists", lambda: False)
    monkeypatch.setattr(
        PRERELEASE,
        "get_release",
        lambda *_args, **_kwargs: {"isPrerelease": True, "assets": []},
    )
    monkeypatch.setattr(
        PRERELEASE,
        "release_notes",
        lambda: "## 1.2.3-beta.1 - 2026-01-01\n",
    )
    with pytest.raises(SystemExit, match=r"Release 1\.2\.3-beta\.1 already exists"):
        PRERELEASE.main()


def test_prerelease_publish_creates_release_with_complete_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes = (
        "## 1.2.3-beta.1 - 2026-01-01\n\n## Improve reliability\n\n- Fixed the bug.\n"
    )
    (tmp_path / "RELEASE_NOTES.md").write_text(
        notes + "\n## 1.2.2 - 2025-12-31\n\n- Previous release.\n",
        encoding="utf-8",
    )
    commands = []

    def run(command, **kwargs):
        commands.append((command, kwargs))
        notes_path = Path(command[command.index("--notes-file") + 1])
        assert notes_path.read_text(encoding="utf-8") == notes
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(PRERELEASE, "ROOT", tmp_path)
    monkeypatch.setattr(PRERELEASE, "VERSION", "1.2.3-beta.1")
    monkeypatch.setattr(PRERELEASE, "tag_exists", lambda: False)
    monkeypatch.setattr(PRERELEASE, "get_release", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(PRERELEASE.subprocess, "run", run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["publish_prerelease.py", "--target", "master"],
    )

    PRERELEASE.main()

    command, kwargs = commands[0]
    assert command[:8] == [
        "gh",
        "release",
        "create",
        "1.2.3-beta.1",
        "--prerelease",
        "--title",
        "1.2.3-beta.1",
        "--notes-file",
    ]
    assert command[9:] == ["--target", "master"]
    assert kwargs == {"check": True}


@pytest.mark.parametrize(
    ("returncode", "expected"),
    [(0, True), (2, False)],
)
def test_tag_exists_checks_the_exact_version_tag(
    monkeypatch: pytest.MonkeyPatch, returncode: int, expected: bool
) -> None:
    run = Mock(return_value=subprocess.CompletedProcess([], returncode, "", ""))
    monkeypatch.setattr(PUBLISH, "VERSION", "1.2.3")
    monkeypatch.setattr(PUBLISH.subprocess, "run", run)

    assert PUBLISH.tag_exists() is expected
    assert run.call_args.args[0] == [
        "git",
        "ls-remote",
        "--exit-code",
        "origin",
        "refs/tags/1.2.3",
    ]


def test_tag_check_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        PUBLISH.subprocess,
        "run",
        Mock(
            return_value=subprocess.CompletedProcess([], 1, "", "remote is unavailable")
        ),
    )

    with pytest.raises(SystemExit, match="Could not check tag"):
        PUBLISH.tag_exists()


@pytest.mark.parametrize("version", [None, "1.2", "v1.2.3"])
def test_publish_rejects_unsupported_versions(
    monkeypatch: pytest.MonkeyPatch, version: object
) -> None:
    monkeypatch.setattr(PUBLISH, "VERSION", version)

    with pytest.raises(SystemExit, match="Unsupported release version"):
        PUBLISH.main()


def test_publish_skips_prereleases(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    release_notes = Mock(side_effect=AssertionError("notes must not be read"))
    get_release = Mock(side_effect=AssertionError("GitHub must not be queried"))
    monkeypatch.setattr(PUBLISH, "VERSION", "1.2.3-beta.1")
    monkeypatch.setattr(PUBLISH, "release_notes", release_notes)
    monkeypatch.setattr(PUBLISH, "get_release", get_release)
    monkeypatch.setattr(sys, "argv", ["publish_stable_release.py"])

    PUBLISH.main()

    assert "Skipping prerelease version 1.2.3-beta.1." in capsys.readouterr().out
    release_notes.assert_not_called()
    get_release.assert_not_called()


def test_publish_refuses_to_reuse_an_existing_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload = Mock()
    monkeypatch.setattr(PUBLISH, "VERSION", "1.2.3")
    monkeypatch.setattr(PUBLISH, "release_notes", lambda: "release notes\n")
    monkeypatch.setattr(PUBLISH, "get_release", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(PUBLISH, "tag_exists", lambda: True)
    monkeypatch.setattr(PUBLISH, "upload_release_asset", upload)
    monkeypatch.setattr(sys, "argv", ["publish_stable_release.py"])

    with pytest.raises(SystemExit, match="already exists without a GitHub Release"):
        PUBLISH.main()

    upload.assert_not_called()


def test_publish_creates_a_release_for_an_unused_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = []
    notes = "## 1.2.3 - 2026-01-01\n\n- Fixed.\n"

    def run(command, **kwargs):
        commands.append((command, kwargs))
        notes_path = Path(command[command.index("--notes-file") + 1])
        assert notes_path.read_text(encoding="utf-8") == notes
        return subprocess.CompletedProcess(command, 0)

    upload = Mock()
    monkeypatch.setattr(PUBLISH, "VERSION", "1.2.3")
    monkeypatch.setattr(PUBLISH, "release_notes", lambda: notes)
    monkeypatch.setattr(PUBLISH, "get_release", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(PUBLISH, "tag_exists", lambda: False)
    monkeypatch.setattr(PUBLISH.subprocess, "run", run)
    monkeypatch.setattr(PUBLISH, "upload_release_asset", upload)
    monkeypatch.setattr(sys, "argv", ["publish_stable_release.py"])
    monkeypatch.setenv("GITHUB_SHA", "0123456789abcdef")

    PUBLISH.main()

    assert len(commands) == 1
    command, kwargs = commands[0]
    assert command[:7] == [
        "gh",
        "release",
        "create",
        "1.2.3",
        "--title",
        "1.2.3",
        "--notes-file",
    ]
    assert command[8:] == ["--target", "0123456789abcdef", "--latest"]
    assert kwargs == {"check": True}
    upload.assert_called_once_with("1.2.3", stable=True, release=None)


def test_publish_reuses_existing_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = {"isDraft": False, "isPrerelease": False, "assets": []}
    tag_exists = Mock(side_effect=AssertionError("tag must not be checked"))
    upload = Mock()
    monkeypatch.setattr(PUBLISH, "VERSION", "1.2.3")
    monkeypatch.setattr(PUBLISH, "release_notes", lambda: "release notes\n")
    monkeypatch.setattr(PUBLISH, "get_release", lambda *_args, **_kwargs: release)
    monkeypatch.setattr(PUBLISH, "tag_exists", tag_exists)
    monkeypatch.setattr(PUBLISH, "upload_release_asset", upload)
    monkeypatch.setattr(sys, "argv", ["publish_stable_release.py"])

    PUBLISH.main()

    tag_exists.assert_not_called()
    upload.assert_called_once_with("1.2.3", stable=True, release=release)


@pytest.mark.parametrize(
    ("release", "stable", "message"),
    [
        (
            {"isDraft": True, "isPrerelease": False, "assets": []},
            False,
            "still a draft",
        ),
        (
            {"isDraft": False, "isPrerelease": True, "assets": []},
            True,
            "marked as a prerelease",
        ),
    ],
)
def test_upload_rejects_nonpublishable_release(
    release: dict, stable: bool, message: str
) -> None:
    with pytest.raises(SystemExit, match=message):
        UPLOAD.upload_release_asset("1.2.3", stable=stable, release=release)


def test_upload_skips_an_existing_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock(side_effect=AssertionError("release asset must not be rebuilt"))
    monkeypatch.setattr(UPLOAD.subprocess, "run", run)
    release = {
        "isDraft": False,
        "isPrerelease": False,
        "assets": [{"name": "sems.zip"}],
    }

    UPLOAD.upload_release_asset("1.2.3", release=release)

    run.assert_not_called()


def test_upload_builds_and_uploads_a_prerelease_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = []
    archive = tmp_path / "sems.zip"
    archive.write_bytes(b"old")

    def run(command, **kwargs):
        commands.append((command, kwargs))
        if command[0] == "zip":
            archive.write_bytes(b"new")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(UPLOAD, "INTEGRATION", tmp_path)
    monkeypatch.setattr(UPLOAD.subprocess, "run", run)
    release = {
        "isDraft": False,
        "isPrerelease": True,
        "assets": [],
    }

    UPLOAD.upload_release_asset("1.2.3-beta.1", release=release)

    assert archive.read_bytes() == b"new"
    assert commands == [
        (
            ["zip", "sems.zip", "-r", "./"],
            {"cwd": tmp_path, "check": True},
        ),
        (
            [
                "gh",
                "release",
                "upload",
                "1.2.3-beta.1",
                str(archive),
            ],
            {"check": True},
        ),
    ]
