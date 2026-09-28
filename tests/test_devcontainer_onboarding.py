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
SPEC = importlib.util.spec_from_file_location("devcontainer_onboarding", HELPER)
assert SPEC is not None and SPEC.loader is not None
ONBOARDING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ONBOARDING)


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
        patch.object(sys, "argv", ["onboard-home-assistant.py", str(tmp_path)]),
    ):
        ONBOARDING.main()

    credential_file = tmp_path / ".dev-owner-credentials.json"
    credentials = json.loads(credential_file.read_text(encoding="utf-8"))
    output = capsys.readouterr().out
    assert credentials["username"] in output
    assert credentials["password"] in output
    assert stat.S_IMODE(credential_file.stat().st_mode) == 0o600
    assert onboarding_calls == [
        (f"/api/onboarding/{step}", "test-access-token")
        for step in ("core_config", "analytics", "integration")
    ]


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
        patch.object(sys, "argv", ["onboard-home-assistant.py", str(tmp_path)]),
    ):
        ONBOARDING.main()

    output = capsys.readouterr().out
    assert "developer" in output
    assert "saved-password" in output
    assert stat.S_IMODE(credential_file.stat().st_mode) == 0o600
