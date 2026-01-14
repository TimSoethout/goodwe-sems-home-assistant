# SEMS API Tests

This directory contains comprehensive tests for the SEMS API module.

## Test Files

- `test_sems_api.py` - Main comprehensive test suite with full coverage of all SEMS API functionality
- `test_sems_api_clean.py` - Clean integration test suite with realistic JSON data structures
- `test_sensor_entities.py` - Home Assistant entity tests (config entry + entity registry)
- `fixtures.py` - Anonymized SEMS API response data for test fixtures
- `__init__.py` - Package initialization for tests
- `requirements.txt` - Test dependencies

## Running Tests

To run all tests:
```bash
python -m pytest tests/ -v
```

If you are running these tests inside the Home Assistant core repository workspace (where `/workspaces/home-assistant/pyproject.toml` exists), pytest may try to load Home Assistant's own `tests/conftest.py` and fail. In that case, run with `--confcutdir`:

```bash
python -m pytest config/goodwe-sems-home-assistant/tests/ -v --confcutdir=config/goodwe-sems-home-assistant
```

To run a specific test file:
```bash
python -m pytest tests/test_sems_api.py -v
```

To run a specific test:
```bash
python -m pytest tests/test_sems_api.py::TestSemsApi::test_get_login_token_success -v
```

## Test Coverage

The test suite covers:

### Authentication
- ✅ Successful login with valid credentials
- ✅ Failed login with invalid credentials
- ✅ Network errors during login
- ✅ Authentication test success/failure

### Data Retrieval
- ✅ Get power station IDs successfully
- ✅ Get monitoring data successfully with real JSON structure
- ✅ Handle failures gracefully (return empty data)

### Control Commands
- ✅ Successful inverter status change
- ✅ HTTP error handling with retry mechanism

### Retry Logic
- ✅ Token refresh and retry on expired tokens
- ✅ Maximum retry limits with OutOfRetries exception

### Error Handling
- ✅ Network connection errors
- ✅ HTTP status code errors
- ✅ API response validation
- ✅ Token expiration handling

## Test Architecture

The tests use `requests-mock` to mock HTTP calls, allowing for:
- Isolated testing without external dependencies
- Predictable test behavior
- Testing of error conditions
- Fast test execution

Each test follows the pattern:
1. Setup mock responses for login and API calls using anonymized SEMS JSON structures
2. Execute the API method under test
3. Assert expected results or exceptions

## Test Data

The test suite uses anonymized API response structures based on real SEMS API data:
- **Mock Power Station ID**: `12345678-1234-5678-9abc-123456789abc` (anonymized UUID)
- **Mock Inverter Serial**: `GW0000SN000TEST1` (anonymized)
- **Mock Inverter Model**: `GW0000-TEST` (anonymized)
- **Mock Location**: `Test City, Test Country` (anonymized)
- **Mock Station Name**: `Test Solar Farm` (anonymized)
- **Mock Email**: `test@example.com` (anonymized)
- **Mock Coordinates**: `longitude: 0.0, latitude: 0.0` (anonymized)
- **Mock Relation IDs**: `aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee` (anonymized)
- **Success Message**: `操作成功` (Chinese: "Operation successful")
- **Complete JSON Structure**: Includes info, kpi, inverter data, weather, and energy statistics

This ensures tests validate against the actual API response format while protecting user privacy.

## Dependencies

- `pytest` - Test framework
- `requests-mock` - HTTP request mocking
- `requests` - HTTP library (tested dependency)
