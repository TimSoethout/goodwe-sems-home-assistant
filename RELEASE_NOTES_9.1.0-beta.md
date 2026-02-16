# Release Notes for v9.1.0-beta

## 🐛 Bug Fixes

### Fixed crash on empty powerflow values from SEMS API

**Issue:** The SEMS integration crashed with a `decimal.InvalidOperation` error when the API returned empty strings for powerflow values at night or when the inverter was offline.

**Affected sensors:**
- HomeKit Load (`sensor.homekit_homekit_<sn>`)
- HomeKit Battery
- HomeKit PV
- HomeKit Grid
- HomeKit Load Status

**Root cause:** 
When the inverter goes offline, the SEMS API returns empty strings for powerflow values (e.g., `'load': ''`, `'bettery': ''`, `'pv': ''`). The sensor value conversion attempted to convert these empty strings to `Decimal('')`, which raised a `decimal.InvalidOperation` exception.

**Fix:**
1. Enhanced `native_value` property to handle empty strings in the `str_clean_regex` extraction
   - When regex doesn't match (e.g., empty string), the value is now set to `None`
   - This prevents invalid Decimal conversions for all sensors
2. Updated `status_value_handler` to check for empty strings before Decimal conversion
   - Returns `None` early when value is an empty string
   - Applies to sensors with custom value handlers (Load, Battery, Load Status)

**Behavior:** 
- Sensors now display "unknown" state instead of crashing when API returns empty values
- Integration remains stable during nighttime or when inverter is offline
- No loss of functionality for valid sensor values

## 🧪 Testing

- Added comprehensive test `test_homekit_sensors_handle_empty_strings_at_night`
  - Simulates day→night transition with empty API values
  - Verifies sensors handle empty strings gracefully without crashing
  - Uses DRY helper function `_build_homekit_test_data()` for maintainability
- All 40 tests passing
- No security vulnerabilities detected (CodeQL scan)

## 📝 Technical Details

**Files changed:**
- `custom_components/sems/sensor.py`: Enhanced empty string handling
- `tests/test_sensor_entities.py`: Added comprehensive test coverage

**Commits:**
- 589de75: Refactor test to DRY - extract common test data builder
- 8d6bece: Fix status_value_handler crash on empty API values

## ⚠️ Breaking Changes

None.

## 📦 Installation

This is a **beta release** intended for testing. To install:

1. **Via HACS (recommended for testing):**
   - Go to HACS → Integrations
   - Find "GoodWe SEMS API"
   - Click on it and select "Redownload"
   - Select version `9.1.0-beta` from the dropdown
   - Restart Home Assistant

2. **Manual installation:**
   - Download the release assets
   - Copy the `custom_components/sems` folder to your Home Assistant config directory
   - Restart Home Assistant

## 🙏 Feedback

Please report any issues or feedback on the [GitHub issue tracker](https://github.com/TimSoethout/goodwe-sems-home-assistant/issues).

## 🔗 Related Issues

- Fixes: [Bug] status_value_handler crashes on empty API values at night
