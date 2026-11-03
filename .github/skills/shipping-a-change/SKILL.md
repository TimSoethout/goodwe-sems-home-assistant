---
name: shipping-a-change
description: What to update when changing this integration and what done requires. Use before opening a pull request.
---

# Shipping a change

## Add a sensor

1. Verify the response shape and units in a real sanitized capture under `api_examples/`.
2. If the response is new, add the capture and update `api_examples/README.md` and `api_examples/index.json`.
3. Add the sensor's `value_path` and metadata to `sensor_options_for_data()` in `custom_components/sems/sensor.py`.
4. Add a fixture-backed regression test in `tests/test_sensor_entities.py`.
5. Run the relevant tests and checks below.

## When you change this, also change that

| Change | Also update |
|---|---|
| API response or mapping | `api_examples/README.md`, `api_examples/index.json` for new captures, a fixture-backed test, and normalization or entity code |
| Sensor or device entity | The relevant platform in `custom_components/sems/`, matching tests, and translations if user-facing text changes |
| Authentication or reauthentication | `config_flow.py`, `sems_api.py`, `tests/test_config_flow.py`, and `tests/test_sems_api_session.py` |
| Release version or user-visible changes | `custom_components/sems/manifest.json` and `RELEASE_NOTES.md`; consult `.github/skills/release/SKILL.md` when preparing a release |

## Done

- `pytest tests/ --cov=custom_components.sems --cov-report=xml --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=80 --junitxml=./junit.xml` passes.
- `ruff check custom_components/` passes.
- `ruff format --check custom_components/` passes.
- `mypy custom_components/ --ignore-missing-imports --python-version 3.14` passes.
- Any behavior change has a test that fails against the old behavior.
