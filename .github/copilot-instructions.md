# Copilot instructions for GoodWe SEMS Home Assistant integration

## Big picture architecture
- This is a Home Assistant custom integration under custom_components/sems with two platforms: sensors and a switch (see [custom_components/sems/manifest.json](../custom_components/sems/manifest.json)).
- Config flow validates credentials and optionally fetches the first power station ID via the SEMS API (see [custom_components/sems/config_flow.py](../custom_components/sems/config_flow.py)).
- Data is pulled by a single DataUpdateCoordinator in [custom_components/sems/__init__.py](../custom_components/sems/__init__.py):
  - It calls `SemsApi.getData()` in an executor (the API client is synchronous `requests`).
  - It normalizes the SEMS payload into `SemsData` with `inverters` keyed by serial number and optional `homekit` (powerflow) data.
- Entities read from the coordinator:
  - Sensors are defined declaratively in [custom_components/sems/sensor.py](../custom_components/sems/sensor.py) via `SemsSensorType` (value-path lists into the coordinator data).
  - Switches call `SemsApi.change_status()` to issue a control command (see [custom_components/sems/switch.py](../custom_components/sems/switch.py)).

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
  - `mypy custom_components/ --ignore-missing-imports --python-version 3.13`
- Tests (from tests/README):
  - `python -m pytest tests/ -v`
  - In HA core repo workspaces, add `--confcutdir=config/goodwe-sems-home-assistant`.

## Release workflow (HACS)
- Update the semantic version in [custom_components/sems/manifest.json](../custom_components/sems/manifest.json).
- For beta releases from branches, always use the `x.x.x-beta` version format, and always mark the GitHub Release as a Pre-release.
- Create a git tag for the new version and publish a GitHub (Pre)Release for that tag (HACS uses the latest release tag as the remote version; tags alone are not enough).
- Release notes should summarize changes since the latest release (e.g., list commits since the previous tag).

## Examples to follow
- Coordinator data shaping: `SemsDataUpdateCoordinator._async_update_data()` in [custom_components/sems/__init__.py](../custom_components/sems/__init__.py).
- Sensor definition patterns: `sensor_options_for_data()` in [custom_components/sems/sensor.py](../custom_components/sems/sensor.py).
- Switch control flow: `SemsStatusSwitch.async_turn_on/off()` in [custom_components/sems/switch.py](../custom_components/sems/switch.py).
