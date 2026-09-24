# Release notes

## 11.5.0-beta - 2026-09-24

## Additional SEMS+ entity recovery

This beta builds on the SEMS+ Web fallback and restores more entities for
installations where the legacy monitor endpoint returns empty data.

### Working with SEMS+ Web

- Battery and BAT_SYS telemetry for supported storage cabinets and store
  devices, including state of charge, state of health, power, voltage,
  current, temperature, and charge/discharge limits.
- Battery daily and lifetime charge/discharge counters when reported.
- Optional station day, month, and historical year energy statistics for
  production, consumption, grid import/export, battery charge/discharge, and
  self-consumption.
- Cached statistics requests with defensive parsing so unavailable or
  malformed historical data does not break coordinator updates.

### Still limited

- Battery/BMS availability depends on the installation exposing a related
  storage device and the corresponding BAT_SYS factors.
- Station statistics depend on the SEMS+ Web statistics endpoint being
  available for the account; no legacy statistics fallback is added.
- Inverter switching and immediate battery-charging controls still use their
  existing control endpoints.

## 11.4.0-beta - 2026-09-24

## SEMS+ Web entity recovery

This release promotes the SEMS+ Web fallback after the legacy monitor endpoint
became unreliable or returned empty data.

### Working with SEMS+ Web

- Inverter discovery, status, live power, runtime, temperature, grid
  measurements, MPPT values, and PV energy counters when those fields are
  reported by the Web API.
- Station-flow HomeKit PV, grid, and load power entities.
- Smart-meter discovery and total power.
- Smart-meter phase A/B/C power, voltage, and current entities.
- Smart-meter daily and lifetime grid import/export energy entities.
- Separate Web authentication/session handling and recovery after legacy token
  renewal.

The entity mappings are based on sanitized real captures in
`api_examples/station_flow_import.json`,
`api_examples/smart_meter_telemetry.json`, and
`api_examples/smart_meter_telecounting.json`.

### Still limited

- Battery and BMS entities are not fully restored by the smart-meter fallback;
  they require the separate SEMS+ battery/device APIs and device-specific
  captures.
- Per-inverter legacy meter and battery charge/discharge fields are only
  available when the corresponding SEMS+ factors are reported.
- Inverter switching and immediate battery-charging controls still use their
  existing control endpoints and are not replaced by the station-flow
  fallback.

### Contributors

