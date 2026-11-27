#!/usr/bin/env python3
"""Complete first-run Home Assistant onboarding for the devcontainer."""

from __future__ import annotations

import asyncio
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

try:
    if len(sys.argv) > 1:
        core_dir = Path(sys.argv[1]).resolve()
        site_packages = next(core_dir.glob(".venv/lib/python*/site-packages"), None)
        if site_packages is not None:
            sys.path.insert(0, str(site_packages))
    import websockets
except Exception as error:
    websockets = None
    WEBSOCKETS_IMPORT_ERROR = f"{type(error).__name__}: {error}"
else:
    WEBSOCKETS_IMPORT_ERROR = ""

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

    print(f"Home Assistant URL: {BASE_URL}")
    print(f"Developer credentials: {path}")


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


async def async_prepare_ha_mcp(session_token: str) -> str:
    """Mint an admin token and install HA-MCP through the Marketplace."""
    if websockets is None:
        raise RuntimeError(
            "websockets is required for HA-MCP Marketplace setup"
            f"{': ' + WEBSOCKETS_IMPORT_ERROR if WEBSOCKETS_IMPORT_ERROR else ''}"
        )

    ws_url = (
        f"{BASE_URL.replace('http://', 'ws://', 1).replace('https://', 'wss://', 1)}"
        "/api/websocket"
    )

    async def receive_result(websocket: Any, message_id: int) -> dict[str, Any]:
        while True:
            raw_message = await asyncio.wait_for(websocket.recv(), REQUEST_TIMEOUT)
            message = json.loads(raw_message)
            if message.get("id") == message_id:
                return message

    async def receive_message(websocket: Any) -> dict[str, Any]:
        raw_message = await asyncio.wait_for(websocket.recv(), REQUEST_TIMEOUT)
        return json.loads(raw_message)

    async def send_command(websocket: Any, command: dict[str, Any]) -> None:
        await websocket.send(json.dumps(command))

    async with websockets.connect(
        ws_url,
        open_timeout=REQUEST_TIMEOUT,
        max_size=None,
    ) as websocket:
        message = await receive_message(websocket)
        if message.get("type") != "auth_required":
            raise RuntimeError("Home Assistant did not start websocket authentication")

        await send_command(websocket, {"type": "auth", "access_token": session_token})
        message = await receive_message(websocket)
        if message.get("type") != "auth_ok":
            raise RuntimeError("Home Assistant websocket authentication failed")

        await send_command(websocket, {"id": 1, "type": "marketplace/warning/accept"})
        warning = await receive_result(websocket, 1)
        if not warning.get("success"):
            error = warning.get("error")
            if isinstance(error, dict):
                code = error.get("code")
                message = error.get("message")
                details = ": ".join(
                    str(part)
                    for part in (code, message)
                    if isinstance(part, str) and part
                )
                if details:
                    raise RuntimeError(
                        f"Could not accept the Marketplace warning: {details}"
                    )
            raise RuntimeError("Could not accept the Marketplace warning")

        await send_command(
            websocket,
            {
                "id": 2,
                "type": "auth/long_lived_access_token",
                "client_name": f"HA-MCP Devcontainer {secrets.token_hex(4)}",
                "lifespan": 3650,
            },
        )
        token_result = await receive_result(websocket, 2)
        admin_token = token_result.get("result")
        if not token_result.get("success") or not isinstance(admin_token, str):
            error = token_result.get("error")
            if isinstance(error, dict):
                code = error.get("code")
                message = error.get("message")
                details = ": ".join(
                    str(part)
                    for part in (code, message)
                    if isinstance(part, str) and part
                )
                if details:
                    raise RuntimeError(
                        f"Could not create the HA-MCP access token: {details}"
                    )
            raise RuntimeError("Could not create the HA-MCP access token")

        await send_command(
            websocket,
            {
                "id": 3,
                "type": "marketplace/repositories/list",
                "categories": ["integration"],
            },
        )
        listed = await receive_result(websocket, 3)
        if not listed.get("success") or not isinstance(listed.get("result"), list):
            raise RuntimeError("Could not list the Marketplace repositories")

        for repository in listed["result"]:
            if (
                isinstance(repository, dict)
                and repository.get("full_name") == "homeassistant-ai/ha-mcp"
            ):
                if not repository.get("installed"):
                    await send_command(
                        websocket,
                        {
                            "id": 4,
                            "type": "marketplace/repository/install",
                            "repository": repository["id"],
                        },
                    )
                    installed = await receive_result(websocket, 4)
                    if not installed.get("success"):
                        raise RuntimeError("Could not install HA-MCP")
                return admin_token

    raise RuntimeError("HA-MCP was not found in the Marketplace catalog")


def prepare_ha_mcp(session_token: str) -> str:
    """Run HA-MCP Marketplace and token preparation."""
    return asyncio.run(async_prepare_ha_mcp(session_token))


def ha_mcp_server_entry_exists(session_token: str) -> bool:
    """Return whether an HA-MCP server config entry is configured."""
    entries = request_json(
        "/api/config/config_entries/entry?domain=ha_mcp_tools",
        token=session_token,
    )
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("unique_id") == "ha_mcp_tools-server" or (
                entry.get("domain") == "ha_mcp_tools"
                and entry.get("title") == "HA-MCP Server"
            ):
                return True
    return False


def configure_ha_mcp(session_token: str, admin_token: str) -> None:
    """Create the HA-MCP server config entry if it is not already configured."""
    if ha_mcp_server_entry_exists(session_token):
        print("HA-MCP server integration is already configured")
        return

    deadline = time.monotonic() + 60
    while True:
        try:
            flow = request_json(
                "/api/config/config_entries/flow",
                {"handler": "ha_mcp_tools"},
                token=session_token,
            )
            break
        except HTTPError as error:
            if error.code != 404 or time.monotonic() >= deadline:
                raise
            time.sleep(2)
    if not isinstance(flow, dict) or not isinstance(flow.get("flow_id"), str):
        raise RuntimeError("HA-MCP config flow did not start")

    flow_id = flow["flow_id"]
    menu = request_json(
        f"/api/config/config_entries/flow/{flow_id}",
        {"next_step_id": "server"},
        token=session_token,
    )
    if not isinstance(menu, dict):
        raise RuntimeError("HA-MCP server setup step did not open")

    result = request_json(
        f"/api/config/config_entries/flow/{flow_id}",
        {
            "admin_token": admin_token,
            "remote_access": "disabled",
        },
        token=session_token,
    )
    if not isinstance(result, dict) or result.get("type") != "create_entry":
        raise RuntimeError("HA-MCP server config entry was not created")
    print("HA-MCP server integration configured")


def main() -> None:
    """Create a dev owner and complete the remaining onboarding steps."""
    core_dir = Path(sys.argv[1]).resolve()
    wait_for_home_assistant()

    steps = onboarding_status()
    if steps is None or all(steps.values()):
        print("Home Assistant onboarding is already complete")
        print_dev_credentials(core_dir)
        credentials = load_or_create_credentials(core_dir)
        session_token = login(credentials)
        if not ha_mcp_server_entry_exists(session_token):
            admin_token = prepare_ha_mcp(session_token)
            configure_ha_mcp(session_token, admin_token)
        else:
            configure_ha_mcp(session_token, "")
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
    if not ha_mcp_server_entry_exists(token):
        admin_token = prepare_ha_mcp(token)
        configure_ha_mcp(token, admin_token)
    else:
        configure_ha_mcp(token, "")


if __name__ == "__main__":
    main()
