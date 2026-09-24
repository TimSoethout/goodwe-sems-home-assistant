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

- Missing detailed battery/BMS voltage, current, SOH, and temperature is
  consistent with the absence of BAT_SYS data.
- Missing station statistics is expected for the current beta, but this
  capture identifies a concrete parser/request-shape defect rather than only
  an account limitation.
- Missing HomeKit PV, grid, load, battery, SOC, and status is not fully
  explained by unavailable data: the station-flow endpoint supplies several
  of those fields, but the current code gates flow retrieval on
  `SMART_METER`.
- Generator and detailed load-status fields are not present in the reported
  flow schema, so those remain unconfirmed.
- `grid_meter_power` is not present in the reported flow or HEMS schemas and
  remains unconfirmed.
