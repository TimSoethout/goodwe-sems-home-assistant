# SEMS+ API migration proposal

Source: [issue #217 comment](https://github.com/TimSoethout/goodwe-sems-home-assistant/issues/217#issuecomment-5797721158)

Additional reference: the current
[ioBroker.goodwe-sems API limitations](https://github.com/bueste/ioBroker.goodwe-sems#api-origin-and-limitations-please-read)
documentation. It independently confirms the permanent legacy gateway gaps
and describes battery retrieval through a separate `BAT_SYS` device.

## Problem

The legacy
`/api/v3/PowerStation/GetMonitorDetailByPowerstationId` request can return
HTTP 200 with success code `0` while its `data` object is empty. A valid
SEMS+ Web login does not change that response. The integration consequently
cannot find the expected `inverter` list and setup fails.

The browser `User-Agent` header is not required for the tested account. The
following values all returned `code=00000` from the SEMS+ Web login and
successfully accessed the station-flow endpoint:

- `home-assistant-sems-api/1.0`
- `Home Assistant`
- `curl/8.0.0`
- Firefox
- Chrome
- An empty `User-Agent`

The browser-like value can still be retained as a conservative default, but
the User-Agent is not the reason the legacy monitor endpoint returns empty
data.

The same comparison was made against the authenticated Web endpoints. Both
`home-assistant-sems-api/1.0` and an empty `User-Agent` returned HTTP 200 and
`code=00000` for device discovery, telemetry, telecounting, and related-device
requests. This confirms that the User-Agent is not required by those endpoints
for the tested account either.

## Additional implementation constraints

The older migration notes contain several findings that remain relevant even
though their original fallback design is superseded:

- Treat a request as successful only when the HTTP response succeeds, the API
  code is successful (`0` or `00000`), and the response contains usable data.
  HTTP 200 alone is not sufficient.
- Keep these response classes distinguishable:
  - `100002`: authorization expired
  - `100004`: login parameter error
  - `100025`: access or operation rights failure
  - `C0602`: abnormal login
  - `GY0429`: rate limiting
- SEMS behavior can vary by account role and sharing/owner permissions. A
  successful login does not imply that every station, device, or telemetry
  endpoint is authorized.
- Re-authenticate at most once for an expired session, then surface the final
  error. Do not recursively retry or re-login for rate limiting.
- Retain the last successful login mode as an optimization, but preserve
  fallback between legacy and Web authentication when the selected mode is
  unavailable.
- There is no documented third-party WebSocket or SignalR push interface.
  Continue using bounded HTTPS polling rather than relying on the older
  `msgSocketAdr` field seen in some responses.

## Browser capture

The SEMS+ Web UI was opened at `https://semsplus.goodwe.com/` and logged into
the station detail view. The sanitized login request and response are recorded
in [`web_cross_login.json`](./web_cross_login.json).

The login response returned `code=00000` and selected the regional API base:

```text
https://eu-gateway.semsportal.com/web/sems
```

The regional gateway must be taken from the login response rather than
hardcoded. The standard SEMS+ login currently fails for the affected account
with `100004`; the legacy login can authenticate but its monitor response is
empty or can later fail with `100002` (authorization expired).

The authenticated requests relevant to the migration are:

| Purpose | Endpoint | Expected useful data |
| --- | --- | --- |
| Station overview | `GET /web/sems/sems-plant/api/stations/flow?stationId=<station_id>` | Station status, PV/AC power, consumption flag, refresh time |
| Device discovery | `GET /web/sems/sems-plant/api/stations/device/all-status?stationId=<station_id>` | Inverter serials, names, models/subtypes, status |
| Live inverter values | `GET /web/sems/sems-plant/api/equipments/<sn>/telemetry?deviceType=INVERTER&pwId=<station_id>` | System, AC, and PV factor groups |
| Energy values | `GET /web/sems/sems-plant/api/equipments/<sn>/telecounting?deviceType=INVERTER&pwId=<station_id>` | Rated power and today/week/month/year/lifetime counters |
| Storage discovery | `GET /web/sems/sems-plant/api/equipments/<sn>/relatedDevices?sn=<sn>&deviceType=ENERGY_STORAGE_INTEGRATED_CABINET&pwId=<station_id>` | Battery/storage cabinet relationships |

The UI also requests static JavaScript and CSS resources, which do not add
inverter data and are not included as fixtures. Live credentials, cookies,
authorization headers, signatures, and tokens were excluded from the capture.

The complete sanitized browser endpoint inventory is in
[`browser_api_endpoints.json`](./browser_api_endpoints.json). It includes
additional UI calls for user information, alarm counts, station listing,
translations, and notification configuration. These are not required for the
initial inverter data adapter, but the alarm-count and station-list endpoints
could support future diagnostics or automatic station discovery.

The endpoint inventory comes from the browser's resource history. It records
the URLs and their apparent UI purpose; it does not preserve live response
bodies or authentication headers. The response fixtures in this directory
remain the source of the documented field mappings.

## Proposed solution

Keep the existing login and legacy API paths for compatibility, but add a
SEMS+ Web data adapter used when the legacy response has no usable inverter
data.

### 1. Authenticate with SEMS+ Web

Use the Web login:

```text
POST https://semsplus.goodwe.com/web/sems/sems-user/api/v1/auth/cross-login
```

The request uses the existing password encoding and `semsPlusWeb` client
metadata. Store the returned Web token and regional API base separately from
the legacy token because the request headers and API base differ. Web API
requests use the Web token and an `X-Signature` generated from the request
timestamp.

### 2. Discover inverter devices

Use the authenticated Web request:

```text
GET https://<region>-gateway.semsportal.com/web/sems/sems-plant/api/stations/device/all-status?stationId=<station_id>
```

Read inverter serial numbers from:

```text
data.deviceDetailList[].statusDetailList[].snList[]
```

Use the corresponding `detailMap` entry for the inverter name, subtype,
status, and other device metadata.

### 3. Fetch per-inverter telemetry

For every discovered inverter serial number, request:

```text
GET /web/sems/sems-plant/api/equipments/<sn>/telemetry
    ?deviceType=INVERTER&pwId=<station_id>
```

The response is grouped into `system`, `ac`, and `pv` sections. Flatten the
`factors` lists by their `code` values.

Useful mappings include:

| SEMS+ field | Existing inverter field | Conversion |
| --- | --- | --- |
| `sn` | `sn` | None |
| `Temperature` | `tempperature` | Numeric value; preserve the legacy field spelling |
| `pAc` | `pac` | kW to W |
| `Vac` | `vac` | Numeric value |
| `Iac` | `iac` | Numeric value |
| `Fac` | `fac` | Numeric value |
| `gridPF` | `power_factor` | Numeric value |
| `MPPT-1:Ppv` | PV power field | kW to W |
| `MPPT-1:Vpv` | PV voltage field | Numeric value |
| `MPPT-1:Ipv` | PV current field | Numeric value |

Missing factors must remain unavailable rather than being replaced with
fabricated zero values.

### 4. Fetch energy counters

Request:

```text
GET /web/sems/sems-plant/api/equipments/<sn>/telecounting
    ?deviceType=INVERTER&pwId=<station_id>
```

Map the counter fields as follows:

| SEMS+ field | Existing inverter field |
| --- | --- |
| `proPvStatsToday` | `eday` |
| `proPvStatsMonth` | `thismonthetotle` |
| `proPvStatsTotal` | `etotal` |

The week and year counters are also available as `proPvStatsWeek` and
`proPvStatsYear` and can be retained for future entities.

### 5. Station flow and power-flow limitations

The Web station-flow endpoint is available and can provide station status,
PV/AC power, consumption direction, and refresh time. It is not a drop-in
replacement for the legacy `homeKit`/`powerflow` object: it does not provide
the existing load, grid, battery, generator, state-of-charge, or chart
statistics fields used by the HomeKit entities. Keep station-flow parsing
separate from inverter telemetry and do not populate those entities from
partial data.

### 6. Preserve the existing coordinator contract

Build the same structure currently consumed by the integration:

```text
{
  "inverter": [
    {
      "invert_full": {
        ...
      }
    }
  ]
}
```

This allows the existing entity setup and device mapping to continue working
while the source of the data changes.

## Implementation and release order

The migration should be delivered as small, independently reviewable PRs.
Each PR below leaves the existing legacy path usable and has a clear
rollback boundary.

### PR 1: Harden response classification and authentication errors

Keep the current data source and entity behavior unchanged. Add typed handling
and tests for:

- HTTP success with API failure codes
- HTTP 200 with empty or unusable `data`
- `100002`, `100004`, `100025`, `C0602`, and `GY0429`
- one re-authentication attempt for an expired session
- no re-login loop for rate limiting
- preserving the last successful login mode as an optimization

Acceptance criteria:

- Existing legacy success fixtures produce identical coordinator data.
- Empty legacy data is distinguishable from a valid empty station.
- Rate-limit and permission errors reach the coordinator with their cause.
- No Web fallback is enabled yet.

### PR 2: Add the SEMS+ Web client and response parsers

Add Web login, dynamic regional API-base handling, request signing, device
discovery, telemetry, telecounting, and the related response parsers. Use the
sanitized fixtures in this directory; do not change coordinator selection or
entity creation yet.

Acceptance criteria:

- Web login stores the returned token and regional API base separately from
  the legacy token.
- Requests use the Web token and `X-Signature`.
- `all-status`, telemetry, and telecounting fixtures map to a normalized
  inverter structure.
- Missing factors remain absent.
- Parser tests cover multiple inverters, missing factors, and non-success API
  codes.

### PR 3: Enable conservative inverter fallback

Use the Web client only when the legacy monitor response is unusable, such as
empty/missing inverter data or known legacy authorization expiry. Keep a
complete legacy result preferred and preserve existing entity IDs and
coordinator keys.

Acceptance criteria:

- Legacy accounts with complete data do not make Web requests.
- Affected accounts receive status, identity, capacity, power, runtime,
  temperature, supported PV/AC values, and available energy counters.
- Missing Web fields do not create zero-valued entities.
- Web permission or transport failures produce an actionable update error.
- Existing legacy behavior and controls remain unchanged.

### PR 4: Add station-flow enrichment

Add the Web station-flow request as an independent, optional enrichment path.
Map only the fields confirmed by the station-flow response. Do not present it
as a replacement for the legacy HomeKit/power-flow object or chart data.

Acceptance criteria:

- Station-flow failure does not remove valid inverter entities.
- Station status and station-level power values are available where supported.
- Existing HomeKit entity IDs and legacy power-flow behavior remain stable.
- Tests cover stations with and without power-flow data.

### PR 5: Add opt-in `BAT_SYS` telemetry

Discover related devices, select attached `BAT_SYS` devices, and query their
telemetry independently from inverter telemetry. Keep this feature disabled
by default until response coverage exists for the affected inverter and
battery models.

Acceptance criteria:

- Battery-less inverters continue to work without extra battery entities.
- Battery telemetry failure for one device does not fail the coordinator.
- Entities are created only for present factors.
- Existing immediate-charging controls remain unchanged.
- Tests cover battery-equipped, battery-less, and battery-request-failure cases.

### PR 6: Expand field coverage only with evidence

Add additional entities or mappings only when a captured response provides a
stable field and unit for them. Candidate areas are additional MPPTs/phases,
last-month energy, income, meter data, and legacy chart statistics.

Acceptance criteria:

- Each new field has a sanitized fixture and a unit conversion test.
- The field is omitted when unavailable for a device model.
- No speculative zero/default values are introduced.

### 6. `invert_full` and entity coverage

The current entity platforms do not use every field in the legacy
`invert_full` object. The following matrix compares the fields used by the
current inverter entities with the fields present in the tested SEMS+ Web
fixtures (`all-status`, `telemetry`, and `telecounting`).

| Current entity or function | Legacy `invert_full` fields | SEMS+ Web coverage | Result |
| --- | --- | --- | --- |
| Inverter status and switch | `status` | `all-status.status` | Available |
| Device name and model | `name`, `model_type` | `all-status.detailMap[].name`, `subtype` | Available with `subtype` mapped to `model_type` |
| Capacity | `capacity` | `telecounting.ratedPower` | Available; kW |
| Power | `pac` | `telemetry.pAc` or `telecounting.pAc` | Available; convert kW to W |
| Total hours | `hour_total` | `telemetry.hTotal` | Available |
| Temperature | `tempperature` | `telemetry.Temperature` | Available; map to the legacy spelling |
| Energy today/this month/total | `eday`, `thismonthetotle`, `etotal` | `proPvStatsToday`, `proPvStatsMonth`, `proPvStatsTotal` | Available |
| Energy last month | `lastmonthetotle` | No equivalent in tested response | Missing |
| Income today/total | `iday`, `itotal` | No equivalent in tested response | Missing |
| PV string voltage/current | `vpv1`-`vpv4`, `ipv1`-`ipv4` | `MPPT-1:Vpv`, `MPPT-1:Ipv` | String/MPPT 1 available; 2-4 missing |
| AC voltage/current/frequency | `vac1`-`vac3`, `iac1`-`iac3`, `fac1`-`fac3` | `Vac`, `Iac`, `Fac` | Phase 1 available; phases 2-3 missing |
| Battery voltage/current | `vbattery1`, `ibattery1` | No battery factors in tested telemetry | Missing |
| Grid meter power | `pmeter` | No equivalent in tested response | Missing |
| Battery charge/discharge energy | `eChargeDay`, `eDischargeDay` | No equivalent in tested response | Missing |
| Battery detail sensors | `battery_count`, `more_batterys[]` with `pbattery`, `vbattery`, `ibattery`, `soc`, `soh`, `bms_temperature`, `bms_discharge_i_max`, `bms_charge_i_max` | No battery detail data in tested inverter responses | Missing |
| Battery controls | Battery cabinet/function data used by the number and switch platforms | Requires separate battery Web calls; not part of `invert_full` telemetry | Not restored by the inverter adapter |

Consequently, a first Web adapter can restore these existing inverter entities:
status, switch status, device identity, capacity, power, total hours,
temperature, energy today, energy this month, total energy, PV MPPT 1 voltage
and current, and AC phase 1 voltage, current, and frequency. It should omit
entities whose source fields are absent rather than publish zero values.

The following existing inverter entities remain unavailable unless another
SEMS+ endpoint or device-specific response supplies the missing fields:

- Energy Last Month
- Income Today and Income Total
- PV strings/MPPTs 2-4
- AC phases 2-3
- Battery Voltage and Battery Current
- Grid Meter Power
- Battery Charge Today and Battery Discharge Today
- Per-battery power, voltage, current, SoC, SoH, BMS temperature, and BMS
  current-limit sensors
- Battery immediate-charging switch and number controls

These conclusions are based on the sanitized responses in this directory.
The Web API may expose additional factors for other inverter models; parsers
should therefore map factors by code and only create an entity when its value
is actually present.

The community reference reports that battery-capable plants expose a separate
`BAT_SYS` device through `relatedDevices`, with battery values retrieved from
that device's own `telemetry` endpoint. This is a more specific follow-up path
than treating battery fields as part of inverter telemetry. It should be
implemented as optional enrichment and isolated from the inverter update:
battery failures must not make PV and inverter entities unavailable.

## Fallback behavior

1. Try the current legacy path.
2. If the response contains a valid inverter list, retain the current behavior.
3. If the legacy response is successful but has empty or missing `data`, or
   reports authorization expiry (`100002`), authenticate with SEMS+ Web and
   use the new adapter.
4. Do not use the Web fallback for arbitrary legacy server or network errors;
   preserve the existing retry/error handling for those cases.
5. If the Web endpoints fail, raise the existing update error with a useful
   endpoint-specific log message.

Do not silently convert an authentication failure into an empty successful
response.

## Known limitations

The issue comment confirms that this compatibility path restores inverter
discovery and daily/lifetime PV counters, but does not yet restore:

- Legacy HomeKit or power-flow data
- Previous-month energy data
- All SEMS battery functions
- Full legacy chart statistics and HomeKit entities; station flow only provides
  a smaller station-level power summary
- The missing inverter entity fields listed in the coverage matrix above
- Battery telemetry until a `BAT_SYS`-specific response has been captured and
  mapped for the affected inverter models

Battery-related Web calls should remain independent enrichment calls so a
failure to retrieve battery functions does not prevent inverter telemetry from
being published.

## Validation plan

Add mocked response fixtures from `api_examples/` and test:

- Legacy response with empty `data` activates the Web fallback.
- Web device discovery returns one or multiple inverters.
- Telemetry and telecounting factors are flattened correctly.
- kW values are converted to W where required.
- Missing factors do not create invalid zero-valued entities.
- A Web endpoint failure preserves the existing retry behavior.
- Existing legacy response fixtures continue to use the legacy path.
- Legacy authorization expiry (`100002`) activates the Web fallback.
- The Web login response selects the regional gateway dynamically.
- The browser endpoint inventory remains sanitized and contains no credentials,
  tokens, cookies, or response bodies.
