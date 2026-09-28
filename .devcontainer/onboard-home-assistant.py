#!/usr/bin/env python3
"""Complete first-run Home Assistant onboarding for the devcontainer."""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = os.environ.get("HA_BASE_URL", "http://localhost:8123").rstrip("/")
CLIENT_ID = f"{BASE_URL}/"
REQUEST_TIMEOUT = 5
STARTUP_TIMEOUT = 120


def request_json(
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    token: str | None = None,
    form: bool = False,
) -> Any:
    """Send a JSON or form-encoded request to Home Assistant."""
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    body = None
    if payload is not None:
        if form:
            body = urlencode(payload).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"

    request = Request(f"{BASE_URL}{path}", data=body, headers=headers)
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.load(response)


def wait_for_home_assistant() -> None:
    """Wait until the Home Assistant HTTP API is available."""
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while True:
        try:
            request_json("/api/")
            return
        except HTTPError as error:
            if error.code == 401:
                return
            raise
        except URLError:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "Home Assistant did not become ready within "
                    f"{STARTUP_TIMEOUT} seconds"
                ) from None
            time.sleep(2)


def onboarding_status() -> dict[str, bool] | None:
    """Return onboarding steps, or None if onboarding is already unavailable."""
    try:
        response = request_json("/api/onboarding")
    except HTTPError as error:
        if error.code == 404:
            return None
        raise RuntimeError(
            f"Home Assistant returned HTTP {error.code} for /api/onboarding"
        ) from error

    if not isinstance(response, list):
        raise RuntimeError("Unexpected response from Home Assistant onboarding API")
    return {step["step"]: step["done"] for step in response}


def load_or_create_credentials(core_dir: Path) -> dict[str, str]:
    """Load local dev credentials or persist a newly generated password."""
    path = core_dir / ".dev-owner-credentials.json"
    if path.exists():
        credentials = json.loads(path.read_text(encoding="utf-8"))
        path.chmod(0o600)
        return credentials

    credentials = {
        "name": "Home Assistant Developer",
        "username": "developer",
        "password": secrets.token_urlsafe(32),
    }
    core_dir.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        json.dump(credentials, file)
        file.write("\n")
    return credentials


def print_dev_credentials(core_dir: Path) -> None:
    """Show the saved developer login in the devcontainer startup output."""
    path = core_dir / ".dev-owner-credentials.json"
    if not path.exists():
        print("No developer credentials were saved by this setup.")
        return

    credentials = load_or_create_credentials(core_dir)
    print(f"Home Assistant URL: {BASE_URL}")
    print(f"Username: {credentials['username']}")
    print(f"Password: {credentials['password']}")


def exchange_auth_code(auth_code: str) -> str:
    """Exchange an onboarding authorization code for an access token."""
    response = request_json(
        "/auth/token",
        {
            "client_id": CLIENT_ID,
            "grant_type": "authorization_code",
            "code": auth_code,
        },
        form=True,
    )
    if not isinstance(response, dict) or not isinstance(
        response.get("access_token"), str
    ):
        raise RuntimeError("Home Assistant did not return an access token")
    return response["access_token"]


def login(credentials: dict[str, str]) -> str:
    """Authenticate the stored dev owner to resume interrupted onboarding."""
    flow = request_json(
        "/auth/login_flow",
        {
            "client_id": CLIENT_ID,
            "handler": ["homeassistant", None],
            "redirect_uri": CLIENT_ID,
        },
    )
    if not isinstance(flow, dict) or not isinstance(flow.get("flow_id"), str):
        raise RuntimeError("Home Assistant did not start the owner login flow")

    result = request_json(
        f"/auth/login_flow/{flow['flow_id']}",
        {
            "client_id": CLIENT_ID,
            "username": credentials["username"],
            "password": credentials["password"],
        },
    )
    if not isinstance(result, dict) or not isinstance(result.get("result"), str):
        raise RuntimeError("Could not authenticate the stored dev owner")
    return exchange_auth_code(result["result"])


def main() -> None:
    """Create a dev owner and complete the remaining onboarding steps."""
    core_dir = Path(sys.argv[1]).resolve()
    wait_for_home_assistant()

    steps = onboarding_status()
    if steps is None or all(steps.values()):
        print("Home Assistant onboarding is already complete")
        print_dev_credentials(core_dir)
        return

    if steps.get("user", False):
        credential_file = core_dir / ".dev-owner-credentials.json"
        if not credential_file.exists():
            print(
                "Home Assistant onboarding was started manually; finish the "
                "remaining steps in the UI."
            )
            return
        credentials = load_or_create_credentials(core_dir)
        token = login(credentials)
    else:
        credentials = load_or_create_credentials(core_dir)
        result = request_json(
            "/api/onboarding/users",
            {
                "client_id": CLIENT_ID,
                **credentials,
                "language": "en",
            },
        )
        if not isinstance(result, dict) or not isinstance(result.get("auth_code"), str):
            raise RuntimeError("Home Assistant did not create the dev owner")
        token = exchange_auth_code(result["auth_code"])

    for step in ("core_config", "analytics", "integration"):
        if steps.get(step, False):
            continue
        payload = (
            {"client_id": CLIENT_ID, "redirect_uri": CLIENT_ID}
            if step == "integration"
            else {}
        )
        request_json(f"/api/onboarding/{step}", payload, token=token)

    remaining_steps = onboarding_status()
    if remaining_steps is not None and not all(remaining_steps.values()):
        raise RuntimeError("Home Assistant onboarding did not finish all steps")

    print("Home Assistant onboarding complete")
    print_dev_credentials(core_dir)


if __name__ == "__main__":
    main()
