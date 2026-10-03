# GoodWe SEMS integration architecture

This document describes the current integration architecture and the
evidence-backed constraints for future changes. Actionable, unfinished work is
tracked in [`TODO.md`](./TODO.md). The sanitized captures under
[`api_examples/`](./api_examples/) are the source of truth for API response
shapes; endpoint behavior can vary by account, region, station, and device.

## Scope and status

The integration connects Home Assistant config entries to GoodWe SEMS/SEMS+
stations. It uses SEMS+ Web for station discovery and normal monitoring. The
legacy monitor endpoint is not part of the live coordinator data path.

Legacy authentication and control paths remain compatibility mechanisms. Do
not remove them until account, region, and device coverage is verified. The
current user-facing setup and control behavior is documented in
[`README.md`](./README.md).

## Runtime architecture

1. **Config flow** authenticates and discovers station IDs. Each selected
   station is represented by its own Home Assistant config entry. Entries for
   the same account share one API client and session. The polling interval is
   configured per account (60-3600 seconds) and applies to running coordinators
   without reloading entries. Reauthentication is password-only and updates
   all station entries for that account.
2. **`SemsApi`** performs synchronous `requests` calls. Home Assistant calls
   it through the executor so network I/O does not block the event loop.
3. **`SemsDataUpdateCoordinator`** refreshes one station on its configured
   scan interval. It converts the API response to `SemsData`, indexing
   inverter-like devices by serial number and retaining optional battery,
   immediate-charging, HomeKit/power-flow, EV-charger, currency, and source
   availability data.
4. **Sensor and switch platforms** consume coordinator data. Sensors are
   declared with value paths; controls call `SemsApi` and request a coordinator
   refresh after a successful command.

The SEMS+ Web adapter deliberately builds the legacy-compatible response
envelope (`inverter[].invert_full`, power-flow, and statistics keys) so
existing entity definitions and unique IDs can be retained while API data is
normalized. Device identity and entity IDs must remain stable across API
changes; use the existing device and unique-ID migration helpers.

## Authentication and request policy

- SEMS+ Web login returns a regional API base. Use that base rather than
  hardcoding a regional gateway.
- SEMS+ Web calls use their own token profile and request signature. Do not
  interchange Web, SEMS+ standard-login, and legacy tokens.
- Initial authentication probes SEMS+ Web first. If it fails,
  `getLoginToken()` tries the SEMS+ standard and legacy modes with the
  previously successful mode preferred on subsequent attempts. Retain these
  compatibility fallbacks because some accounts or permissions do not behave
  uniformly. A successful login does not imply access to every station or
  endpoint.
- Treat HTTP status, GoodWe response code, and usable response data as
  separate success checks. In particular, HTTP 200 with an empty monitor
  response is not useful inverter data.
- Preserve distinct authorization, permission, and rate-limit outcomes.
  `100025` is an access/operation-rights failure, not proof of an expired
  credential. Do not retry rate limiting (`GY0429`) as if it were an
  authentication failure.
- Bound token renewal and request retries. Surface the final failure rather
  than hiding it behind empty-success data or a retry loop.
- The account-shared client serializes authentication, limits concurrent
  requests, and uses a bounded cooldown after repeated failures. Its Web
  response cache is synchronized and pruned so concurrent station refreshes
  cannot race cache updates or grow date-keyed entries without bound.
- Prefer bounded HTTPS polling. No supported third-party push/WebSocket
  contract has been established.

## Monitoring data flow

For a station refresh, the Web adapter uses the captured SEMS+ contracts to:

1. Discover station devices with
   `GET /sems-plant/api/stations/device/all-status`.
2. Fetch per-device `telemetry` and `telecounting` using the discovered serial
   number and actual `deviceType`.
3. Fetch station flow independently of smart-meter discovery.
4. For supported storage devices, discover related cabinets and enrich them
   with separate `BAT_SYS` telemetry. Battery enrichment is optional and must
   not make valid inverter data unavailable.
