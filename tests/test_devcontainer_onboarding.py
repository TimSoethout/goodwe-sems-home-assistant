"""Checks for the devcontainer's first-run onboarding helper."""

import importlib.util
import io
import json
import stat
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

HELPER = (
    Path(__file__).resolve().parents[1] / ".devcontainer" / "onboard-home-assistant.py"
)
REPO_ROOT = HELPER.parents[1]
SPEC = importlib.util.spec_from_file_location("devcontainer_onboarding", HELPER)
assert SPEC is not None and SPEC.loader is not None
ONBOARDING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ONBOARDING)


def test_home_assistant_lifecycle_is_controlled_by_tasks() -> None:
    devcontainer = json.loads(
        (REPO_ROOT / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8")
    )
    tasks = json.loads(
        (REPO_ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8")
    )["tasks"]
    startup_script = (REPO_ROOT / ".devcontainer" / "start-home-assistant").read_text(
        encoding="utf-8"
    )

    assert "postStartCommand" not in devcontainer
    lifecycle_tasks = {
        task["label"]: task["command"]
        for task in tasks
        if "start-home-assistant" in task["command"]
        or "terminate-home-assistant" in task["command"]
    }
    assert lifecycle_tasks == {
        "SEMS: run Home Assistant": "bash .devcontainer/start-home-assistant --foreground",
        "SEMS: restart Home Assistant": (
            "bash .devcontainer/start-home-assistant --restart"
        ),
        "SEMS: terminate Home Assistant": (
            "bash .devcontainer/start-home-assistant --terminate"
        ),
    }
    assert '"$python" "$repo_root/.devcontainer/onboard-home-assistant.py"' in (
        startup_script
    )
    assert devcontainer["forwardPorts"] == [8123]
    assert "8123" in devcontainer["portsAttributes"]


def test_devcontainer_uses_home_assistant_marketplace() -> None:
    setup_script = (REPO_ROOT / ".devcontainer" / "setup.sh").read_text(
        encoding="utf-8"
    )

    assert "get.hacs.xyz" not in setup_script
    assert "HACS through the built-in Marketplace" in setup_script
    assert "HA-MCP will be installed through the built-in Marketplace" in setup_script
    assert "ha-mcp.git" not in setup_script


def test_devcontainer_syncs_go2rtc_binary_with_home_assistant() -> None:
    setup_script = (REPO_ROOT / ".devcontainer" / "setup.sh").read_text(
        encoding="utf-8"
    )

    assert "RECOMMENDED_VERSION" in setup_script
    assert "go2rtc/releases/download/v${go2rtc_version}" in setup_script


def test_wait_for_home_assistant_accepts_unauthorized_api_response() -> None:
    unauthorized = HTTPError(
        url="http://localhost:8123/api/",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=None,
    )
    with patch.object(ONBOARDING, "request_json", side_effect=unauthorized):
        ONBOARDING.wait_for_home_assistant()


def test_request_json_sends_bearer_token() -> None:
    with patch.object(
        ONBOARDING, "urlopen", return_value=io.BytesIO(b"{}")
    ) as open_url:
        assert (
            ONBOARDING.request_json("/api/onboarding/core_config", token="secret") == {}
        )

    request = open_url.call_args.args[0]
    assert request.get_header("Authorization") == "Bearer secret"


def test_configure_ha_mcp_is_idempotent() -> None:
    entries = [
        {
            "domain": "ha_mcp_tools",
            "title": "HA-MCP Server",
            "unique_id": "ha_mcp_tools-server",
        }
    ]
    with (
        patch.object(ONBOARDING, "request_json", return_value=entries),
        patch("builtins.print") as print_output,
    ):
        ONBOARDING.configure_ha_mcp("test-access-token", "")

    print_output.assert_called_once_with(
        "HA-MCP server integration is already configured"
    )


def test_configure_ha_mcp_creates_server_entry() -> None:
    calls: list[tuple[str, dict[str, object] | None, str | None]] = []

    def request_json(path, payload=None, *, token=None, form=False):
        calls.append((path, payload, token))
        if path.endswith("entry?domain=ha_mcp_tools"):
            return []
        if path == "/api/config/config_entries/flow":
            return {"flow_id": "test-flow", "type": "menu"}
        if path.endswith("/test-flow"):
            if payload == {"next_step_id": "server"}:
                return {"type": "menu", "step_id": "server"}
            if payload == {
                "admin_token": "test-long-lived-token",
                "remote_access": "disabled",
            }:
                return {"type": "create_entry"}
        raise AssertionError(f"Unexpected HA-MCP config request: {path}")

    with (
        patch.object(ONBOARDING, "request_json", side_effect=request_json),
        patch("builtins.print"),
    ):
        ONBOARDING.configure_ha_mcp("test-access-token", "test-long-lived-token")

    assert calls == [
        (
            "/api/config/config_entries/entry?domain=ha_mcp_tools",
            None,
            "test-access-token",
        ),
        (
            "/api/config/config_entries/flow",
            {"handler": "ha_mcp_tools"},
            "test-access-token",
        ),
        (
            "/api/config/config_entries/flow/test-flow",
            {"next_step_id": "server"},
            "test-access-token",
        ),
        (
            "/api/config/config_entries/flow/test-flow",
            {
                "admin_token": "test-long-lived-token",
                "remote_access": "disabled",
            },
            "test-access-token",
        ),
    ]


def test_completed_onboarding_installs_missing_ha_mcp(tmp_path: Path) -> None:
    credential_file = tmp_path / ".dev-owner-credentials.json"
    credential_file.write_text(
        json.dumps({"username": "developer", "password": "saved-password"})
    )
    completed_steps = {
        step: True for step in ("user", "core_config", "analytics", "integration")
    }

    with (
        patch.object(ONBOARDING, "onboarding_status", return_value=completed_steps),
        patch.object(ONBOARDING, "wait_for_home_assistant"),
        patch.object(ONBOARDING, "login", return_value="test-access-token"),
        patch.object(ONBOARDING, "ha_mcp_server_entry_exists", return_value=False),
        patch.object(
            ONBOARDING,
            "prepare_ha_mcp",
            return_value="test-long-lived-token",
        ) as prepare_ha_mcp,
        patch.object(ONBOARDING, "configure_ha_mcp") as configure_ha_mcp,
        patch.object(sys, "argv", ["onboard-home-assistant.py", str(tmp_path)]),
    ):
        ONBOARDING.main()

    prepare_ha_mcp.assert_called_once_with("test-access-token")
    configure_ha_mcp.assert_called_once_with(
        "test-access-token", "test-long-lived-token"
    )


def test_onboards_new_instance_with_private_generated_credentials(
    tmp_path: Path, capsys
) -> None:
    initial_steps = [
        {"step": step, "done": False}
        for step in ("user", "core_config", "analytics", "integration")
    ]
    completed_steps = [{"step": step["step"], "done": True} for step in initial_steps]
    statuses = iter((initial_steps, completed_steps))
    onboarding_calls: list[tuple[str, str | None]] = []

    def request_json(path, payload=None, *, token=None, form=False):
        if path == "/api/":
            return {}
        if path == "/api/onboarding":
            return next(statuses)
        if path == "/api/onboarding/users":
            assert payload["username"] == "developer"
            assert payload["language"] == "en"
            return {"auth_code": "one-time-code"}
        if path == "/auth/token":
            assert form
            return {"access_token": "test-access-token"}
        if path.startswith("/api/onboarding/"):
            onboarding_calls.append((path, token))
            return {}
        raise AssertionError(f"Unexpected Home Assistant request: {path}")

    with (
        patch.object(ONBOARDING, "request_json", side_effect=request_json),
        patch.object(ONBOARDING, "wait_for_home_assistant"),
        patch.object(ONBOARDING, "ha_mcp_server_entry_exists", return_value=True),
        patch.object(ONBOARDING, "configure_ha_mcp") as configure_ha_mcp,
        patch.object(sys, "argv", ["onboard-home-assistant.py", str(tmp_path)]),
    ):
        ONBOARDING.main()

    credential_file = tmp_path / ".dev-owner-credentials.json"
    credentials = json.loads(credential_file.read_text(encoding="utf-8"))
    output = capsys.readouterr().out
    assert credentials["username"] not in output
    assert credentials["password"] not in output
    assert str(credential_file) in output
    assert stat.S_IMODE(credential_file.stat().st_mode) == 0o600
    assert onboarding_calls == [
        (f"/api/onboarding/{step}", "test-access-token")
        for step in ("core_config", "analytics", "integration")
    ]
    configure_ha_mcp.assert_called_once_with("test-access-token", "")


def test_prints_saved_credentials_when_onboarding_is_already_complete(
    tmp_path: Path, capsys
) -> None:
    credential_file = tmp_path / ".dev-owner-credentials.json"
    credential_file.write_text(
        json.dumps({"username": "developer", "password": "saved-password"}),
        encoding="utf-8",
    )
    completed_steps = {
        step: True for step in ("user", "core_config", "analytics", "integration")
    }

    with (
        patch.object(ONBOARDING, "onboarding_status", return_value=completed_steps),
        patch.object(ONBOARDING, "wait_for_home_assistant"),
        patch.object(ONBOARDING, "login", return_value="test-access-token"),
        patch.object(ONBOARDING, "ha_mcp_server_entry_exists", return_value=True),
        patch.object(ONBOARDING, "configure_ha_mcp") as configure_ha_mcp,
        patch.object(sys, "argv", ["onboard-home-assistant.py", str(tmp_path)]),
    ):
        ONBOARDING.main()

    output = capsys.readouterr().out
    assert "developer" not in output
    assert "saved-password" not in output
    assert str(credential_file) in output
    assert stat.S_IMODE(credential_file.stat().st_mode) == 0o600
    configure_ha_mcp.assert_called_once_with("test-access-token", "")
