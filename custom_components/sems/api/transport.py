"""Transport and log-safety helpers for SEMS HTTP calls."""

import re
from typing import Any, TypeGuard
from urllib.parse import parse_qsl, urlsplit, urlunsplit


def is_web_statistics(value: object) -> TypeGuard[dict[str, list[float]]]:
    """Return whether a cached value contains normalized SEMS statistics."""
    return isinstance(value, dict) and all(
        isinstance(key, str)
        and isinstance(values, list)
        and all(isinstance(statistic, float) for statistic in values)
        for key, values in value.items()
    )


def safe_url_for_log(url: str) -> str:
    """Return request endpoint context without identifiers or query values."""
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname or ""
        if hostname == "goodwe.com" or hostname.endswith(".goodwe.com"):
            host = "goodwe.com"
        elif hostname == "semsportal.com" or hostname.endswith(".semsportal.com"):
            host = "semsportal.com"
        else:
            host = "<host>"
    except ValueError:
        return "<invalid-url>"

    path_parts: list[str] = []
    previous = ""
    for part in (item for item in parsed.path.split("/") if item):
        if (
            any(character.isdigit() for character in part)
            or "@" in part
            or previous in {"control-item-content-list", "equipments"}
        ):
            path_parts.append("<redacted>")
        else:
            path_parts.append(part)
        previous = part
    path = f"/{'/'.join(path_parts)}" if path_parts else ""
    query = "&".join(
        f"{key}=<redacted>"
        for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
    )
    return urlunsplit((parsed.scheme, host, path, query, ""))


def safe_response_code_for_log(response_code: Any) -> str:
    """Return an API status code only when it has a known-safe shape."""
    value = str(response_code)
    return value if re.fullmatch(r"(?:[A-Z]{1,3})?\d{3,6}", value) else "<redacted>"