5. Fetch station statistics for supported chart and total fields. Optional
   data must remain absent when the endpoint or field is unavailable.

Supported discovered device types include inverter-like devices, smart
meters, battery racks, dongles, and EV chargers. EV chargers are modeled as
separate devices. Only device types with a defined entity mapping should
create those entities; a dongle is not an inverter. The normalizer should
preserve the reported device type for follow-up API calls.

Station statistics use the observed request/response contract in the hybrid
fixtures: local timestamp boundaries are inclusive, `total` is rejected, and
multi-year lifetime values require supported year-by-year requests. Treat
station-production response parsing as unverified until a sanitized response
fixture exists.

## Normalized data and entity contracts

- Keep the coordinator's `SemsData` shape: inverter data keyed by serial
  number, with optional batteries, immediate-charging state, HomeKit data,
  EV-charger data, source availability, and currency. The inverter mapping may
  be empty when power-flow data is available; a response with neither
  supported inverter data nor HomeKit power-flow data is still a failure.
- Add sensors through `sensor_options_for_data()` and explicit value paths.
  Preserve existing names, units, unique IDs, legacy aliases, and migrations.
- Use `device_info_for_inverter()` for consistent device grouping.
- HomeKit/power-flow devices and unique IDs are scoped to their station.
  Migration changes the registry identifiers while preserving entity IDs and
  recorder history.
- Expose a value only when a supported field is actually present. Do not
  fabricate zeroes for missing telemetry or create healthy battery state from
  cabinet presence alone.
- Convert units only when confirmed by a captured response. For example,
  inverter active power reported in kW is normalized to W where the existing
  entity contract requires W; energy counters and chart values require their
  own verified unit handling.
- Do not infer energy from instantaneous power. Do not silently apply
  `abs()` or reverse import/export or battery-flow signs.
- Retain established legacy spellings such as `homKit`, `tempperature`,
  `energeStatisticsCharts`, and `energeStatisticsTotals` through constants or
  explicit normalization aliases.

The hybrid fixtures establish these sign conventions for the captured
station/device contract: station-flow `pGrid` is positive for export and
negative for import; `pBat` is positive for discharge and negative for charge;
`pSystem` is PV input, while hybrid inverter `pAc` can include battery
discharge. Do not generalize these findings to unrepresented models without
additional evidence.

## Controls

- Inverter start/stop uses the SEMS+ Web remote-control API when the account
  has permission, with legacy control retained as a compatibility fallback.
  Do not create the Inverter Control switch for dongles or battery racks.
- Battery immediate charging is a separate operation from stopping inverter
  generation. Continue using the captured function metadata and endpoints;
  do not conflate the two controls.
- EV-charger controls use charger-specific SEMS+ endpoints and permissions;
  keep them separate from inverter and battery controls.
- Run blocking control calls through the coordinator's executor path. A
  rejected account credential starts reauthentication; permission failures do
  not.
- Successful authentication does not imply write permission. Report control
  failures with useful endpoint/device context without exposing credentials,
  tokens, or private identifiers in logs.

## Diagnostics

Config-entry diagnostics redact credentials, account/station identifiers,
serials, names, and model metadata. Replace serials recursively before
redaction so they are also hidden when used as dictionary keys.

## API evidence and privacy

Follow the capture, sanitization, and fixture-testing workflow in
[`api_examples/README.md`](./api_examples/README.md). Never commit raw
browser/HAR captures or credentials, tokens, or identifying data. Treat
community and legacy API documentation as context, not evidence of current
SEMS+ behavior.

## Related references

- Community API limitations: [ioBroker.goodwe-sems](https://github.com/bueste/ioBroker.goodwe-sems#api-origin-and-limitations-please-read)
- Migration and compatibility context: [issue #217](https://github.com/TimSoethout/goodwe-sems-home-assistant/issues/217) and [issue #219](https://github.com/TimSoethout/goodwe-sems-home-assistant/issues/219)
