# GoodWe SEMS API references

Checked 2026-09-23. These references are a mixture of older official
documentation and current reverse-engineered community documentation.

## Official Help and Swagger

- [GoodWe Help index](http://www.goodwe-power.com:82/Help) is still reachable
  and returns an endpoint catalog.
- [Swagger UI](http://www.goodwe-power.com:82/swagger/ui/index) is reachable,
  but the supplied operation fragment
  `PowerStationController_GetPlantDetailByPowerstationId_0` does not provide a
  reliable standalone response when fetched directly. The UI appears to
  require client-side navigation and may describe an older API generation.

The Help catalog documents older versioned controller routes, including:

- Account/user operations such as `Account/GetUser` and
  `Account/GetPermissionList`
- Power-station/plant listing and detail operations
- Device and data-logger operations
- Remote-control operations

These routes use the older `/api/{version}/...` style and should not be
assumed to work against the current SEMS+ Web gateway without testing.

## Current community reference

The most relevant current reference is the
[bueste/ioBroker.goodwe-sems repository](https://github.com/bueste/ioBroker.goodwe-sems),
particularly its
[API origin and limitations](https://github.com/bueste/ioBroker.goodwe-sems#api-origin-and-limitations-please-read)
section.

Relevant findings from its current README:

- Normal SEMS Portal accounts use undocumented portal/app HTTPS endpoints;
  GoodWe OpenAPI access is a separate organization account/API product.
- The legacy `GetMonitorDetailByPowerstationId` gateway response has permanent
  gaps: no reliable station timestamp, month-to-date generation, income, or
  currency fields.
- Power-flow data is conditional on the plant response and is not guaranteed.
- There is no documented third-party WebSocket/SignalR push interface; polling
  remains the safer approach.
- `GY0429` rate limiting has been observed and should be handled with a
  cooldown rather than immediate retries.
- Battery data is not part of the legacy monitor response. The SEMS+ Web UI
  retrieves it through a separate API: discover a related `BAT_SYS` device and
  query that device's own telemetry endpoint.
- The community battery implementation is explicitly experimental and should
  fail independently from inverter/PV telemetry.

## Relevance to this integration

The current SEMS+ migration proposal already uses the Web login, regional
gateway, station/device discovery, inverter telemetry, telecounting, and
related-device calls. The community findings support these decisions and add
two important constraints:

1. Do not expect the legacy monitor endpoint to restore month-to-date income,
   currency, or station timestamp fields.
2. Treat battery support as a separate, optional `BAT_SYS` telemetry adapter;
   do not infer battery entities from inverter telemetry alone.

The official references are useful for historical endpoint names and
controller coverage, but the live SEMS+ browser capture and sanitized fixtures
in [`custom_components/sems/api_examples/`](custom_components/sems/api_examples/)
are the authoritative sources for the current Web API behavior.