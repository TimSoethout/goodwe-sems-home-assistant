# SEMS API examples and response captures

These sanitized JSON files document response shapes observed while testing the
GoodWe SEMS and SEMS+ APIs. Credentials, tokens, trace IDs, station IDs, serial
numbers, and names are replaced with placeholders or representative values.
The machine-readable [`index.json`](./index.json) catalogs the committed
examples, including file-backed fixtures under `tests/test-data/`, their
provenance, and known test consumers. Sanitized examples with unverified
capture context are explicitly labeled as such. Legacy SEMS response examples
are kept in [`legacy/`](./legacy/). See the repository
[architecture plan](../ARCHITECTURE_PLAN.md) and [follow-up work](../TODO.md)
for the current integration design and open coverage items.

[`openapi.yaml`](./openapi.yaml) is a partial, evidence-based OpenAPI 3.1
description of selected endpoints. It is not an official or complete GoodWe
contract. Captured responses are linked to their fixture files; reported and
synthetic data is labeled separately and must not be treated as verified API
behavior.

## Capturing a new endpoint or response

1. Enable `custom_components.sems: debug` logging in Home Assistant.
2. Reproduce the request or response shape and copy only the relevant redacted
   response payload from the log. The integration logs SEMS+ response data in
   redacted form; still review it manually before sharing or committing it.
3. Add the sanitized JSON response under this directory. Put legacy SEMS
   monitor responses in [`legacy/`](./legacy/); keep SEMS+ Web responses at the
   top level.
4. Add it to [`index.json`](./index.json), including provenance and any test
   consumers. Update the response reference below with its endpoint and field
   details.
5. Add or update a fixture-backed regression test before adding a production
   mapping. Include units, device type, region, and known limitations in the
   fixture or test documentation.

Never commit credentials, cookies, authorization headers, signatures, live
tokens, station IDs, serial numbers, trace IDs, or personal names. Replace
them with stable placeholders. Do not commit an unredacted browser HAR; extract
the relevant JSON response and sanitize it instead.

## Response reference

