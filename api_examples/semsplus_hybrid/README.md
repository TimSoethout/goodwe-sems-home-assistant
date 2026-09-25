# SEMS+ Web captures: hybrid inverter + battery, no smart meter

Sanitized captures from a GoodWe hybrid inverter (all-status `subtype: "store"`)
with one BAT_SYS battery, taken from the SEMS+ Web UI (AU gateway,
September 2026). The station has **no `SMART_METER` device**; the inverter's own
grid CT feeds `pGrid` in the station flow. The station also lists a
`BATTERY_RACK` (telemetry is empty; battery data comes from the BAT_SYS reached
via the storage-cabinet `relatedDevices` call) and a `DONGLE`.

Serials, station IDs, trace IDs and names are placeholders.
`statistics_month_2026-08.json` is synthetic (shape copied from a real month
response); every other file is a real response with identifiers replaced.

| File | Request |
| --- | --- |
| `all_status.json` | `GET /sems-plant/api/stations/device/all-status?stationId=` |
| `inverter_telemetry.json` | `GET /sems-plant/api/equipments/<sn>/telemetry?deviceType=INVERTER&pwId=` |
| `inverter_telecounting.json` | `GET /sems-plant/api/equipments/<sn>/telecounting?deviceType=INVERTER&pwId=` |
| `related_devices_storage_cabinet.json` | `GET .../relatedDevices?sn=<sn>&deviceType=ENERGY_STORAGE_INTEGRATED_CABINET&pwId=` |
| `battery_system_telemetry.json` | `GET /sems-plant/api/equipments/<bat_sys_sn>/telemetry?deviceType=BAT_SYS&pwId=` |
| `station_flow.json` | `GET /sems-plant/api/stations/flow?stationId=` |
| `statistics_day.json`, `statistics_year_*.json`, `statistics_month_*.json` | `POST /sems-plant/api/stations/statistics` |
| `statistics_invalid_dimension.json` | same endpoint with `dimension: "total"` (rejected, `S0327`) |

## Observations

- Statistics request bodies sent by the Web UI use full local timestamps:
  `{"stationId", "isReport": false, "items": [...], "dimension": "day",
  "startTime": "2026-09-24 00:00:00", "endTime": "2026-09-24 23:59:59"}`.
- `dimension: "total"` is rejected (`S0327`) and a multi-year `year` range
  returns zeros, so lifetime totals must be summed one year at a time.
  all-status `addTime` (epoch ms) gives the install year to start from.
- Statistics summaries: `proPurchase`, `proGrid`, `proConsum`,
  `proSelfConsum`, `production` (kWh) and `contributionRate`,
  `proSelfConsumRate` (percent). Charge/discharge only appear per item in
  `dataList` (`proCharStats`, `proDischarStats`).
- Station flow (kW): `pSystem` = PV, `pAc` = inverter AC output (includes
  battery discharge on a hybrid), `pBat` + discharging / − charging,
  `pGrid` + export / − import, `pConsum` = load, `soc`.
- Inverter telemetry `pAc` on a hybrid is the AC output, i.e. PV **plus battery
  discharge**; `pDc` is total PV input.
- BAT_SYS telemetry codes on this model: `soc`, `soh`, `pBat` (kW),
  `voltage`, `a`, `batSysTemp`, `aMaxChar`, `aMaxDischar`.
