"""Pytest configuration for the SEMS custom integration tests."""

# Load required pytest plugins explicitly.
#
# Some CI environments set `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, which prevents
# entrypoint-based plugin discovery. Explicit loading keeps fixtures like
# `hass` and `requests_mock` available everywhere.
pytest_plugins = [
    # "pytest_asyncio.plugin",
    "pytest_homeassistant_custom_component.plugins",
    # "requests_mock.contrib._pytest_plugin",
]
