# GoodWe SEMS Integration

## API changes
- Check real, sanitized captures in [api_examples/](../api_examples/) before changing parsing, coordinator data, or entities. Verify endpoint, response shape, device/factor names, units, signs, and missing fields.
- If no capture covers the response, obtain and sanitize one; add it and document the endpoint/fields in [api_examples/README.md](../api_examples/README.md). Never guess payloads from names or mocks.
- Test captured fixtures through normalization to entity state. Use mocks only for errors, boundaries, missing fields, or cases that cannot be captured. Never call the live API or require credentials in tests.
- Assert unit/sign conversions against captures. If a capture conflicts with code, stop and investigate; never alter a fixture to fit.
- Never commit credentials, tokens, cookies, signatures, station IDs, serial numbers, trace IDs, precise locations or personal names.

## Architecture and conventions
- `config_flow.py` validates credentials; `__init__.py` fetches and normalizes data through one `DataUpdateCoordinator`.
- `SemsApi` uses synchronous `requests`: call it through `hass.async_add_executor_job()`. Keep control payloads intact and use its retry handling.
- Sensors are defined in `sensor.py` with `value_path`; use `empty_value` when empty API values should disable a sensor.
- Use `device_info_for_inverter()` for device grouping. Preserve `_migrate_to_new_unique_id()` when changing sensor IDs.
- SEMS has misspelled keys; use `GOODWE_SPELLING` constants, not corrected inline spellings.

## Development
- Tests: `python -m pytest tests/ -v`; in HA Core, add `--confcutdir=config/goodwe-sems-home-assistant`.
- Checks: `ruff check custom_components/`, `ruff format --check custom_components/`, and `mypy custom_components/ --ignore-missing-imports --python-version 3.14`. Run the narrowest relevant tests and checks for each change.
- Redact sensitive information from logs.
- Use Conventional Commits: `type(scope): summary`; mark breaking changes with `!` or a `BREAKING CHANGE:` footer.

## Domain-specific conventions
- SEMS payload uses misspelled keys; use constants in `GOODWE_SPELLING` (e.g., `homKit`, `tempperature`, `energeStatisticsCharts`) from [custom_components/sems/const.py](../custom_components/sems/const.py) instead of “fixing” them in-line.
- Add new sensors by extending `sensor_options_for_data()` in [custom_components/sems/sensor.py](../custom_components/sems/sensor.py) with a `value_path` list; this makes the entity data-driven and consistent with existing ones.
- If a sensor should be hidden by default when the API value is empty, set `empty_value` in `SemsSensorType`. The base `SemsSensor` disables the entity if the initial value is `None` or matches `empty_value`.
- Device grouping should use `device_info_for_inverter()` in [custom_components/sems/device.py](../custom_components/sems/device.py) to ensure consistent device names and identifiers.
- When touching entity IDs, keep migration logic in mind: `_migrate_to_new_unique_id()` handles legacy `-power` IDs in [custom_components/sems/sensor.py](../custom_components/sems/sensor.py).

## External integrations
- The SEMS API client in [custom_components/sems/sems_api.py](../custom_components/sems/sems_api.py) is synchronous `requests` and handles token retry logic internally; all calls should go through `hass.async_add_executor_job()`.
- Control commands use an undocumented SEMS endpoint (`SaveRemoteControlInverter`), so keep the request format intact and let `_make_control_api_call()` handle retries.

## Developer workflows
- Linting (from README):
  - `ruff check custom_components/`
  - `ruff format --check custom_components/`
  - `mypy custom_components/ --ignore-missing-imports --python-version 3.14`
- Tests (from tests/README):
  - `python -m pytest tests/ -v`
  - In HA core repo workspaces, add `--confcutdir=config/goodwe-sems-home-assistant`.
- For any code change, run the narrowest relevant validation before wrapping up: format if needed, run `ruff check`, and run the most relevant tests for the touched area. Use the targeted test file(s) first, then expand only if necessary.
- Make sure all log messages are redacted of sensitive info (e.g., no email addresses, serial numbers, or API tokens in logs).
- When discovering a new SEMS or SEMS+ endpoint or response shape, capture a
  sanitized response in [api_examples/](../api_examples/), add the endpoint and
  field mapping to its README, and add a fixture-backed regression test before
  relying on the response in integration code. Never commit credentials,
  cookies, authorization headers, signatures, tokens, station IDs, serial
  numbers, trace IDs, or personal names.
- Prefer sanitized responses captured from the real API for integration tests (../api_examples/):
  load them as fixtures and exercise the complete response-normalization and
  entity-creation path. Use hand-built mocks only for isolated error handling,
  missing-field, boundary, or otherwise hard-to-capture cases. Automated tests
  must never call the live GoodWe API or require user credentials.

## Release Workflow
- Use the [release-workflow skill](.github/skills/release-workflow/SKILL.md) when preparing HACS releases, including version bumps, tags, beta/pre-release publishing, and release notes.

## GitHub and session wrap-up
- Use the `gh` CLI or Github-MCP for GitHub issues, pull requests, comments, and replies.
- Label GitHub PRs, comments and replies as AI/Copilot-generated.

## Examples to follow
- Coordinator data shaping: `SemsDataUpdateCoordinator._async_update_data()` in [custom_components/sems/__init__.py](../custom_components/sems/__init__.py).
- Sensor definition patterns: `sensor_options_for_data()` in [custom_components/sems/sensor.py](../custom_components/sems/sensor.py).
- Switch control flow: `SemsStatusSwitch.async_turn_on/off()` in [custom_components/sems/switch.py](../custom_components/sems/switch.py).
