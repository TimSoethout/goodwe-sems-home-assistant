"""Validate the observed OpenAPI document and its local fixture references."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPOSITORY_ROOT / "api_examples" / "openapi.yaml"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def test_openapi_spec_and_fixture_references() -> None:
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    assert spec["openapi"] == "3.1.0"

    operation_ids: list[str] = []
    fixture_references: set[str] = set()
    for path_item in spec["paths"].values():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            operation_ids.append(operation["operationId"])
            fixture_references.update(
                operation.get("x-evidence", {}).get("fixtures", [])
            )
            fixture_references.update(
                operation.get("x-evidence", {}).get("reportedFixtures", [])
            )
            for response in operation["responses"].values():
                for media_type in response.get("content", {}).values():
                    for example in media_type.get("examples", {}).values():
                        if "externalValue" in example:
                            fixture_references.add(example["externalValue"])

    assert len(operation_ids) == len(set(operation_ids))
    assert fixture_references
    for reference in fixture_references:
        parsed = urlsplit(reference)
        assert not parsed.scheme and not parsed.netloc
        fixture_path = (SPEC_PATH.parent / parsed.path).resolve()
        assert fixture_path.is_relative_to(REPOSITORY_ROOT)
        assert fixture_path.is_file()
        json.loads(fixture_path.read_text(encoding="utf-8"))
