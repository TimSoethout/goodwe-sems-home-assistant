# SEMS+ API migration proposal

Source: [issue #217 comment](https://github.com/TimSoethout/goodwe-sems-home-assistant/issues/217#issuecomment-5797721158)

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

### 7. `invert_full` and entity coverage

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
