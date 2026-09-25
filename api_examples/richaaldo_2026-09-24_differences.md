# Richaaldo EU SEMS+ Web capture

Source: [issue #219 comment 5819430659](https://github.com/TimSoethout/goodwe-sems-home-assistant/issues/219#issuecomment-5819430659), reported by [@Richaaldo](https://github.com/Richaaldo) on 2026-09-24.

The new `*_richaaldo_*_schema.json` files record response contracts only. The
source comment intentionally contained no measured telemetry, station IDs,
serial numbers, tokens, trace IDs, or account data, so placeholder strings
are retained instead of inventing values. Existing API examples are unchanged.

## Differences from the current implementation

### Station statistics

The Web UI sends `items` (plural) and `isReport: false`. The 11.5.0-beta
client sent `item` (singular) and `isReport: 0`; the implementation now uses
the observed request contract.

More importantly, the response puts the series under `data.dataList[]`, with
each entry carrying `item`, `unit`, and `statisticsList[]`. The 11.5.0-beta
parser expected each series to be a top-level dictionary and therefore did not
parse this response. The parser now handles `dataList[]` and the flat summary
fields such as
`production`, `proConsum`, `proPurchase`, `proGrid`, `proSelfConsum`,
`proSelfConsumRate`, and `contributionRate`.

### Station flow

The flow response includes `pSystem`, `pAc`, `pBat`, `pGrid`, `soc`,
`pConsum`, `flows.pBat`, and `refreshTime`. It is available for a station whose
device groups are `INVERTER`, `BATTERY_RACK`, and `DONGLE`, without a
`SMART_METER`.

The implementation now fetches station flow independently of SMART_METER
discovery and maps the reported PV, grid, load, battery, and SOC fields when
available.

### Battery/BMS details

The capture reported no `SMART_METER` and no `BAT_SYS` response. It confirms
that BAT_SYS-dependent voltage, current, SOH, and BMS-temperature entities
cannot be validated from this station. The station flow does provide `pBat`
and `soc`, which are power-flow values rather than a replacement for detailed
BMS telemetry.

### HEMS graph endpoint

The UI also successfully calls
`/sems-plant/api/v1/hems/power/statisticsAndPreV2`. Its `data.dataList[]`
contains time-series points with `{tp, power}` for `pSystem`, `pConsum`,
`pBat`, `pGrid`, `sell`, `buy`, `soc`, and `charge`. This is a separate
power-graph contract from station statistics and is not currently consumed by
the integration.

## Interpretation of the reported missing entities

The report is **partly consistent** with the current understanding:

- Missing detailed battery/BMS voltage, current, SOH, and temperature was
  initially consistent with the earlier capture, but the newer hybrid capture
  proves that BAT_SYS can be reached through the storage-cabinet related-device
  path.
- Station statistics were initially missing because of a concrete
  parser/request-shape defect; the request and nested response handling are
  now implemented and covered by fixtures.
- Missing HomeKit PV, grid, load, battery, SOC, and status was not fully
  explained by unavailable data. The station-flow endpoint now supplies
  those fields independently of `SMART_METER`.
- Generator and detailed load-status fields are not present in the reported
  flow schema, so those remain unconfirmed.
- `grid_meter_power` is not present in the reported flow or HEMS schemas and
  remains unconfirmed.

## Newer hybrid capture findings

Sources:

- [Richaaldo's full EU contract capture](https://github.com/TimSoethout/goodwe-sems-home-assistant/issues/219#issuecomment-5822419042)
- [kieranlee1970's hybrid capture and patch report](https://github.com/TimSoethout/goodwe-sems-home-assistant/issues/219#issuecomment-5823301737)
- [thisisgeoffsemail's HomeKit report](https://github.com/TimSoethout/goodwe-sems-home-assistant/issues/219#issuecomment-5822353300)
- [davcolh's AU HomeKit report](https://github.com/TimSoethout/goodwe-sems-home-assistant/issues/219#issuecomment-5828321846)

The sanitized response files prefixed `richaaldo_hybrid_` are real captures
unless their name or README says otherwise. They contain no live identifiers.

### Statistics request contract

The Web UI requires local timestamps in `YYYY-MM-DD HH:MM:SS` form. `endTime`
is the last second in the requested range, not the first instant after it.
The UI uses:

- `day` for day, week, and month ranges;
- `month` for year ranges;
- one `year` request from the plant creation date for all-time totals.

`dimension: "total"` is rejected with `S0327`. The implementation now uses
inclusive local boundaries, uses the device `addTime` year for lifetime
aggregation, retains one request per year when the API requires it, and has
request-body tests for each dimension.

It does not use `dimension: "total"` because the capture proves that value is
invalid.

### Production endpoint and currency

`POST /sems-plant/api/stations/production` returns flat daily totals for
`proSystemTotalStats`, `proGridStats`, `proPurchaseStats`, `proConsumStats`,
profit fields, and `currency` (reported as `EUR`). This is a better source for
the currency and station summary totals than reading currency from an
inverter object.

The implementation now makes this endpoint an optional Web request, uses a
valid returned currency, and uses flat production totals only to fill missing
daily chart values. Station statistics remain the primary series source.

The 2026-09-25 Home Assistant log confirms that the request is sent through
the Web gateway after successful Web authentication:

```text
Making getWebStationProduction API call to
https://eu-gateway.semsportal.com/web/sems/sems-plant/api/stations/production
```

The supplied log ends immediately after this request, so it does not contain
the production response or prove that the endpoint returned usable totals.

### BAT_SYS and battery entity shape

The newer hybrid capture reaches a related device with `type: "BAT_SYS"` and
then requests telemetry with `deviceType=BAT_SYS`. Its factors include:

- `soh` and `soc` in percent;
- `pBat` in kW;
- `voltage` in V and `a` in A;
- `batSysTemp` in degrees Celsius;
- `aMaxChar` and `aMaxDischar` in A.

The implementation now preserves the related-device record, enriches BAT_SYS
serials independently with their reported request type, reuses the existing
battery entity contract, and maps voltage, current, SOH, temperature, and
charge/discharge limits. Cell values remain separate from pack values when
present.

### Hybrid flow signs and HomeKit compatibility

The hybrid capture confirms `pSystem` is PV input, while `pAc` includes PV plus
battery discharge. `pBat` is positive while discharging and negative while
charging. `pGrid` is positive for export and negative for import. This means
mapping HomeKit PV from `pAc` can show battery discharge as solar production;
the safer PV source is `pSystem` (or inverter `pDc`).

The capture also reports that the existing HomeKit keys use the legacy
spellings `bettery` and `betteryStatus`, while the newer mapping writes
`battery` and `batteryStatus`. Grid direction must be represented by
`gridStatus`, not only by a signed grid value.

The implementation now preserves both spelling aliases, maps HomeKit PV from
`pSystem`, derives explicit grid/battery direction statuses from flow signs
and the `flows` object, and covers import/export plus charge/discharge with
fixture tests. Legacy sign behavior remains unchanged.

### Entity filtering and optional failures

The hybrid station lists `BATTERY_RACK` and `DONGLE`, but those are not
inverter devices. Creating normal inverter entities for them causes empty
requests and misleading entities. Dongle diagnostics are available from its
`information` endpoint, while dongle telecounting is empty.

The report also identifies that a failed optional station-flow, storage, or
BAT_SYS request can fail the whole coordinator update.

The implementation now filters battery racks and dongles out of normal
inverter entities and isolates optional station-flow, storage, and BAT_SYS
enrichment failures per call. The log confirms that a station with
`INVERTER`, `BATTERY_RACK`, and `DONGLE` groups can still produce usable
inverter telemetry.

### Totals, counters, and remaining reports

Lifetime values currently use raw `pro*Stats` keys instead of the existing
`buy`, `sell`, `charge`, `disCharge`, and consumption keys. The report also
identifies current-month data being assigned to `lastmonthetotle`, missing
`pmeter` without a smart meter, and single-phase stations receiving
permanently unknown phase 2/3 entities.

The implementation now normalizes statistics through one legacy-key mapping,
requests the previous completed month for `lastmonthetotle`, maps station-flow
`pGrid` to `pmeter` when no smart meter exists, and only creates phase values
when the device contract exposes those factors.

### Legacy request noise

Multiple users still see a successful Web fallback preceded by legacy
`getData` code `100002` logs. The fallback works, but the repeated error is
misleading.

This remains a logging/ordering cleanup rather than a data-availability
problem. It is not changed yet because legacy station discovery and control
paths still exist, and using the Web token for legacy calls would mix
authentication profiles. A safe fix requires separating the initial legacy
compatibility probe from the Web-only coordinator path.

### HomeKit totals still unavailable

The report from `thisisgeoffsemail` confirms that 11.6.0-beta restored HomeKit
power values but not total import/export energy. This is consistent with the
current implementation's dependency on smart-meter telecounting or a complete
statistics normalization path; it is not evidence that instantaneous flow
power can safely be converted into energy.

The statistics timestamp/range fix and legacy-key normalization are now
implemented. Total-increasing reset behavior and final HomeKit energy values
still require a real statistics response capture; instantaneous flow power is
not converted into energy.

### Open items that need additional evidence

The following differences cannot be safely fixed from the available captures:

- HEMS graph integration needs an import/export capture proving the sign and
  unit semantics match the existing Home Assistant energy entities.
- Generator and detailed load-status fields are absent from the observed
  station-flow contracts.
- `grid_meter_power` is absent from the flow and HEMS contracts.
- Production response parsing and currency use still need a log containing the
  production response; the current log only proves that the request is sent.
