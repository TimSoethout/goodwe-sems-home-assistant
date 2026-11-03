# Agent instructions

## Repository-specific rules

- Ground API parsing, coordinator, and entity changes in sanitized captures under `api_examples/`; read `api_examples/README.md` first.
- For an uncovered response, add a sanitized capture, document it in `api_examples/README.md` and `index.json`, and test the captured fixture. Never call the live API in tests.
- Use mocks for errors, boundaries, missing fields, or responses that cannot be captured; never change a capture just to match the code.
- Use `GOODWE_SPELLING` in `custom_components/sems/const.py` for SEMS misspellings such as `homKit` and `tempperature`.
- `SemsApi` uses synchronous `requests`; call it via `hass.async_add_executor_job()`. Preserve retry handling and remote-control request payloads.
- Define sensors in `sensor_options_for_data()` in `sensor.py` with `value_path`; use `empty_value` for values that should disable an entity.
- Use `device_info_for_inverter()` for inverter grouping and preserve `_migrate_to_new_unique_id()` when changing sensor IDs.
- Redact credentials, tokens, cookies, signatures, station IDs, serial numbers, trace IDs, precise locations, and personal names from logs and committed examples.
- Review integration changes against Home Assistant best practices and Integration Quality Scale rules. When `.ha-core/` exists, read its `AGENTS.md` and `ha-integration-knowledge` skill; use `ha-review` for code reviews when available.
- Use GitHub suggestions where useful in reviews, and label GitHub PRs, comments, and replies as AI/Copilot-generated.
- Use Conventional Commits; mark breaking changes with `!` or a `BREAKING CHANGE:` footer.

## Adding a sensor

1. Confirm the value and units in a real sanitized capture; add and index a capture if needed.
2. Add its `value_path` and metadata in `custom_components/sems/sensor.py`; set `empty_value` when applicable.
3. Add or update a fixture-backed test in `tests/` and update translations if user-facing text changes.

## Maintenance matrix

| Change | Also update |
|---|---|
| API response or mapping | `api_examples/README.md`, `api_examples/index.json` for new captures, the relevant fixture-backed test, and the normalization or entity code |
| Sensor or device entity | `custom_components/sems/sensor.py` or the relevant platform, the corresponding `tests/` coverage, and translations when text changes |
| Authentication or reauthentication | `custom_components/sems/config_flow.py`, `custom_components/sems/sems_api.py`, `tests/test_config_flow.py`, and `tests/test_sems_api_session.py` |
| Release version or user-visible changes | `custom_components/sems/manifest.json` and `RELEASE_NOTES.md`; consult `.github/skills/release/SKILL.md` when preparing a release |

`README.md` is the user and development guide; `api_examples/README.md` documents captured API evidence. `RELEASE_NOTES.md` is the release history; do not create a second changelog. `ARCHITECTURE_PLAN.md` and `TODO.md` track architecture and follow-up work. There is no separate documentation site.

## Done means

- `pytest tests/ --cov=custom_components.sems --cov-report=xml --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=80 --junitxml=./junit.xml` passes.
- `ruff check custom_components/` passes.
- `ruff format --check custom_components/` passes.
- `mypy custom_components/ --ignore-missing-imports --python-version 3.14` passes.
- Any behavior change has a test that fails against the old behavior.

## Never merges without a human

A person has to have **read this diff** before it lands. Telling an agent "merge it when you're done" is approving a goal, not this change — so it does not count for anything on this list. Everywhere else it counts fine.

- Any change to `custom_components/sems/config_flow.py`, `custom_components/sems/sems_api.py`, or `custom_components/sems/diagnostics.py` (credential, authentication, and redaction paths).
- Any change to `custom_components/sems/switch.py` or `custom_components/sems/ev_charger.py` (remote control of inverter or charger hardware).
- Any change to `custom_components/sems/manifest.json`, `RELEASE_NOTES.md`, `.github/workflows/stable-release.yml`, `.github/workflows/release-assets.yml`, `.github/scripts/publish_stable_release.py`, or `.github/scripts/upload_release_asset.py` (release publication paths).
