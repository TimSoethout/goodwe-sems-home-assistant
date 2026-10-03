"""Validate the observed OpenAPI document and its local fixture references."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPOSITORY_ROOT / "api_examples" / "openapi.yaml"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def resolve_schema_refs(schema: object, document: dict[str, object]) -> object:
    if isinstance(schema, list):
        return [resolve_schema_refs(item, document) for item in schema]
    if not isinstance(schema, dict):
        return schema

    if "$ref" in schema:
        reference = schema["$ref"]
        assert isinstance(reference, str) and reference.startswith("#/")
        resolved: object = document
        for part in reference[2:].split("/"):
            assert isinstance(resolved, dict)
            resolved = resolved[part.replace("~1", "/").replace("~0", "~")]
        resolved = resolve_schema_refs(resolved, document)
        siblings = {key: value for key, value in schema.items() if key != "$ref"}
        if siblings:
            return {
                "allOf": [
                    resolved,
                    resolve_schema_refs(siblings, document),
                ]
            }
        return resolved

    return {key: resolve_schema_refs(value, document) for key, value in schema.items()}


def test_openapi_spec_and_fixture_references() -> None:
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    assert spec["openapi"] == "3.1.0"
    validate(spec)

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
                    schema = media_type.get("schema")
                    validator = (
                        Draft202012Validator(resolve_schema_refs(schema, spec))
                        if schema is not None
                        else None
                    )
                    for example in media_type.get("examples", {}).values():
                        if "externalValue" in example:
                            reference = example["externalValue"]
                            fixture_references.add(reference)
                            if validator is not None:
                                parsed = urlsplit(reference)
                                fixture_path = (
                                    SPEC_PATH.parent / parsed.path
                                ).resolve()
                                value = json.loads(
                                    fixture_path.read_text(encoding="utf-8")
                                )
                                error = next(validator.iter_errors(value), None)
                                assert error is None, (
                                    f"{reference} fails its response schema: "
                                    f"{'/'.join(map(str, error.absolute_path))}: "
                                    f"{error.message}"
                                )

    assert len(operation_ids) == len(set(operation_ids))
    assert fixture_references
    for reference in fixture_references:
        parsed = urlsplit(reference)
        assert not parsed.scheme and not parsed.netloc
        fixture_path = (SPEC_PATH.parent / parsed.path).resolve()
        assert fixture_path.is_relative_to(REPOSITORY_ROOT)
        assert fixture_path.is_file()
        json.loads(fixture_path.read_text(encoding="utf-8"))
