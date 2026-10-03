"""Validate the fixture catalog and its referenced response files."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = REPOSITORY_ROOT / "api_examples" / "index.json"
PROVENANCE_TYPES = {
    "api_capture",
    "endpoint_inventory",
    "issue_report",
    "reported_schema",
    "synthetic",
    "unverified_capture",
}


def test_api_example_index_references_unique_json_files() -> None:
    catalog = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    assert catalog["schema_version"] == 1

    examples = catalog["examples"]
    paths = [example["path"] for example in examples]
    assert len(paths) == len(set(paths))

    for example in examples:
        assert example["provenance"] in PROVENANCE_TYPES
        path = (REPOSITORY_ROOT / example["path"]).resolve()
        assert path.is_relative_to(REPOSITORY_ROOT)
        assert path.is_file()
        json.loads(path.read_text(encoding="utf-8"))
        for test_path in example.get("tests", []):
            assert (REPOSITORY_ROOT / test_path).is_file()


def test_legacy_multi_inverter_fixture_keeps_serials_distinct() -> None:
    fixture = REPOSITORY_ROOT / "api_examples/legacy/multiple_inverters.json"
    devices = json.loads(fixture.read_text(encoding="utf-8"))["data"]["list"]
    serials = [device["sn"] for device in devices]

    assert len(serials) > 1
    assert len(serials) == len(set(serials))


def test_legacy_get_data_fixture_redacts_device_check_code() -> None:
    fixture = REPOSITORY_ROOT / "api_examples/legacy/sydneywonder_get_data.json"
    devices = json.loads(fixture.read_text(encoding="utf-8"))["inverter"]
    check_codes = [
        item["value"]
        for item in devices[0]["dict"]["left"]
        if item.get("key") == "laCheckcode"
    ]

    assert check_codes == ["<redacted>"]


def test_index_covers_all_shared_fixture_json() -> None:
    git_root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
    )
    integration_path = REPOSITORY_ROOT.relative_to(git_root)
    tracked_paths = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            str(integration_path / "api_examples"),
            str(integration_path / "tests/test-data"),
        ],
        cwd=git_root,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.splitlines()
    expected = {
        Path(path).relative_to(integration_path).as_posix()
        for path in tracked_paths
        if path.endswith(".json")
        and Path(path).relative_to(integration_path).as_posix()
        != "api_examples/index.json"
    }
    catalog = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    indexed = {example["path"] for example in catalog["examples"]}

    assert indexed == expected
