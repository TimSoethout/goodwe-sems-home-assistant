---
name: security-review
description: Review GoodWe credentials, authentication, API tokens, logs, and diagnostics in the SEMS integration.
---

# Security review

## Trust boundaries in this repo

- `custom_components/sems/config_flow.py` accepts account credentials and stores them in Home Assistant config entries.
- `custom_components/sems/sems_api.py` sends credentials, handles legacy and SEMS+ Web tokens and signatures, and consumes remote API responses.
- `custom_components/sems/const.py` provides `redact_for_log()`; `custom_components/sems/diagnostics.py` redacts config-entry data and device serials before export.
- `custom_components/sems/switch.py` and `custom_components/sems/ev_charger.py` send commands that control physical equipment.
- Tests use local fixtures and mocks; they must not call GoodWe's live API or require user credentials.

## Never

- Log or commit raw passwords, tokens, cookies, signatures, station IDs, serial numbers, trace IDs, precise locations, or personal names.
- Bypass `redact_for_log()` for SEMS response data, identifiers, or token data written to logs.
- Return config-entry credentials or identifying device data unredacted from diagnostics.
- Change undocumented control payloads without evidence in sanitized captures and regression coverage.

## Before merging a change to a trust boundary

- For credential or token changes, verify the correct token type and required headers in `tests/test_sems_api_session.py`; verify login and reauthentication in `tests/test_config_flow.py`.
- For log or diagnostics changes, check `tests/test_diagnostics.py` and relevant redaction tests for passwords, tokens, station IDs, and serial numbers.
- For control commands, verify the request format against captured API evidence and test error/retry behavior without contacting the live API.
