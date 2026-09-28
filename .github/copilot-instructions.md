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

## GitHub and session wrap-up
- Label GitHub comments and replies as AI/Copilot-generated.

## Releases
- Follow the [release skill](skills/release/SKILL.md) for HACS releases.
