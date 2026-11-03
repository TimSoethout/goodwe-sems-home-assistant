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

For other changes, use the [maintenance matrix in `AGENTS.md`](../../../AGENTS.md#maintenance-matrix).

Before shipping, follow the completion checks in [`AGENTS.md`](../../../AGENTS.md#done-means).