| File | Request | Token required | Main response fields |
| --- | --- | --- | --- |
| [`legacy/legacy_monitor_empty.json`](./legacy/legacy_monitor_empty.json) | `POST /api/v3/PowerStation/GetMonitorDetailByPowerstationId` with `powerStationId` in the JSON body | Legacy token from `Common/CrossLogin`, sent in the `token` header | `code`, `components`, `hasError`, `msg`, empty `data` |
| `web_cross_login.json` | `POST /web/sems/sems-user/api/v1/auth/cross-login` | Account credentials; returns a SEMS+ Web token | `code=00000`, regional `api`, `region`, Web token metadata |
| `station_list.json` | `POST /web/sems/sems-plant/api/portal/stations/page` with `current` and `size` | SEMS+ Web token and `X-Signature` | `dataList[].id`, station status, capacity, generation, and timezone |
| `browser_api_endpoints.json` | Sanitized inventory of API URLs observed in the Web UI | Web token and `X-Signature` for authenticated calls | Authentication, station, device, alarm, message, and UI-support endpoints |
| `device_start_stop.json` | `POST /web/sems/sems-remote/api/v2/address/remote/getDeviceFunctionTabMenus` and `POST /web/sems/sems-remote/api/v1/address/remote/setDeviceFunctionParameters` with address `80017` | SEMS+ Web token and `X-Signature` | Start/stop capability schema, request values, and successful response codes |
| `station_flow.json` | `GET /web/sems/sems-plant/api/stations/flow?stationId=<station_id>` | SEMS+ Web token and `X-Signature` | `id`, `name`, `status`, `pSystem`, `pAc`, `consumFlag`, `refreshTime` |
| `station_flow_import.json` | `GET /web/sems/sems-plant/api/stations/flow?stationId=<station_id>` | SEMS+ Web token and `X-Signature` | Importing example with `pGrid`, `pConsum`, and flow direction |
| [`station_flow_battery_directions.json`](./station_flow_battery_directions.json) | `GET /web/sems/sems-plant/api/stations/flow?stationId=<station_id>` | SEMS+ Web token and `X-Signature` | Four hybrid charge/discharge and import/export samples; `pBat` and `pGrid` are in kW |
| `all_status.json` | `GET /web/sems/sems-plant/api/stations/device/all-status?stationId=<station_id>` | SEMS+ Web token and `X-Signature` | `deviceDetailList`, `statusDetailList`, `snList`, `detailMap` |
| `smart_meter_all_status.json` | `GET /web/sems/sems-plant/api/stations/device/all-status?stationId=<station_id>` | SEMS+ Web token and `X-Signature` | `INVERTER` plus `SMART_METER` device discovery |
| `telemetry.json` | `GET /web/sems/sems-plant/api/equipments/<sn>/telemetry?deviceType=INVERTER&pwId=<station_id>` | SEMS+ Web token and `X-Signature` | `sn`, `hTotal`, `Temperature`, `pAc`, `qAc`, `gridPF`, `Vac`, `Iac`, `Fac`, MPPT fields |
| `smart_meter_telemetry.json` | `GET /web/sems/sems-plant/api/equipments/<meter_sn>/telemetry?deviceType=SMART_METER&pwId=<station_id>` | SEMS+ Web token and `X-Signature` | `totalPac`, per-phase power, voltage, and current |
| `telecounting.json` | `GET /web/sems/sems-plant/api/equipments/<sn>/telecounting?deviceType=INVERTER&pwId=<station_id>` | SEMS+ Web token and `X-Signature` | `pAc`, `ratedPower`, `proPvStatsToday`, `proPvStatsWeek`, `proPvStatsMonth`, `proPvStatsYear`, `proPvStatsTotal` |
| `smart_meter_telecounting.json` | `GET /web/sems-plant/api/equipments/<meter_sn>/telecounting?deviceType=SMART_METER&pwId=<station_id>` | SEMS+ Web token and `X-Signature` | `proGridStats*` and `proPurchaseStats*` import counters |
| `smart_meter_related_devices.json` | `GET /web/sems-plant/api/equipments/<sn>/relatedDevices` for `INVERTER` and `SMART_METER` | SEMS+ Web token and `X-Signature` | Both responses return an empty `data` list |
| [`semsplus_hybrid/all_status.json`](./semsplus_hybrid/all_status.json) | `GET /web/sems-plant/api/stations/device/all-status?stationId=<station_id>` | SEMS+ Web token and `X-Signature` | `INVERTER`, `BATTERY_RACK`, and `DONGLE` groups; install `addTime` |
| [`semsplus_hybrid/station_flow.json`](./semsplus_hybrid/station_flow.json) | `GET /web/sems-plant/api/stations/flow?stationId=<station_id>` | SEMS+ Web token and `X-Signature` | Hybrid `pSystem`, `pAc`, `pBat`, `pGrid`, `pConsum`, `soc`, and flow directions |
| [`semsplus_hybrid/battery_system_telemetry.json`](./semsplus_hybrid/battery_system_telemetry.json) | `GET /web/sems-plant/api/equipments/<bat_sys_sn>/telemetry?deviceType=BAT_SYS&pwId=<station_id>` | SEMS+ Web token and `X-Signature` | BAT_SYS SOC/SOH, power, voltage, current, temperature, and current limits |
| [`semsplus_hybrid/inverter_telemetry.json`](./semsplus_hybrid/inverter_telemetry.json) | `GET /web/sems-plant/api/equipments/<sn>/telemetry?deviceType=INVERTER&pwId=<station_id>` | SEMS+ Web token and `X-Signature` | Hybrid inverter AC/PV and MPPT factors |
| [`semsplus_hybrid/inverter_telecounting.json`](./semsplus_hybrid/inverter_telecounting.json) | `GET /web/sems-plant/api/equipments/<sn>/telecounting?deviceType=INVERTER&pwId=<station_id>` | SEMS+ Web token and `X-Signature` | PV, charge, and discharge counters |
| [`semsplus_hybrid/related_devices_storage_cabinet.json`](./semsplus_hybrid/related_devices_storage_cabinet.json) | `GET /web/sems-plant/api/equipments/<sn>/relatedDevices?deviceType=ENERGY_STORAGE_INTEGRATED_CABINET&pwId=<station_id>` | SEMS+ Web token and `X-Signature` | Related BAT_SYS device metadata |
| [`semsplus_hybrid/statistics_day.json`](./semsplus_hybrid/statistics_day.json) | `POST /web/sems-plant/api/stations/statistics` with local timestamp boundaries | SEMS+ Web token and `X-Signature` | Nested daily series plus flat energy summaries |
| [`semsplus_hybrid/statistics_year_2025.json`](./semsplus_hybrid/statistics_year_2025.json) | `POST /web/sems-plant/api/stations/statistics` with `dimension=year` | SEMS+ Web token and `X-Signature` | Real yearly series for lifetime aggregation |
| [`semsplus_hybrid/statistics_year_2026.json`](./semsplus_hybrid/statistics_year_2026.json) | `POST /web/sems-plant/api/stations/statistics` with `dimension=year` | SEMS+ Web token and `X-Signature` | Current-year series for lifetime aggregation |
| [`semsplus_hybrid/statistics_invalid_dimension.json`](./semsplus_hybrid/statistics_invalid_dimension.json) | `POST /web/sems-plant/api/stations/statistics` with `dimension=total` | SEMS+ Web token and `X-Signature` | Rejected `S0327` response; `total` is not supported |