- [@TimSoethout](https://github.com/TimSoethout) - integration changes and
  release preparation.
- [@DingoDan21](https://github.com/DingoDan21) - sanitized SEMS+ smart-meter,
  station-flow, telemetry, and telecounting API captures and validation.

## 11.3.0-beta - 2026-09-24

## What's changed

- Match the SEMS+ Web login contract with the Web client identity, signature, browser User-Agent, Origin, and Referer headers.
- Pair each API endpoint with its required token type and improve authentication error diagnostics.
- Refresh the SEMS+ Web session after a legacy token renewal to avoid transient C0602 discovery failures.
- Treat inverter status 5 (Normal) as an active inverter switch state.
- Add regression coverage for endpoint authentication, token refresh, error reporting, and status handling.

### Contributors

- [@TimSoethout](https://github.com/TimSoethout) - code and release preparation.

## 11.2.0-beta - 2026-09-24

## Beta testing: SEMS+ migration improvements

- Supports SEMS+ cabinet device discovery and device-type-specific telemetry requests.
- Maps SEMS+ three-phase voltage telemetry.
- Adds redacted response logging to help collect sanitized API fixtures.
- Uses sanitized real API responses in regression coverage for supported response shapes.

Please test with SEMS+ cabinet/all-in-one installations and report the device type, region, and sanitized response data when values remain missing. Do not share credentials, tokens, station IDs, serial numbers, or personal names.

## 11.1.0 - 2026-09-24

## Fixes

- Make SEMS legacy chart energy normalization capacity-aware for Wh values reported as kWh.
- Preserve legitimate large kWh values and cumulative totals.
- Add debug logging when chart values are normalized.
- Map active SEMS+ inverter status code 5 to Normal.
- Organize legacy API response examples under the legacy folder.

This release addresses the energy spike reported in issue #228. Please update and reopen the issue if the incorrect energy jump persists.

## 11.1.0-beta - 2026-09-24

## Beta testing: SEMS+ cabinet device support

- Accepts `ENERGY_STORAGE_INTEGRATED_CABINET` devices during SEMS+ discovery.
- Preserves each discovered device type for telemetry and telecounting requests.
- Adds redacted SEMS+ response payloads to debug logging to help collect fixtures for unsupported device types and fields.
- Includes regression coverage for cabinet discovery and device-type request URLs.

Please test this beta with all-in-one/cabinet installations and report:

- whether setup succeeds when no `INVERTER` device is returned;
- whether PV, AC, frequency, voltage, and energy entities populate;
- the device type and region if values remain missing;
- sanitized debug response data, with credentials, tokens, station IDs, serial numbers, and personal names removed.

## 11.0.0 - 2026-09-23

## GoodWe SEMS API migration

This release adds the SEMS+ Web API migration and fallback behavior for inverter discovery, telemetry, and energy counters. It also improves handling of incomplete authentication and legacy monitor responses, and includes additional energy, PV, grid, and optional battery entities where the API provides those values.

## Important API change

GoodWe changed the SEMS API behavior on September 23, 2026. As a result, older integration versions may no longer be able to authenticate or retrieve inverter data. Those versions appear to be broadly unusable for affected accounts. This stable release promotes the SEMS+ migration from beta in the hope of restoring service for as many affected users as possible.

If your installation stopped working after the GoodWe API change, upgrade to 11.0.0 and reload or restart Home Assistant. If the issue persists, please report it in the active tracking issue: https://github.com/TimSoethout/goodwe-sems-home-assistant/issues/219.

## Validation

- 68 focused tests passed
- Ruff lint and format checks passed
- Release asset is generated automatically by the release workflow

## HomeKit testing needed

HomeKit-only and meter-only GoodWe installations have not been fully verified with this release. If you use HomeKit entities, please test 11.0.0 and report whether they are created and update correctly, including sanitized diagnostics if they do not.


## 11.0.0-beta - 2026-09-23

## What's Changed
* Add GitHub funding metadata from existing README sponsorship links by @TimSoethout with @Copilot in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/226
* Add browser User-Agent to SEMS+ API requests by @TimSoethout with @Copilot in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/218
* Harden SEMS+ migration response handling by @TimSoethout in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/220
* Add SEMS+ Web API client and parsers by @TimSoethout in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/221
* Enable conservative SEMS+ inverter fallback by @TimSoethout in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/222
* Add SEMS+ enrichment and evidence-backed fields by @TimSoethout in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/223
* Isolate optional BAT_SYS telemetry by @TimSoethout in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/224
* Cover SEMS+ energy counter mappings by @TimSoethout in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/225


**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/10.6.1...11.0.0-beta

## 10.6.4-beta - 2026-09-19

## What's changed

- Prefer the SEMS+ web-login token after fallback recovery so subsequent token renewals use the working authentication mode.
- Add regression coverage for web-login preference during renewal.

## 10.6.3-beta - 2026-09-18

## What's changed

- Add a SEMS+ web-login fallback when the new authentication endpoint fails.
- Add regression coverage for authentication fallback behavior and simplify related test fixtures.

## 10.6.2-beta - 2026-09-05

### Changes
- Add SEMS+ power-flow fallback for missing HomeKit load and grid values, including HK1000 support.
- Avoid logging battery function retrieval when no battery cabinets are present.

## 10.6.1 - 2026-09-04

## What's Changed
- Fixed battery feature handling and presence checks for installations without batteries.
- Added retry coverage for immediate-charging controls.
- Simplified battery number entities and authentication probe handling.

## 10.6.0-beta - 2026-09-04

## What's Changed
- Added battery feature handling and presence checks with retries for control operations.
- Better guards around the new battery features, which broke version 10.5.0 for users without batteries.
- Added coverage for immediate-charging retry behavior.

## 10.5.0 - 2026-09-02

User-visible changes since 10.4.0:

- Added number and switch controls for immediate battery charging through SEMS+. (Thanks @F21)
- Improved login error logging by recording the attempted authentication methods.
EDIT: demoted to BETA release due to many issues.

## 10.4.0 - 2026-09-01

## Changed
- New automatic power station discovery capability. (I only have a single inverter, so please test if you have more, and/or homekit.)
- Updated integration configuration instructions.
- Removed the outdated Portuguese README.

## 10.4.0-beta - 2026-07-31

Beta release for the new automatic power station discovery capability. This release improves setup experience by automatically discovering the first power station during configuration and includes related maintenance and documentation updates.

I only have a single inverter, so please test if you have more, and/or homekit.

## 10.3.0 - 2026-06-17

## What's Changed
* Add unexposed energy statistics and per-inverter sensors by @DJCallyman in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/186
* New Goodwe logo's
* Legacy HomeKit Load sensor marked with `(legacy)` to indicate difference with non-legacy version.

## New Contributors
* @DJCallyman made their first contribution in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/186

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/10.1.0...10.3.0

## 10.2.0-beta - 2026-06-11

## What's Changed
* Add unexposed energy statistics and per-inverter sensors by @DJCallyman in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/186

## New Contributors
* @DJCallyman made their first contribution in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/186

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/10.1.0...10.2.0-beta

## 10.1.0 - 2026-05-31

# Release 10.1.0

Prepared release notes (commits since previous tag):

- Release: bump version to 10.1.0 (718f272)
- Normalize SEMS `sw_version` to string for HA 2026.12 compatibility (#200) (34f4eb5)

## 10.0.4 - 2026-05-10

## What's changed
- Fixed SEMS+ login payload validation for error 100001 scenarios (#193).
- Improved sensitive-data redaction logic in logs, including better handling of numeric values and dataclass objects.

## Notes
- Stable release (not a pre-release).

## 10.0.3 - 2026-05-08

## 10.0.3
## Summary
Beta release from branch feature/sems-plus-login with SEMS+ authentication updates, API hardening, and lint cleanup.

## Changes since 9.1.1
- Add SEMS+ login support
- Update SEMS API login URLs for the new authentication flow
- Improve API error handling for login and request failures
- Handle API rate limiting to reduce temporary failures
- Refactor authentication flow for clarity and maintainability
- Improve type annotations in authentication code paths
- Fix Ruff UP035 import modernization (Callable from collections.abc)
- Redacting of sensitive information in log messages

## Included commits
- Release 10.0.2-beta
- Fix Ruff UP035 Callable import
- Release 10.0.1-beta
- Refactor SEMS API authentication flow and enhance type annotations for clarity
- Update SEMS API login URLs and enhance error handling for new login flow
- Add SEMS+ login support and handle rate limiting in API calls

## Notes
- This is a prerelease intended for validation of the SEMS+ login path before stable release
- Please report login or API issues via GitHub Issues with secrets removed from logs

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/9.1.1...10.0.3

## 10.0.3-beta - 2026-04-26

## Summary
Beta release from branch feature/sems-plus-login with SEMS+ authentication updates, API hardening, and lint cleanup.

## Changes since 9.1.1
- Add SEMS+ login support
- Update SEMS API login URLs for the new authentication flow
- Improve API error handling for login and request failures
- Handle API rate limiting to reduce temporary failures
- Refactor authentication flow for clarity and maintainability
- Improve type annotations in authentication code paths
- Fix Ruff UP035 import modernization (Callable from collections.abc)

## Included commits
- Release 10.0.2-beta
- Fix Ruff UP035 Callable import
- Release 10.0.1-beta
- Refactor SEMS API authentication flow and enhance type annotations for clarity
- Update SEMS API login URLs and enhance error handling for new login flow
- Add SEMS+ login support and handle rate limiting in API calls

## Notes
- This is a prerelease intended for validation of the SEMS+ login path before stable release
- Please report login or API issues via GitHub Issues with secrets removed from logs

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/master...10.0.3-beta

## 10.0.2-beta - 2026-04-26

## Summary
Beta release from branch feature/sems-plus-login with SEMS+ authentication updates, API hardening, and lint cleanup.

## Changes since 9.1.1
- Add SEMS+ login support
- Update SEMS API login URLs for the new authentication flow
- Improve API error handling for login and request failures
- Handle API rate limiting to reduce temporary failures
- Refactor authentication flow for clarity and maintainability
- Improve type annotations in authentication code paths
- Fix Ruff UP035 import modernization (Callable from collections.abc)

## Included commits
- Release 10.0.2-beta
- Fix Ruff UP035 Callable import
- Release 10.0.1-beta
- Refactor SEMS API authentication flow and enhance type annotations for clarity
- Update SEMS API login URLs and enhance error handling for new login flow
- Add SEMS+ login support and handle rate limiting in API calls

## Notes
- This is a prerelease intended for validation of the SEMS+ login path before stable release
- Please report login or API issues via GitHub Issues with secrets removed from logs

## 10.0.0-beta - 2026-02-28

- Add EV charger sensor support based on evCharge field from power station API\n- Fix tests\n- Fix mypy linting errors

Test version for @smh51.

## 9.1.2-beta - 2026-02-28

## Summary
Beta release from branch fix/multiple-homekit.

Warning: Unfinished FIX release. Could make you loose HomeKit historical data.

## Changes since 9.1.1-beta
- fix tests
- restore multiple HomeKit branch behavior


## 9.1.1 - 2026-03-05

## 9.1.1
### Fixes
- Fix crash on empty powerflow values from SEMS API (#177)
- Fix import/export sensor data paths and add comprehensive test coverage (#167)

### Improvements
- Restore legacy powerflow and homekit unique id behavior to reduce entity churn
- Remove "powerflow" from homekit sensor value paths and add tests for powerflow sensors
- Consolidate API tests and resolve mypy issues

## 9.1.1-beta - 2026-02-16

## Summary
Beta release with powerflow robustness fixes.

## Changes since 9.1.0-beta
- Fix crash on empty powerflow values from SEMS API (#177).
- Restore legacy powerflow behaviour.


## 9.1.0-beta - 2026-02-09

## Summary
Minor beta release with HomeKit/powerflow unique-id migration work.

## Changes since 9.0.0-beta
- Migrate powerflow unique IDs to legacy homekit SN IDs.
- Add/adjust migration test coverage.


## 9.0.0-beta - 2026-02-09

## Summary
Major beta release with HomeKit/powerflow adjustments and test consolidation.

## Changes since 8.2.1-beta
- Restore legacy HomeKit load sensor ID and old unique IDs.
- Add end-to-end powerflow sensor test coverage.
- Consolidate SEMS API tests into the main suite.
- Update Copilot release instructions and README download badges.
- Remove "powerflow" prefix from HomeKit sensor value paths (#168).


## 8.2.1-beta - 2026-02-07

## Summary
Beta release containing the latest fixes and translations since 8.2.0.

## Changes since 8.2.0
- Fix import/export sensor data paths and add comprehensive test coverage (#167).
- Add Spanish translations.
- Update Copilot instructions.


## 8.2.0 - 2026-02-06

## What's Changed
* Feature/separate entities by @TimSoethout in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/151

**WARNING** Very big revamp. So expect **Breaking Changes**, potentially for HomeKit users.
Make sure you have backups if testing, so you can recover. Feedback is appreciated though.

- Separate entities instead of storing everything in attributes, in proper HA style.
- Should keep history in Power and Energy entities.
- Finally Unit tests, Proper CI, Linting
- The inverter control switch device class changed from `OUTLET` to `SWITCH`; If you have automations/dashboards that filter by device class `outlet`, update them to use device class `switch`

Please try it out. I only tested it with my own Inverter, not with HomeKit, although tests for HomeKit were added.
Let me know if this works, and what you're missing.

Based on major contributions of @L-four and @davidchristen. Thanks a lot!

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/7.4.1...8.2.0

Small fix in version number.

## 8.2.0-beta - 2026-02-01

**WARNING** Very big revamp. So expect **Breaking Changes**, especially for HomeKit users.
Make sure you have backups if testing, so you can recover, or wait for normal release. Feedback is appreciated though.

- Separate entities instead of storing everything in attributes, in proper HA style.
- Should keep history in Power and Energy entities.
- Finally Unit tests, Proper CI, Linting
- The inverter control switch device class changed from `OUTLET` to `SWITCH`; If you have automations/dashboards that filter by device class `outlet`, update them to use device class `switch`

Please try it out. I only tested it with my own Inverter, not with HomeKit.
Let me know if this works, and what you're missing.

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/7.4.1...8.2.0-beta

## 8.1.0-beta - 2026-01-14

- fixes for HomeKit
- unit tests for entities


**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/8.0.0-beta...8.1.0-beta

## 8.0.0-beta - 2026-01-09

**WARNING** Very big revamp. So expect **Breaking Changes**, especially for HomeKit users.
Make sure you have backups if testing, so you can recover, or wait for normal release. Feedback is appreciated though.

- Separate entities instead of storing everything in attributes, in proper HA style.
- Should keep history in Power and Energy entities.

Please try it out. I only tested it with my own Inverter, not with HomeKit.
Let me know if this works, and what you're missing.

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/7.5.0-beta...8.0.0-beta

## 7.5.0-beta - 2025-09-08

Revamp of sems_api.py: DRY, robuster

Vibed-coded tests run by Github Actions.

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/7.4.1...7.5.0-beta

## 7.4.1 - 2025-09-08

Fixed invalid authentication due to SEMS API change.

(Sems portal started returning Chinese instead of English. :))

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/7.4.0...7.4.1

## 7.4.0 - 2025-07-01

## What's Changed
* fix homekit hopefully, release 7.4.0 by @TimSoethout in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/134
The issue seems to be that the wrong Sensor instances were created for HomeKit devices.
I now added more debug logging and disabled creation of SemsSensor, SemsStatisticsSensor and SemsStatusSwitch for HomeKit devices.


**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/7.2.0...7.4.0

## 7.4.0-beta - 2025-06-23

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/7.3.0-beta...7.4.0-beta

Fix HomeKit sensors, hopefully

## 7.3.0-beta - 2025-06-20

debug logging

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/v7.2.0-beta...7.3.0-beta

## 7.2.0 - 2025-06-19

## What's Changed
* Update README.md template to new ha version by @HermeZ23 in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/127
* Update README.md by @VuurVos in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/129
* 7.2.0 beta release by @TimSoethout in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/132
Includes:

[v7.2.0-beta](https://github.com/TimSoethout/goodwe-sems-home-assistant/releases/tag/v7.2.0-beta) Pre-release

Full Changelog: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/v7.1.0-beta...v7.2.0-beta

Fetch power station id during config flow

[v7.1.0-beta](https://github.com/TimSoethout/goodwe-sems-home-assistant/releases/tag/v7.1.0-beta) Pre-release

Full Changelog: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/v7.0.0-beta...v7.1.0-beta

entity naming and unique id migration

[v7.0.0-beta](https://github.com/TimSoethout/goodwe-sems-home-assistant/releases/tag/v7.0.0-beta) Pre-release

Full Changelog: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/6.1.1...v7.0.0-beta

WIP, should be feature compatible with 6.1.1 though, but now:

    using data coordinators
    major refactoring of code.
    pre-work for having all attributes as entities in the proper devices

## New Contributors
* @HermeZ23 made their first contribution in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/127
* @VuurVos made their first contribution in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/129

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/6.1.1...7.2.0

## v7.2.0-beta - 2025-04-04

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/v7.1.0-beta...v7.2.0-beta

Fetch power station id during config flow

## v7.1.0-beta - 2025-04-03

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/v7.0.0-beta...v7.1.0-beta

entity naming and unique id migration

## v7.0.0-beta - 2025-03-31

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/6.1.1...v7.0.0-beta

WIP, should be feature compatible with 6.1.1 though, but now:
- using data coordinators
- major refactoring of code.
- pre-work for having all attributes as entities in the proper devices

## 6.1.1 - 2024-10-31

Use zip to release, which should result in HACS showing number of downloads. :D

## What's Changed
* Download counters by @TimSoethout in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/117


**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/6.1.0...6.1.1

## 6.1.0 - 2024-10-09

## What's Changed
* Support Goodwe Power Meter (Issue #92) by @IsaacInsoll in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/115

## New Contributors
* @IsaacInsoll made their first contribution in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/115

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/6.0.0...6.1.0

## 6.0.0 - 2024-09-15

## What's Changed
* Fix deprecated hass.config_entries.async_forward_entry_setup by @markruys in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/113


**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/5.0.0...6.0.0

## 5.0.0 - 2024-03-20

## What's Changed
* Adding power control by @cthulu in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/103

## New Contributors
* @cthulu made their first contribution in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/103

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/4.0.0...5.0.0

## 4.0.0 - 2024-03-11

## What's Changed
* Use new constants by @markruys in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/102

## New Contributors
* @markruys made their first contribution in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/102

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/3.7.4...4.0.0

## 3.7.4 - 2024-01-18

## What's Changed
* Create pt.json by @jacmatias in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/97
* Create README_PT.md by @jacmatias in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/98

## New Contributors
* @jacmatias made their first contribution in https://github.com/TimSoethout/goodwe-sems-home-assistant/pull/97

**Full Changelog**: https://github.com/TimSoethout/goodwe-sems-home-assistant/compare/3.7.3...3.7.4

## 3.7.3 - 2023-05-24

Thanks to @darek-margas .

## 3.7.2 - 2022-10-10

Thanks to @Denifia

## 3.7.1 - 2022-08-17

Added "all_time_generation" for home kit from `kpi` section. Thanks @philipbrennan .

## 3.7.0 - 2022-06-13



## 3.7.0-beta - 2021-12-20

 Make sure API url from authentication reponse is used


## 3.6.0-beta - 2021-11-24

Extra HomeKit sensors, thx @darek-margas

## 3.5.0-beta - 2021-10-31

 Added powerflow sensor #58 by @Ads5555

Please test. :)
Thanks @Ads5555

## 3.4.0 - 2021-09-05

Support HA 2021.9.x new longterm statistics format `total_increasing`

Closes #49 , #50 , #51

## 3.3.1 - 2021-08-21

Defensive programming when determining model type, to support older models (where model type is `null`).

## 3.3.1-beta - 2021-08-20

Defensive programming when fetching model type, to support older versions.

## 3.3.0 - 2021-08-06

- Added HA device to group entities
- Added entity for kWh, to support HA's new energy report

## 3.3.0-beta3 - 2021-08-05



## 3.3.0-beta - 2021-08-05

Added extra sensor that should be compatible with "Long-term Statistics" and therefor the New Energy monitor feature in HA.

## 3.2.0 - 2021-04-26

Update inverterval configurable via config flow

## 3.1.1 - 2021-04-16

Small updates:
- HA version requirements
- content_in_root: false for HACS installs -- if this not works for you try removing the whole integration from HACS, restart and reinstall

## 3.1.0 - 2021-04-16

Major overhaul:
- Supports multiple inverters and plants
- HA async style integration
- HA Flow configuration

Note that entity names will change from `sensor.sem_portal` to `sensor.inverter_$NAME`

## 3.1.0-beta2 - 2021-04-14



## 3.0.0-beta2 - 2021-04-14



## 3.0.0-beta - 2021-04-14



## 2.0.0-beta - 2021-04-14

Pre-release (also to test out `hacs.json`'s `"content_in_root": true`)

## 1.0.1 - 2021-03-07

Added required `version` to manifest for HA 2021.3.0

## v2.0.0-beta - 2020-09-01

* multiple inverters
* async component

## 1.0.0 - 2020-05-28

Battle proven version for a single inverter.
