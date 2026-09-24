# SEMS API examples

These sanitized JSON files document response shapes observed while testing the
GoodWe SEMS and SEMS+ APIs. Credentials, tokens, trace IDs, station IDs, serial
numbers, and names are replaced with placeholders or representative values.
Legacy SEMS response examples are kept in [`legacy/`](./legacy/).

## Response reference

| File | Request | Token required | Main response fields |
| --- | --- | --- | --- |
| [`legacy/legacy_monitor_empty.json`](./legacy/legacy_monitor_empty.json) | `POST /api/v3/PowerStation/GetMonitorDetailByPowerstationId` with `powerStationId` in the JSON body | Legacy token from `Common/CrossLogin`, sent in the `token` header | `code`, `components`, `hasError`, `msg`, empty `data` |
| `web_cross_login.json` | `POST /web/sems/sems-user/api/v1/auth/cross-login` | Account credentials; returns a SEMS+ Web token | `code=00000`, regional `api`, `region`, Web token metadata |
| `browser_api_endpoints.json` | Sanitized inventory of API URLs observed in the Web UI | Web token and `X-Signature` for authenticated calls | Authentication, station, device, alarm, message, and UI-support endpoints |
| `station_flow.json` | `GET /web/sems/sems-plant/api/stations/flow?stationId=<station_id>` | SEMS+ Web token and `X-Signature` | `id`, `name`, `status`, `pSystem`, `pAc`, `consumFlag`, `refreshTime` |
| `all_status.json` | `GET /web/sems/sems-plant/api/stations/device/all-status?stationId=<station_id>` | SEMS+ Web token and `X-Signature` | `deviceDetailList`, `statusDetailList`, `snList`, `detailMap` |
| `telemetry.json` | `GET /web/sems/sems-plant/api/equipments/<sn>/telemetry?deviceType=INVERTER&pwId=<station_id>` | SEMS+ Web token and `X-Signature` | `sn`, `hTotal`, `Temperature`, `pAc`, `qAc`, `gridPF`, `Vac`, `Iac`, `Fac`, MPPT fields |
| `telecounting.json` | `GET /web/sems/sems-plant/api/equipments/<sn>/telecounting?deviceType=INVERTER&pwId=<station_id>` | SEMS+ Web token and `X-Signature` | `pAc`, `ratedPower`, `proPvStatsToday`, `proPvStatsWeek`, `proPvStatsMonth`, `proPvStatsYear`, `proPvStatsTotal` |

## Token types

The legacy monitor endpoint expects the token returned by the legacy
`/api/v3/Common/CrossLogin` login. The SEMS+ endpoints expect the token returned
by the SEMS+ Web `/web/sems/sems-user/api/v1/auth/cross-login` login. Web
requests also require an `X-Signature` header generated from the Web token and
the current timestamp.

The SEMS+ standard login and legacy login are not interchangeable with the
SEMS+ Web token. The legacy monitor response is included because it can return
HTTP 200 and success code `0` while providing no inverter data. The SEMS+ Web
endpoints provide the replacement station, device, telemetry, and energy
counter data.

## Browser capture

The SEMS+ Web UI was opened at:

```text
https://semsplus.goodwe.com/
```

After login, the UI navigated to the station detail view and returned a
successful Web login response. The response identifies the regional gateway:

```text
https://eu-gateway.semsportal.com/web/sems
```

The useful authenticated requests are:

| Purpose | Request |
| --- | --- |
| Station overview and power flow | `GET /web/sems/sems-plant/api/stations/flow?stationId=<station_id>` |
| Inverter discovery | `GET /web/sems/sems-plant/api/stations/device/all-status?stationId=<station_id>` |
| Inverter telemetry | `GET /web/sems/sems-plant/api/equipments/<sn>/telemetry?deviceType=INVERTER&pwId=<station_id>` |
| Energy counters | `GET /web/sems/sems-plant/api/equipments/<sn>/telecounting?deviceType=INVERTER&pwId=<station_id>` |
| Related storage devices | `GET /web/sems/sems-plant/api/equipments/<sn>/relatedDevices?sn=<sn>&deviceType=ENERGY_STORAGE_INTEGRATED_CABINET&pwId=<station_id>` |

The browser capture also loaded static JavaScript and CSS assets. Those files
are not useful API fixtures. Credentials, cookies, authorization headers,
signatures, and live tokens must not be stored in this directory.

The complete sanitized endpoint inventory is in
[`browser_api_endpoints.json`](./browser_api_endpoints.json). It includes
additional UI endpoints such as user information, alarm counts, station
listing, translations, and notification configuration. The endpoints required
for inverter migration remain device discovery, telemetry, telecounting, and
related-device discovery.

## Calls implemented by `SemsApi`

| Method | HTTP request | Token |
| --- | --- | --- |
| `getLoginToken` | `POST /api/v3/Common/CrossLogin` (legacy fallback) or `POST /web/sems/sems-user/api/v1/auth/cross-login` (SEMS+ login) | Legacy token or SEMS+ Web token, depending on the successful login |
| `getPowerStationIds` | `POST /PowerStation/GetPowerStationIdByOwner` | Legacy token |
| `getData` | `POST /v3/PowerStation/GetMonitorDetailByPowerstationId` with `powerStationId` | Legacy token; affected accounts can receive an empty `data` object |
| `getEnergyStorageIntegratedCabinets` | `GET /web/sems/sems-plant/api/equipments/<sn>/relatedDevices?sn=<sn>&deviceType=ENERGY_STORAGE_INTEGRATED_CABINET&pwId=<station_id>` | SEMS+ Web token |
| `getBatteryGeneralFunctions` | `POST /web/sems/sems-remote/api/v2/address/remote/getDeviceFunctionTabMenus` | SEMS+ Web token |
| `getBatteryImmediateChargingStates` | `POST /web/sems/sems-remote/api/v1/address/remote/get-cache-device-function-parameters` | SEMS+ Web token |
| `setDeviceFunctionParameters` | `POST /web/sems/sems-remote/api/v1/address/remote/setDeviceFunctionParameters` | SEMS+ Web token |
| `change_status` | `POST /PowerStation/SaveRemoteControlInverter` | Legacy token |

The `startImmediateCharging`, `stopImmediateCharging`,
`setImmediateChargingEndSoC`, and `setImmediateChargingChargingPower` methods
are convenience wrappers around `setDeviceFunctionParameters`. Their request
body selects the corresponding battery function address and value.

## Privacy

Do not add live API responses to this directory. Remove credentials, tokens,
station identifiers, serial numbers, trace IDs, and personal names before
adding or updating an example.