The hybrid capture set and its observed units and device relationships are
documented in [`semsplus_hybrid/README.md`](./semsplus_hybrid/README.md).
The separate [`station_flow_battery_directions.json`](./station_flow_battery_directions.json)
capture records the EU installation's reported flow signs in all four
battery/grid operating states. It keeps the 19:31 portal observation, 19:32
flow response, and the time-aligned 19:33 flow response with local sensor
readings separate.

## Endpoint without a response fixture

The integration has an optional request for
`POST /web/sems-plant/api/stations/production`, but the available sanitized
evidence contains the request and not its response. Do not treat its response
fields or currency mapping as verified until a real response is sanitized and
added as a fixture. Track the capture and validation in
[`TODO.md`](../TODO.md).

## `semsplus_hybrid` capture set

The sanitized files in [`semsplus_hybrid/`](./semsplus_hybrid/) are the
incorporated hybrid capture set. They cover the hybrid station's device
discovery, station flow, inverter telemetry and counters, related BAT_SYS
metadata, and station statistics. The capture-specific README documents the
synthetic month fixture and the observed units; duplicate top-level copies are
not maintained.

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
| `getPowerStationIds` | `POST /web/sems/sems-plant/api/portal/stations/page` with `current` and `size` | SEMS+ Web token |
| `getData` | SEMS+ Web station flow, device discovery, telemetry, and telecounting requests | SEMS+ Web token |
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

## EV charger (HCA wallbox) endpoints

Derived from the SEMS+ Web UI charger page. The integration was checked
against a live HCA charger (values and every control), but no sanitized
response captures are stored yet; the tests use hand-built responses with the
same shapes. Chargers are discovered as `EV_CHARGER` devices in `all-status`.

| Purpose | Request |
| --- | --- |
| Live values / counters | `GET /web/sems/sems-plant/api/equipments/<sn>/telemetry` and `.../telecounting` with `deviceType=EV_CHARGER&pwId=<station_id>` |
| Mode settings | `GET /web/sems/sems-remote/api/ev-charger/control-item-content-list/<sn>` (`productModel`, `chargeMode`, `chargeMaxPower`) |
| Charge state | `GET /web/sems/sems-plant/api/v1/chargePile/getLastCharge?chargeSn=<sn>&pwId=<station_id>`; `chargeLog.workStu`: 0 offline, 2 fault, 6 charging, 8/10 available, 9 maintenance; `chargeLog.status` = plug status |
| Current mode and settings | `POST /web/sems/sems-remote/api/ev-charger/detail` with `{sn, productModel}`: `chargeMode`, `chargeMaxPower`, `ratedMaxiChargePower`, `buyPwrLimit`, `ensureMinimumChargingPower`, `gridControlLimitSwitch`/`gridControlLimitValue`, `dynamicLoad`/`currentLimit`, `phaseSwitch`, `lockChargingPlug`, `chargedNow` (plug and charge) |
| Change a setting | `POST /web/sems/sems-remote/api/ev-charger/set-config` with `{sn, plantId, productModel, <field>: value}`; toggles are sent as 0/1; ranges come from the mode settings' `controlItemRanges` |
| Live charging power | `stations/flow` field `pEvChar` (kW, station total) |
| Last session | `getLastCharge` `chargeLog`: `currentChargeQuantity`, `greenElec`, `purElec` (kWh), `averCharP`, `maxCharP` (kW), `chargeTimeLength` (min), `chargeStartTime`, `chargeEndTime`, `chargeEndCauseDetail`, `mileage` |
| Start / stop | `POST /web/sems/sems-remote/api/ev-charger/startCharge` or `stopCharge` with `{sn, plantId, productModel, mode}` |
| Charge mode | `POST /web/sems/sems-remote/api/ev-charger/set-mode` with `{mode, sn, plantId, productModel}`; mode 0 fast (also sends `chargeMaxPower`, `chargePowerSetted`), 1 PV, 2 PV + battery |

Also present in the UI but not implemented: `set-scheduled` / `cancel-charge` (scheduled charging), RFID
`card/*`, and `chargePile/queryChargeLogList` (session history).
